"""FastAPI app: the browser-facing API + static chat UI. The browser never reaches OpenCode."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from frontend import versioning, wiki
from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy, SessionLost
from frontend.upload import lwt_convert, store_upload

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB hard cap — prevents memory exhaustion
_UI_DIR = Path(__file__).resolve().parent / "ui"


class MessageIn(BaseModel):
    text: str


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
            count = sum(1 for p in d.iterdir() if p.is_file()) if d.is_dir() else 0
        except PermissionError:
            count = 0
        return {"count": count}

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


def build_default_app() -> FastAPI:
    base = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
    notes_root = os.environ.get("NOTES_ROOT", ".")
    git_dir_env = os.environ.get("NOTES_GIT_DIR")
    if not git_dir_env:
        raise RuntimeError(
            "NOTES_GIT_DIR must be set to the split git-dir outside the sandbox "
            "(e.g. <install-root>/notes.git). Start via launcher/run.py, or set it "
            "explicitly. Without it the notes .git would be created inside the "
            "agent's workspace/ sandbox, breaking confinement (ADR-0005)."
        )
    git_dir = Path(git_dir_env)
    oc = OpenCodeClient.connect(base, agent="workspace-assistant")
    return create_app(NotesProxy(oc), notes_root=notes_root, git_dir=git_dir)
