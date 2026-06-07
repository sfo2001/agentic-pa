"""FastAPI app: the browser-facing API + static chat UI. The browser never reaches OpenCode."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from frontend import proposal, sweep, versioning, wiki
from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy, SessionLost
from frontend.upload import lwt_convert, store_upload

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB hard cap — prevents memory exhaustion
_UI_DIR = Path(__file__).resolve().parent / "ui"


class MessageIn(BaseModel):
    text: str


# Pydantic v2 sub-models for SweepConfirm. The regex pattern re-uses
# ``proposal.SLUG_PATTERN`` so the HTTP boundary and the apply layer
# stay in lock-step automatically.
_SWEEP_SLUG = Annotated[
    str, Field(min_length=1, max_length=64, pattern=proposal.SLUG_PATTERN)
]


class _SweepTopicEntry(BaseModel):
    slug: _SWEEP_SLUG
    section: Annotated[str, Field(min_length=1, max_length=proposal.MAX_TOPIC_SECTION_LEN)]
    text: Annotated[str, Field(min_length=1, max_length=proposal.MAX_TOPIC_TEXT_LEN)]

    @field_validator("section")
    @classmethod
    def _section_must_be_known(cls, v: str) -> str:
        """Reject section headers outside the known literal set.

        Per ``frontend.proposal.VALID_SECTIONS``. Mirrors the same check in
        ``_apply_topics`` so an unknown header is rejected at the HTTP
        boundary with a 422 rather than silently dropped by the applier.
        """
        if not proposal.is_valid_section(v):
            raise ValueError(
                f"section {v!r} not in the known literal set "
                f"{list(proposal.VALID_SECTIONS)}"
            )
        return v


class _SweepMeetingEntry(BaseModel):
    slug: _SWEEP_SLUG
    title: Annotated[str, Field(max_length=proposal.MAX_MEETING_TITLE_LEN)] = ""
    topics: list[_SWEEP_SLUG] = Field(default_factory=list, max_length=proposal.MAX_MEETING_TOPICS_PER)
    summary: Annotated[str, Field(max_length=proposal.MAX_MEETING_FIELD_LEN)] = ""
    decisions: Annotated[str, Field(max_length=proposal.MAX_MEETING_FIELD_LEN)] = ""
    actions: Annotated[str, Field(max_length=proposal.MAX_MEETING_FIELD_LEN)] = ""
    raw: Annotated[str, Field(max_length=proposal.MAX_MEETING_FIELD_LEN)] = ""


class _SweepTaskOp(BaseModel):
    id: Annotated[str, Field(pattern=proposal.ID_BARE_PATTERN)]
    op: Annotated[str, Field(pattern=r"^(complete|reprioritize|retickle)$")]
    value: str | None = None


class _SweepProposalBody(BaseModel):
    diary: str = ""
    actions: list[str] = Field(default_factory=list, max_length=proposal.MAX_ACTIONS)
    topics: list[_SweepTopicEntry] = Field(default_factory=list, max_length=proposal.MAX_TOPICS)
    meetings: list[_SweepMeetingEntry] = Field(default_factory=list, max_length=proposal.MAX_MEETINGS)
    task_ops: list[_SweepTaskOp] = Field(default_factory=list, max_length=proposal.MAX_TASK_OPS)


class SweepConfirm(BaseModel):
    proposal: _SweepProposalBody
    capture: Annotated[str, Field(max_length=256)]
    session: Annotated[str, Field(max_length=128)]
    last_id: Annotated[str, Field(max_length=128)]


def changelog_subject(agent_text: str) -> str | None:
    """Derive a commit subject from the agent's end-of-turn output.

    Prefers the last line beginning ``CHANGELOG:`` (the system prompt asks the
    agent to emit one summarising what changed); otherwise the first non-empty
    line. Returns ``None`` for empty text so callers fall back to the user prompt.
    """
    if not agent_text:
        return None
    lines = [ln.strip() for ln in agent_text.splitlines() if ln.strip()]
    if not lines:
        return None
    for ln in reversed(lines):
        if ln.upper().startswith("CHANGELOG:"):
            return ln.split(":", 1)[1].strip() or None
    return lines[0]


def create_app(proxy: NotesProxy, *, notes_root: Path | str = ".", git_dir: Path | str | None = None) -> FastAPI:
    notes_root = Path(notes_root)
    _git_dir = Path(git_dir) if git_dir is not None else None
    git_lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        versioning.ensure_repo(notes_root, git_dir=_git_dir)
        proposal.backfill_ids(notes_root)
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/api/message")
    async def post_message(msg: MessageIn):
        try:
            await proxy.send(msg.text)
        except SessionLost:
            return JSONResponse(status_code=503, content={"ok": False, "error": "session lost"})
        async with git_lock:
            # Prefer the agent's end-of-turn CHANGELOG summary as the commit
            # subject; fall back to the user's prompt.
            subject = changelog_subject(await proxy.final_agent_text()) or msg.text
            findings = wiki.run_housekeeping(notes_root)
            committed = versioning.commit_all(notes_root, subject, git_dir=_git_dir)
        return {"ok": True, "committed": committed, "lint": findings}

    @app.post("/api/undo")
    async def undo():
        try:
            async with git_lock:
                sha = versioning.revert_last(notes_root, git_dir=_git_dir)
        except RuntimeError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        return {"ok": True, "reverted": sha}

    @app.post("/api/sweep")
    async def post_sweep():
        try:
            sid = await proxy.ensure_session()
            msgs = await proxy.transcript()
        except (SessionLost, httpx.HTTPError, RuntimeError, ValueError):
            # ensure_session() doesn't wrap HTTP/RuntimeError as SessionLost
            # (only send/propose_ingest do) — do it here so the 503 path is
            # uniform: the client UI uses 503 to mean "wait and retry".
            return JSONResponse(status_code=503, content={"ok": False, "error": "session lost"})
        after = sweep.read_watermark(notes_root, sid, git_dir=_git_dir)
        window, last_id = sweep.slice_window(msgs, after_id=after)
        if not window:
            return {"ok": True, "proposal": None, "capture": None}
        stamp = sweep.make_capture_stamp()
        capture: Path | None = None
        try:
            # write_capture and propose_ingest both live inside the same
            # try/finally. If write_capture itself raises (disk full, race
            # with a concurrent delete) the capture is never created and
            # the finally short-circuits via ``capture is None``. Otherwise
            # the finally unconditionally archives the capture on every
            # exit — including the happy path — so the lead abandon
            # scenario (sweep → look → "not now" → close the panel) does
            # not leave the capture in inbox/ and inflate the inbox badge.
            capture = sweep.write_capture(notes_root, sweep.render_window_text(window), stamp=stamp)
            text = await proxy.propose_ingest(f"inbox/{capture.name}")
            prop = proposal.parse_proposal(text)
        except SessionLost:
            return JSONResponse(status_code=503, content={"ok": False, "error": "session lost"})
        except proposal.ProposalError as exc:
            # Drop the raw agent text from the response (it can include the
            # user's braindump, action text, etc.). The 502 body is fixed text
            # only.
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": f"bad proposal: {exc}"},
            )
        finally:
            # M1: /api/sweep owns the capture's lifetime. The capture is
            # archived on every exit where it was successfully written
            # (happy path, 502, 503-inner) so the lead abandon scenario
            # — sweep → no /confirm — does not orphan the capture. If
            # write_capture itself failed, capture is still None and the
            # block is a no-op. archive_capture failures (OSError) are
            # swallowed: best-effort cleanup must not mask the original
            # error.
            if capture is not None:
                try:
                    sweep.archive_capture(notes_root, capture)
                except OSError:
                    pass
        # Stash the window's last id on the proposal so confirm can advance the watermark.
        return {
            "ok": True,
            "proposal": prop,
            "capture": capture.name,
            "session": sid,
            "last_id": last_id,
        }

    @app.post("/api/sweep/confirm")
    async def post_sweep_confirm(body: SweepConfirm):
        # Resolve + path-confine the capture filename. /confirm does not
        # read or move the capture file itself (the capture was already
        # archived by /api/sweep on its happy/error path — see the
        # ``finally`` block in ``post_sweep``); this validation is defense
        # in depth so any future /confirm that does touch the file
        # inherits the same guard against a hostile or buggy client
        # supplying ``body.capture = "../opencode.json"`` and walking out
        # of inbox/.
        notes_root_resolved = notes_root.resolve()
        inbox_dir = (notes_root_resolved / "inbox").resolve()
        cap_name = (body.capture or "").strip()
        # Reject empty, too long, traversal (..\), subdirectory (/),
        # NUL byte (which makes Path.resolve() raise ValueError), and
        # the bare dot "." (would resolve to inbox_dir itself).
        if (not cap_name or len(cap_name) > 200 or ".." in cap_name
                or "\\" in cap_name or "\x00" in cap_name
                or "/" in cap_name or cap_name == "."):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "invalid capture name"},
            )
        cap_path = (inbox_dir / cap_name).resolve()
        if not cap_path.is_relative_to(inbox_dir):
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "capture escapes inbox/"},
            )
        # The Pydantic body is a model; serialise to a plain dict for the applier.
        prop_dict = body.proposal.model_dump()
        async with git_lock:
            summary = proposal.apply_proposal(notes_root, prop_dict)
            # Advance the watermark BEFORE committing: a failed watermark
            # write (disk full / permission) means the next sweep would
            # re-process the same window, creating duplicate actions. By
            # writing the watermark first, a failed commit_all leaves the
            # watermark advanced — the turn's structure is in the previous
            # commit but the next sweep won't re-process it. This is a
            # fixed-cost idempotency trade-off.
            sweep.write_watermark(notes_root, body.session, body.last_id, git_dir=_git_dir)
            findings = wiki.run_housekeeping(notes_root)
            committed = versioning.commit_all(
                notes_root, f"sweep: diary+structure {cap_name}", git_dir=_git_dir
            )
        return {"ok": True, "applied": summary, "committed": committed, "lint": findings}

    @app.get("/api/events")
    async def events():
        async def gen():
            async for evt in proxy.relay():
                yield f"data: {json.dumps(evt)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    from frontend.render import render_markdown

    @app.get("/api/file")
    async def get_file(path: str):
        base = notes_root.resolve()
        target = (base / path).resolve()
        if base != target and not target.is_relative_to(base):
            return JSONResponse(status_code=403, content={"ok": False, "error": "outside workspace"})
        if not target.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "not found"})
        text = target.read_text(encoding="utf-8", errors="replace")
        if target.suffix.lower() in (".md", ".markdown"):
            return {"path": path, "html": render_markdown(text), "text": None}
        return {"path": path, "html": None, "text": text}

    @app.get("/api/inbox")
    async def inbox():
        d = notes_root / "inbox"
        try:
            count = sum(1 for p in d.iterdir() if p.is_file() and not p.name.startswith("_")) if d.is_dir() else 0
        except PermissionError:
            count = 0
        return {"count": count}

    _PROPOSAL_FILE = "_proposal.json"

    @app.get("/api/proposal")
    async def get_proposal():
        p = notes_root / "inbox" / _PROPOSAL_FILE
        if not p.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "no pending proposal"})
        try:
            return {"ok": True, "proposal": json.loads(p.read_text(encoding="utf-8"))}
        except json.JSONDecodeError:
            return JSONResponse(status_code=500, content={"ok": False, "error": "corrupted proposal file"})

    @app.post("/api/proposal/confirm")
    async def confirm_proposal():
        from pydantic import ValidationError

        p = notes_root / "inbox" / _PROPOSAL_FILE
        # Read + validate + apply under the same git_lock: the propose tool
        # (running in a separate MCP process) can write to the staging file
        # at any time, so reading outside the lock risks unlinking a fresh
        # proposal while confirming an older one. The in-process asyncio.Lock
        # serialises concurrent confirms; the file is also written
        # atomically by presenter.server.propose (atomic_write_text), so
        # readers see either the old or the new content, never partial.
        async with git_lock:
            if not p.is_file():
                return JSONResponse(status_code=404, content={"ok": False, "error": "no pending proposal"})
            try:
                prop = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"ok": False, "error": "corrupted proposal file"})
            try:
                body = _SweepProposalBody.model_validate(prop)
            except ValidationError as exc:
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "error": "invalid proposal: "
                        + "; ".join(
                            f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}"
                            for e in exc.errors()
                        ),
                    },
                )
            try:
                task_ops = [t.model_dump() for t in body.task_ops]
                summary = proposal.apply_proposal(notes_root, prop, task_ops=task_ops)
                findings = wiki.run_housekeeping(notes_root)
                committed = versioning.commit_all(notes_root, "proposal: confirmed", git_dir=_git_dir)
            finally:
                p.unlink(missing_ok=True)
        return {"ok": True, "applied": summary, "committed": committed, "lint": findings}

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        data = b""
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_UPLOAD_BYTES:
                return JSONResponse(status_code=413, content={"ok": False, "error": "file too large"})
        try:
            result = store_upload(notes_root, file.filename or "", data, convert=lwt_convert)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        return result

    @app.get("/")
    async def index():
        return FileResponse(_UI_DIR / "index.html")

    app.mount("/ui", StaticFiles(directory=_UI_DIR), name="ui")
    return app


def _validate_url(v: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"must be a valid http:// or https:// URL (got {v!r})")
    return v


def build_default_app() -> FastAPI:
    from bootstrap_env import EnvSpec, preflight_env

    preflight_env([
        EnvSpec(
            "OPENCODE_BASE_URL", default="http://127.0.0.1:4096",
            parser=_validate_url,
            hint="base URL of the running opencode server (set by launcher/run.py)",
        ),
        EnvSpec(
            "NOTES_ROOT", default=".",
            hint="absolute path to the workspace/ directory (set by launcher/run.py)",
        ),
        EnvSpec(
            "NOTES_GIT_DIR", required=True,
            hint=(
                "absolute path to the split git-dir outside NOTES_ROOT "
                "(ADR-0005). Without it the notes .git would be created inside "
                "the agent's workspace/ sandbox, breaking confinement. "
                "Normally set by launcher/run.py."
            ),
        ),
    ])
    base = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
    notes_root = os.environ.get("NOTES_ROOT", ".")
    git_dir_env = os.environ.get("NOTES_GIT_DIR")
    if not git_dir_env:
        raise AssertionError("NOTES_GIT_DIR guaranteed by preflight_env(required=True)")
    git_dir = Path(git_dir_env)
    oc = OpenCodeClient.connect(base, agent="workspace-assistant")
    return create_app(NotesProxy(oc), notes_root=notes_root, git_dir=git_dir)
