"""Tests for the FastAPI browser-facing app."""
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

from frontend import versioning
from frontend.app import create_app
from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy
from tests.frontend.fake_opencode import make_fake_opencode


def _app_with_fake(script, *, tool_parts=()):
    oc = OpenCodeClient(
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_fake_opencode(script, tool_parts=tool_parts)),
            base_url="http://oc",
        ),
        agent="workspace-assistant",
    )
    # Use a throwaway tmp dir so lifespan.ensure_repo and commit_all never touch
    # the code repo (notes_root="." default would commit the worktree).
    _tmp = tempfile.mkdtemp()
    return create_app(NotesProxy(oc), notes_root=_tmp)


async def test_health_endpoint():
    """GET /health returns {"ok": true}."""
    app = _app_with_fake([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


async def test_message_endpoint_returns_ok():
    """POST /api/message returns {"ok": true}."""
    app = _app_with_fake([{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.post("/api/message", json={"text": "hello"})
        assert r.status_code == 200
        assert r.json()["ok"] is True


async def test_events_stream_content_type():
    """GET /api/events returns text/event-stream content-type."""
    app = _app_with_fake([
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        async with c.stream("GET", "/api/events") as resp:
            assert "text/event-stream" in resp.headers["content-type"]
            # consume stream
            async for _ in resp.aiter_lines():
                break


async def test_events_stream_message_delta_then_tool_call_then_done():
    """GET /api/events streams message_delta, tool_call, then done in order."""
    tool_parts = [
        {
            "id": "prt_1",
            "type": "tool",
            "tool": "notes_today",
            "state": {"status": "completed"},
        }
    ]
    script = [
        {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_fake", "field": "text", "delta": "hi"},
        },
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    app = _app_with_fake(script, tool_parts=tool_parts)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        chunks = []
        async with c.stream("GET", "/api/events") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunks.append(json.loads(line[6:]))
                    if chunks[-1]["type"] == "done":
                        break

    types = [c["type"] for c in chunks]
    assert "message_delta" in types
    assert "tool_call" in types
    assert types[-1] == "done"
    # Order: delta(s) before tool_call before done
    delta_idx = types.index("message_delta")
    tool_idx = types.index("tool_call")
    done_idx = types.index("done")
    assert delta_idx < tool_idx < done_idx

    # Verify content
    delta_evt = next(c for c in chunks if c["type"] == "message_delta")
    assert delta_evt["text"] == "hi"
    tool_evt = next(c for c in chunks if c["type"] == "tool_call")
    assert tool_evt["name"] == "notes_today"
    assert tool_evt["status"] == "completed"


# ── BH-22: Pattern P — events() SSE generator must handle relay() exceptions ─


async def test_bh22_events_sse_generator_handles_relay_exception():
    """BH-22: The ``gen()`` async generator in the ``events()`` endpoint
    iterates ``proxy.relay()`` without try/except. If relay() raises (before
    yielding any events), the exception propagates out of the generator,
    FastAPI serves a 500 to the SSE stream, and the browser sees a truncated
    response.

    The generator should catch exceptions and yield an error event, keeping
    the SSE stream well-formed."""
    class _CrashClient:
        """Client whose relay raises before yielding."""
        async def create_session(self):
            return "ses_fake"

        async def iter_events(self):
            raise RuntimeError("pre-yield crash")
            yield  # pragma: no cover

        async def tool_calls(self, sid):
            return []

        async def aclose(self):
            pass

    from frontend.proxy import NotesProxy
    proxy = NotesProxy(_CrashClient())  # type: ignore[arg-type]
    # Bypass the single-flight guard
    proxy._relaying = False
    proxy._session_id = "ses_fake"

    # Simulate what the events() endpoint does
    gen_crashed = False
    try:
        async for _ in proxy.relay():
            pass
    except Exception:
        gen_crashed = True

    # BUG: exception propagates instead of becoming an error event
    assert gen_crashed is False, (
        "relay() raised exception instead of yielding error event"
    )
    await proxy.aclose()


async def test_no_credential_in_browser_response():
    """OPENCODE_SERVER_PASSWORD never appears in any browser-facing response."""
    os.environ["OPENCODE_SERVER_PASSWORD"] = "super_secret_pw"
    try:
        app = _app_with_fake([])
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            health_body = (await c.get("/health")).text
            assert "super_secret_pw" not in health_body
    finally:
        del os.environ["OPENCODE_SERVER_PASSWORD"]


async def test_message_returns_503_on_session_lost():
    """POST /api/message returns 503 with {"ok": false, "error": "session lost"} on SessionLost."""

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    oc = OpenCodeClient(
        httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc"),
        agent="workspace-assistant",
    )
    from frontend.proxy import NotesProxy
    proxy = NotesProxy(oc)
    proxy._session_id = "ses_fake"  # bypass ensure_session so send() hits the message endpoint
    app = create_app(proxy, notes_root=tempfile.mkdtemp())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.post("/api/message", json={"text": "hello"})
    assert r.status_code == 503
    body = r.json()
    assert body == {"ok": False, "error": "session lost"}
    # Confirm no exception text leaks (no "connection refused" or URL in body)
    assert "connection refused" not in r.text
    assert "http://oc" not in r.text


async def test_build_default_app_reads_env(monkeypatch, tmp_path):
    """build_default_app() uses OPENCODE_BASE_URL from the environment."""
    from frontend.app import build_default_app

    monkeypatch.setenv("OPENCODE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("NOTES_GIT_DIR", str(tmp_path / "notes.git"))  # required (see below)
    # Just confirm the app can be created without error; it won't have a live server
    app = build_default_app()
    assert app is not None


def test_build_default_app_threads_notes_git_dir(monkeypatch, tmp_path):
    """build_default_app reads NOTES_GIT_DIR and passes it to create_app as git_dir.

    We monkeypatch create_app to capture the kwargs it receives, then confirm
    that git_dir matches the env var value (resolved to a Path).
    """
    from pathlib import Path

    import frontend.app as app_mod

    captured = {}

    def _spy_create_app(proxy, *, notes_root=".", git_dir=None):
        captured["git_dir"] = git_dir
        # Return a minimal stand-in so build_default_app doesn't fail
        from fastapi import FastAPI
        return FastAPI()

    fake_git_dir = str(tmp_path / "notes.git")
    monkeypatch.setenv("NOTES_GIT_DIR", fake_git_dir)
    monkeypatch.setattr(app_mod, "create_app", _spy_create_app)

    app_mod.build_default_app()

    assert captured["git_dir"] == Path(fake_git_dir)


# ── BH-31: Pattern E — config.py dict(permissions) is a dead-code copy ───────


def test_bh31_config_permissions_dict_copy_has_no_effect():
    """BH-31: frontend/config.py builds ``permissions`` as a dict literal and
    then creates a shallow copy with ``dict(permissions)`` for the top-level
    ``permission`` key (line 61) and a second copy for the agent definition
    (line 68). The top-level copy is never checked independently; only the
    agent-level copy is used. This is Pattern E (dead code / unused branch).

    The test verifies the structure is valid (no crash), documenting the
    dead-code pattern."""
    from frontend.config import build_opencode_config

    cfg = build_opencode_config(
        model_endpoint="http://inf:8000",
        model_id="inf-model",
        notes_root="/tmp/notes",
        python_executable="/usr/bin/python",
        prompt_path="/etc/prompt.md",
    )
    assert "permission" in cfg
    assert cfg["agent"]["workspace-assistant"]["permission"]["bash"] == "deny"


def test_build_default_app_requires_notes_git_dir(monkeypatch, capsys):
    """When NOTES_GIT_DIR is unset, build_default_app must refuse to start —
    otherwise the notes .git would be created inside the agent's sandbox,
    breaking confinement (ADR-0005).

    The preflight layer (ADR-0010) is the authoritative check now: required
    + unset → sys.exit(2), with a per-shell "how to set" hint. The preflight
    replaces the older RuntimeError guard; this test pins the new contract."""
    import frontend.app as app_mod

    monkeypatch.delenv("NOTES_GIT_DIR", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        app_mod.build_default_app()
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "NOTES_GIT_DIR" in err
    assert "REQUIRED" in err
    # Pre-flight includes the (now) per-platform hint. POSIX: bash + powershell.
    if os.name == "nt":
        assert "set NOTES_GIT_DIR=" in err
    else:
        assert "export NOTES_GIT_DIR=" in err


# ── BH-06: FastAPI lifespan must close the proxy on shutdown ────────────────

async def test_bh06_lifespan_calls_proxy_aclose_on_shutdown():
    """BH-06: create_app lifespan must call proxy.aclose() during app shutdown."""
    from asgi_lifespan import LifespanManager

    from frontend.app import create_app

    class _SpyProxy:
        """Minimal proxy spy that records whether aclose() was called."""

        def __init__(self):
            self.aclose_called = False
            # Attributes NotesProxy has, so create_app doesn't break
            self._session_id = None

        async def aclose(self):
            self.aclose_called = True

        # relay/send not needed for this test

    spy = _SpyProxy()
    _tmp = tempfile.mkdtemp()
    app = create_app(spy, notes_root=_tmp)

    async with LifespanManager(app):
        # Inside the lifespan context — app is started, not yet shut down
        assert not spy.aclose_called, "aclose() must NOT be called during startup"

    # After exiting LifespanManager, the shutdown event has fired
    assert spy.aclose_called, "aclose() must be called during app shutdown"


# ── Task 2 + 3: inbox, upload, index tests ──────────────────────────────────

def _app(tmp_path, script=None):
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode(script or [])),
                          base_url="http://oc"),
        agent="workspace-assistant",
    )
    return create_app(NotesProxy(oc), notes_root=tmp_path)


async def test_inbox_counts_files(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.md").write_text("x", encoding="utf-8")
    (inbox / "b.md").write_text("y", encoding="utf-8")
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/inbox")
        assert r.json() == {"count": 2}


async def test_inbox_zero_when_no_dir(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/inbox")).json() == {"count": 0}


# ── BH-19: Pattern I — inbox endpoint PermissionError → 500 ──────────────────


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod(0o000) has no effect on Windows ACLs, so the PermissionError "
    "path this test exercises can't be triggered — it would pass vacuously.",
)
async def test_bh19_inbox_permission_error_returns_graceful_error(tmp_path):
    """BH-19: GET /api/inbox must return a graceful error (not 500)
    when the inbox/ directory exists but is not readable.

    The current code calls ``d.iterdir()`` without try/except, so a
    PermissionError propagates as an unhandled HTTP 500."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    inbox.chmod(0o000)  # remove all permissions
    try:
        app = _app(tmp_path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get("/api/inbox")
            # Should not 500 — should return a graceful error response
            assert r.status_code != 500, "PermissionError caused unhandled 500"
            # Currently the bug is it returns 500; after fix it should return e.g. {"count": 0} or {"ok": false, "error": ...}
    finally:
        inbox.chmod(0o755)


async def test_upload_stores_txt(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/upload", files={"file": ("n.txt", b"hello", "text/plain")})
        assert r.status_code == 200
        assert r.json() == {"stored": "documents/n.txt", "markdown": None}
        assert (tmp_path / "documents" / "n.txt").read_bytes() == b"hello"


async def test_index_served(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/")
        assert r.status_code == 200
        body = r.text
        for marker in ('id="chat"', 'id="composer"', 'id="send"', 'id="inbox-badge"',
                       'data-prompt', 'id="upload"', 'app.js', 'id="undo"'):
            assert marker in body


async def test_upload_empty_filename_returns_400(tmp_path):
    """POST /api/upload with an empty filename returns 400 {"ok": false, ...}."""
    app = _app(tmp_path)
    # Use raw multipart so FastAPI receives filename="" as an UploadFile (not a plain field).
    raw_body = (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename=""\r\n'
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"x\r\n"
        b"--boundary--\r\n"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/upload",
            content=raw_body,
            headers={"content-type": "multipart/form-data; boundary=boundary"},
        )
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False
        assert "error" in body


# ── Changelog → commit subject ──────────────────────────────────────────────

def test_changelog_subject_prefers_changelog_line():
    from frontend.app import changelog_subject
    txt = "Processed the inbox.\nmore prose\nCHANGELOG: filed Atlas sync; +3 actions"
    assert changelog_subject(txt) == "filed Atlas sync; +3 actions"


def test_changelog_subject_falls_back_to_first_line():
    from frontend.app import changelog_subject
    assert changelog_subject("First line summary\nsecond line") == "First line summary"


def test_changelog_subject_none_when_empty():
    from frontend.app import changelog_subject
    assert changelog_subject("") is None
    assert changelog_subject("   \n  \n") is None


async def test_final_text_returns_last_assistant_text():
    fake = make_fake_opencode([], final_text="hello world")
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=fake), base_url="http://oc"),
        agent="workspace-assistant",
    )
    sid = await oc.create_session()
    assert await oc.final_text(sid) == "hello world"
    await oc.aclose()


async def test_message_commit_subject_uses_changelog(tmp_path):
    """POST /api/message commits with the agent's CHANGELOG line as the subject."""
    from asgi_lifespan import LifespanManager

    fake = make_fake_opencode(
        [{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}],
        final_text="Processed the inbox.\nCHANGELOG: filed Atlas sync; +2 actions",
    )
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=fake), base_url="http://oc"),
        agent="workspace-assistant",
    )
    notes_root = tmp_path / "workspace"
    git_dir = tmp_path / "notes.git"
    app = create_app(NotesProxy(oc), notes_root=notes_root, git_dir=git_dir)
    async with LifespanManager(app):  # runs ensure_repo (split git-dir)
        # simulate the agent having written a note this turn so the tree is dirty
        (notes_root / "tasks.todo.txt").write_text("(A) do it +atlas", encoding="utf-8")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.post("/api/message", json={"text": "Process the inbox."})
            assert r.json()["ok"] is True
    subject = subprocess.run(
        ["git", f"--git-dir={git_dir}", f"--work-tree={notes_root}", "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert subject == "notes: filed Atlas sync; +2 actions"


async def test_upload_too_large_returns_413(tmp_path, monkeypatch):
    """POST /api/upload with a body exceeding MAX_UPLOAD_BYTES returns 413."""
    import frontend.app as app_mod
    monkeypatch.setattr(app_mod, "MAX_UPLOAD_BYTES", 8)
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/upload", files={"file": ("big.txt", b"123456789", "text/plain")})
        assert r.status_code == 413
        body = r.json()
        assert body["ok"] is False
        assert "too large" in body["error"]


# ── Task 5 (plan 5): versioning wiring ──────────────────────────────────────

def _last_subject(root):
    return subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%s"],
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.asyncio
async def test_startup_inits_notes_repo(tmp_path):
    app = _app(tmp_path)                       # _app helper from earlier tests
    from asgi_lifespan import LifespanManager
    async with LifespanManager(app):
        assert versioning.is_repo(tmp_path)


@pytest.mark.asyncio
async def test_message_commits_notes_changes(tmp_path):
    versioning.ensure_repo(tmp_path)
    # simulate an agent write that happened during the (fake) turn
    (tmp_path / "tasks.todo.txt").write_text("(A) do it +x upd:2026-05-30", encoding="utf-8")
    app = _app(tmp_path, script=[{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/message", json={"text": "Process the inbox"})
        assert r.status_code == 200
        assert r.json()["committed"] is not None        # a sha
    assert _last_subject(tmp_path) == "notes: Process the inbox"


@pytest.mark.asyncio
async def test_undo_reverts_last(tmp_path):
    versioning.ensure_repo(tmp_path)
    (tmp_path / "f.md").write_text("x", encoding="utf-8")
    versioning.commit_all(tmp_path, "add f")
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/undo")
        assert r.status_code == 200 and r.json()["reverted"]
    assert not (tmp_path / "f.md").exists()


@pytest.mark.asyncio
async def test_undo_400_when_nothing_to_undo(tmp_path):
    versioning.ensure_repo(tmp_path)
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/undo")
        assert r.status_code == 400 and r.json()["ok"] is False


# ── Task 4: GET /api/file — path-confined markdown render ────────────────────

async def test_get_file_renders_markdown_confined(tmp_path):
    notes = tmp_path / "workspace"
    (notes / "topics").mkdir(parents=True)
    (notes / "topics" / "atlas.md").write_text("# Atlas\n\nbody\n", encoding="utf-8")
    app = create_app(NotesProxy(OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([])), base_url="http://oc"),
        agent="workspace-assistant")), notes_root=notes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/file", params={"path": "topics/atlas.md"})
        assert r.status_code == 200
        body = r.json()
        assert body["path"] == "topics/atlas.md"
        assert "<h1>" in body["html"] and "Atlas" in body["html"]


async def test_index_includes_presentation_pane(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/")).text
        assert 'id="pane"' in body
        assert 'id="pane-body"' in body


async def test_get_file_rejects_traversal(tmp_path):
    notes = tmp_path / "workspace"
    notes.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    app = create_app(NotesProxy(OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([])), base_url="http://oc"),
        agent="workspace-assistant")), notes_root=notes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/file", params={"path": "../secret.txt"})
        assert r.status_code == 403
        assert r.json()["ok"] is False


async def test_get_file_returns_plain_text_for_non_markdown(tmp_path):
    notes = tmp_path / "workspace"
    notes.mkdir()
    (notes / "tasks.todo.txt").write_text("(A) do it +x", encoding="utf-8")
    app = create_app(NotesProxy(OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([])), base_url="http://oc"),
        agent="workspace-assistant")), notes_root=notes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/file", params={"path": "tasks.todo.txt"})).json()
        assert body["html"] is None
        assert body["text"] == "(A) do it +x"


async def test_get_file_returns_404_for_missing_file(tmp_path):
    notes = tmp_path / "workspace"
    notes.mkdir()
    app = create_app(NotesProxy(OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([])), base_url="http://oc"),
        agent="workspace-assistant")), notes_root=notes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/file", params={"path": "topics/nope.md"})
        assert r.status_code == 404
        assert r.json()["ok"] is False


# ── Task 6: per-turn housekeeping (index + lint) wiring ─────────────────────

@pytest.mark.asyncio
async def test_message_returns_lint_findings(tmp_path):
    """POST /api/message must run wiki housekeeping and return lint findings.

    After the message is processed:
    - index.md is regenerated (housekeeping ran)
    - broken_link findings are returned in body["lint"]
    - existing keys (ok, committed) are still present (additive change)
    """
    versioning.ensure_repo(tmp_path)
    (tmp_path / "topics").mkdir(parents=True, exist_ok=True)
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\nSee [[ghost]].\n", encoding="utf-8"
    )
    app = _app(tmp_path, script=[{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/message", json={"text": "process notes"})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "lint" in body, "response must include 'lint' key from housekeeping"
    assert any(f["type"] == "broken_link" for f in body["lint"]), (
        f"expected a broken_link finding for [[ghost]] but got: {body['lint']}"
    )
    assert (tmp_path / "index.md").exists(), "housekeeping must regenerate index.md"


# ── Sweep T10 + T11: POST /api/sweep and POST /api/sweep/confirm ─────────────

_PROPOSAL_JSON = (
    '```json\n{"diary": "Atlas morning.", "actions": ["(B) call vendor +hw t:2026-06-11 upd:2026-06-04"],'
    ' "topics": [], "meetings": []}\n```'
)


def _sweep_app(transcript, *, notes_root):
    """Build a FastAPI app with a fake OpenCode whose GET /session/{sid}/message
    returns the supplied transcript (which must include a final assistant message
    whose text is _PROPOSAL_JSON — that's the agent's PROPOSE-mode reply)."""
    app_fake = make_fake_opencode([])
    app_fake.state.transcript = transcript
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app_fake), base_url="http://oc"),
        agent="workspace-assistant",
    )
    return create_app(NotesProxy(oc), notes_root=notes_root)


async def test_sweep_returns_proposal_and_does_not_write():
    from pathlib import Path

    root = tempfile.mkdtemp()
    transcript = [
        {"info": {"id": "m1", "role": "user"}, "parts": [{"type": "text", "text": "revisit atlas"}]},
        {"info": {"id": "m_final", "role": "assistant"},
         "parts": [{"type": "text", "text": _PROPOSAL_JSON}]},
    ]
    app = _sweep_app(transcript, notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["proposal"]["diary"] == "Atlas morning."
    capture_name = data["capture"]
    assert capture_name.endswith(".md")
    # Propose must not write structure yet:
    assert not (Path(root) / "diary").exists()
    # M1: /api/sweep owns the capture's lifetime — the happy path
    # archives immediately. inbox/ is empty and archive/<cap> exists,
    # so the "sweep → no /confirm" abandon path does not leave the
    # capture in inbox/ and inflate the inbox badge. This test does
    # NOT call /confirm, so it also pins the abandon contract by
    # construction: a successful /api/sweep that's never confirmed
    # must still have its capture in archive/.
    inbox = Path(root) / "inbox"
    archive = Path(root) / "archive"
    assert inbox.exists() and not any(inbox.iterdir()), (
        f"M1 happy-path cleanup failed: inbox still contains {list(inbox.iterdir())}"
    )
    assert (archive / capture_name).exists(), (
        f"M1 happy-path cleanup failed: {capture_name} not in archive/"
    )


async def test_sweep_empty_when_caught_up():
    root = tempfile.mkdtemp()
    app = _sweep_app([], notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep")
    assert r.json() == {"ok": True, "proposal": None, "capture": None}


async def test_sweep_confirm_applies_and_advances_watermark():
    from pathlib import Path

    from frontend import sweep

    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    cap = sweep.write_capture(root, "you: revisit atlas\n", stamp="2026-06-04-1430")
    app = _sweep_app([], notes_root=root)
    payload = {
        "proposal": {"diary": "Atlas morning.", "actions": ["(B) x +hw upd:2026-06-04"],
                     "topics": [], "meetings": []},
        "capture": cap.name, "session": "ses_fake", "last_id": "m9",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep/confirm", json=payload)
    assert r.status_code == 200 and r.json()["ok"] is True
    # Diary was written — pin to the date the server's clock produces (not
    # 2026-06-04 hard-coded, which was a latent time-bomb that only passed
    # on that exact day). The exact `now`-driven date is exhaustively covered
    # in ``test_apply_diary_appends_dated_section`` at the unit level.
    today = datetime.date.today().isoformat()
    assert (Path(root) / "diary" / f"{today}.md").exists()
    assert "(B) x +hw upd:2026-06-04" in (Path(root) / "tasks.todo.txt").read_text(encoding="utf-8")
    # /api/sweep/confirm does not move the capture — /api/sweep already
    # archived it on its happy path (M1). This test bypasses /api/sweep
    # (places the file directly), so the M1 archive step did not run for
    # it: the capture sits in inbox/ and archive/ is empty.
    assert cap.exists() and not (Path(root) / "archive" / cap.name).exists()  # /confirm did not archive
    assert sweep.read_watermark(root, "ses_fake") == "m9"  # advanced


async def test_sweep_confirm_empty_proposal_advances_only_watermark():
    from pathlib import Path

    from frontend import sweep

    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    cap = sweep.write_capture(root, "you: nothing actionable\n", stamp="2026-06-04-1500")
    app = _sweep_app([], notes_root=root)
    payload = {"proposal": {"diary": "", "actions": [], "topics": [], "meetings": []},
               "capture": cap.name, "session": "ses_fake", "last_id": "m10"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep/confirm", json=payload)
    assert r.status_code == 200
    assert sweep.read_watermark(root, "ses_fake") == "m10"
    assert not (Path(root) / "diary").exists()


# ── T12: agent prompt locks PROPOSE-mode contract ────────────────────────────


def test_agent_prompt_specifies_propose_mode_and_schema():
    from pathlib import Path as _P

    prompt = (_P(__file__).resolve().parents[2] / "frontend" / "assets" / "notes-agent.md").read_text(encoding="utf-8")
    assert "PROPOSE mode" in prompt
    # The structured contract the frontend parser relies on:
    for key in ('"diary"', '"actions"', '"topics"', '"meetings"'):
        assert key in prompt
    assert "do not write" in prompt.lower()


# ── Group K: /api/sweep error mapping (SessionLost → 503, ProposalError → 502) ─


async def test_sweep_returns_503_when_session_lost_during_propose_ingest():
    """K-5: /api/sweep returns 503 (not 500) when the upstream OpenCode session
    goes away during propose_ingest. Pinning the contract: the client UI
    uses 503 to mean "wait and retry" vs 502 "your message had a problem".
    """
    import httpx

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    oc = OpenCodeClient(
        httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc"),
        agent="workspace-assistant",
    )
    root = tempfile.mkdtemp()
    app = create_app(NotesProxy(oc), notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep")
    assert r.status_code == 503
    j = r.json()
    assert j["ok"] is False
    assert j["error"] == "session lost"
    # The response MUST NOT leak the raw upstream error text.
    assert "connection refused" not in j["error"]
    # M1 contract: when the failure happens *before* write_capture runs (the
    # outer-try path), no capture is created — inbox/ must stay empty so the
    # inbox badge does not inflate from this 503.
    inbox = Path(root) / "inbox"
    assert not inbox.exists() or not any(inbox.iterdir())


async def test_sweep_returns_502_when_proposal_text_is_malformed():
    """K-6: /api/sweep returns 502 (not 500/503) when the agent's PROPOSE-mode
    text can't be parsed. The 502 body MUST drop the raw agent text (which
    may carry the user's braindump) and only return a fixed error string.
    """
    transcript = [
        {"info": {"id": "m1", "role": "user"}, "parts": [{"type": "text", "text": "x"}]},
        # Malformed: not a JSON block at all
        {"info": {"id": "m_final", "role": "assistant"},
         "parts": [{"type": "text", "text": "sorry, I forgot the schema entirely"}]},
    ]
    root = tempfile.mkdtemp()
    app = _sweep_app(transcript, notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep")
    assert r.status_code == 502
    j = r.json()
    assert j["ok"] is False
    assert "forgot the schema" not in j["error"]
    # Fixed-text error only.
    assert j["error"].startswith("bad proposal:")
    # M1 contract: write_capture ran (so a capture IS in inbox/), and the
    # M1 finally block then moved it to archive/ on the 502 exit. The
    # inbox/ must be empty and archive/<cap> must exist.
    inbox = Path(root) / "inbox"
    archive = Path(root) / "archive"
    assert inbox.exists() and not any(inbox.iterdir()), (
        f"M1 cleanup failed: inbox still contains {list(inbox.iterdir())}"
    )
    assert archive.exists() and any(archive.iterdir()), (
        "M1 cleanup failed: archive/ is empty after 502 exit"
    )


# ── H-1: capture-name guards on /api/sweep/confirm are tested ────────────────


async def test_sweep_confirm_400_on_empty_capture():
    """H-1a: body.capture = "" → 400 (rejected before any file I/O)."""
    from frontend import sweep as _sweep

    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    cap = _sweep.write_capture(root, "x", stamp="2026-06-04-1430")
    app = _sweep_app([], notes_root=root)
    payload = {
        "proposal": {"diary": "", "actions": [], "topics": [], "meetings": []},
        "capture": "", "session": "ses_fake", "last_id": "m9",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep/confirm", json=payload)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid capture name"
    # Capture file MUST still exist in inbox/ — /confirm rejected the name
    # before any I/O, and the M1 archive step (which /api/sweep owns) did
    # not run because this test bypasses /api/sweep.
    assert cap.exists()


async def test_sweep_confirm_400_on_capture_with_dotdot_or_backslash():
    """H-1b: body.capture with '..' or '\\\\' → 400 (rejected pre-resolve)."""
    from frontend import sweep as _sweep

    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    _sweep.write_capture(root, "x", stamp="2026-06-04-1430")
    app = _sweep_app([], notes_root=root)
    for bad in ("../etc/passwd", "..\\windows", "sub/dir.md"):
        payload = {
            "proposal": {"diary": "", "actions": [], "topics": [], "meetings": []},
            "capture": bad, "session": "ses_fake", "last_id": "m9",
        }
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/sweep/confirm", json=payload)
        assert r.status_code == 400, f"{bad!r} should be 400, got {r.status_code}: {r.json()}"
        assert r.json()["error"] == "invalid capture name"


async def test_sweep_confirm_400_on_capture_with_null_byte():
    """H-1c: body.capture with NUL byte → 400 (defense against Path ValueError)."""
    from frontend import sweep as _sweep

    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    _sweep.write_capture(root, "x", stamp="2026-06-04-1430")
    app = _sweep_app([], notes_root=root)
    payload = {
        "proposal": {"diary": "", "actions": [], "topics": [], "meetings": []},
        "capture": "ok\x00.md", "session": "ses_fake", "last_id": "m9",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep/confirm", json=payload)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid capture name"


async def test_sweep_confirm_400_on_capture_dot():
    """M-2: body.capture = '.' (would resolve to inbox_dir itself) → 400."""
    from frontend import sweep as _sweep

    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    _sweep.write_capture(root, "x", stamp="2026-06-04-1430")
    app = _sweep_app([], notes_root=root)
    payload = {
        "proposal": {"diary": "", "actions": [], "topics": [], "meetings": []},
        "capture": ".", "session": "ses_fake", "last_id": "m9",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep/confirm", json=payload)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid capture name"


async def test_sweep_confirm_403_on_capture_escaping_inbox_via_symlink():
    """H-1d: body.capture that resolves outside inbox/ → 403 (defense in depth)."""
    import os
    from pathlib import Path


    root = tempfile.mkdtemp()
    versioning.ensure_repo(root)
    # Place a file OUTSIDE inbox/, then try to point the capture at it via
    # a name that resolves through inbox/ and out the other side.
    secret = Path(root) / "secret.md"
    secret.write_text("top secret", encoding="utf-8")
    # Use a symlink as the cap_name's content; the symlink lives in inbox/
    # and points to secret.md, so inbox_dir/<symlink> resolves to secret.md
    # (outside inbox/). is_relative_to() catches this.
    inbox = Path(root) / "inbox"
    inbox.mkdir(exist_ok=True)
    try:
        os.symlink(str(secret), str(inbox / "leak.md"))
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not supported here: {exc}")
    app = _sweep_app([], notes_root=root)
    payload = {
        "proposal": {"diary": "", "actions": [], "topics": [], "meetings": []},
        "capture": "leak.md", "session": "ses_fake", "last_id": "m9",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep/confirm", json=payload)
    assert r.status_code == 403
    assert r.json()["error"] == "capture escapes inbox/"
    # The secret file is unchanged — no archive operation happened.
    assert secret.read_text(encoding="utf-8") == "top secret"


# ── L-3: SweepConfirm.last_id / .session must have max_length (DoS hardening) ─


def test_sweep_confirm_rejects_oversized_last_id():
    """L-3: last_id over max_length → ValidationError (DoS hardening)."""
    from pydantic import ValidationError

    from frontend.app import SweepConfirm
    with pytest.raises(ValidationError):
        SweepConfirm(
            proposal={"diary": "", "actions": [], "topics": [], "meetings": []},
            capture="x.md", session="s",
            last_id="m" * 1000,  # way over the 128-char cap
        )


def test_sweep_confirm_rejects_oversized_session():
    """L-3: session over max_length → ValidationError (DoS hardening)."""
    from pydantic import ValidationError

    from frontend.app import SweepConfirm
    with pytest.raises(ValidationError):
        SweepConfirm(
            proposal={"diary": "", "actions": [], "topics": [], "meetings": []},
            capture="x.md", session="s" * 1000, last_id="m1",
        )


# ── LOW-1: /api/sweep returns 503 when propose_ingest fails (inner path) ─────


async def test_sweep_returns_503_when_propose_ingest_fails_inner_path():
    """LOW-1: /api/sweep returns 503 when session creation succeeds but
    propose_ingest itself fails with SessionLost (the inner except path).

    The existing K-5 test ensures the outer try block catches failures
    from ensure_session() / transcript(). This test exercises the INNER
    try block where propose_ingest's own send_message() fails, which
    must also yield a clean 503 with no raw error leak.
    """

    async def _handler(request):
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_fake"})
        if request.method == "GET" and "/message" in request.url.path:
            # Non-empty transcript so slice_window produces a window
            return httpx.Response(200, json=[
                {"info": {"id": "m1", "role": "user"},
                 "parts": [{"type": "text", "text": "hello"}]},
            ])
        if request.method == "POST" and "/message" in request.url.path:
            raise httpx.ConnectError("propose failed (inner path)")
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=transport, base_url="http://oc"),
        agent="workspace-assistant",
    )
    root = tempfile.mkdtemp()
    app = create_app(NotesProxy(oc), notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep")
    assert r.status_code == 503
    j = r.json()
    assert j["ok"] is False
    assert j["error"] == "session lost"
    # Must not leak the raw upstream error text.
    assert "propose failed" not in j["error"]
    # M1 contract: write_capture ran in the inner-try, then SessionLost
    # raised, then the M1 finally archived the orphan. inbox/ is empty,
    # archive/<cap> exists.
    inbox = Path(root) / "inbox"
    archive = Path(root) / "archive"
    assert inbox.exists() and not any(inbox.iterdir()), (
        f"M1 cleanup failed: inbox still contains {list(inbox.iterdir())}"
    )
    assert archive.exists() and any(archive.iterdir()), (
        "M1 cleanup failed: archive/ is empty after the 503 exit"
    )


# ── LOW: M1 OSError swallow + write_capture-fails race fix ─────────────────


async def test_sweep_archive_capture_oserror_does_not_mask_502(monkeypatch):
    """LOW: M1's ``except OSError: pass`` in the finally block must not
    mask the original 502 response when ``archive_capture`` itself raises.
    The capture stays in inbox/ (next sweep retries it) and the user sees
    a clean 502, not a 500 or a crash.
    """
    from frontend import sweep as _sweep

    def _raise_oserror(_root, _cap):
        raise OSError("simulated permission denied on archive")

    monkeypatch.setattr(_sweep, "archive_capture", _raise_oserror)

    transcript = [
        {"info": {"id": "m1", "role": "user"}, "parts": [{"type": "text", "text": "x"}]},
        {"info": {"id": "m_final", "role": "assistant"},
         "parts": [{"type": "text", "text": "sorry, I forgot the schema entirely"}]},
    ]
    root = tempfile.mkdtemp()
    app = _sweep_app(transcript, notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/sweep")
    # 502 is returned cleanly — the OSError did not leak into the response.
    assert r.status_code == 502
    assert r.json()["error"].startswith("bad proposal:")
    # The capture is still in inbox/ (archive_capture failed). It will be
    # picked up by the next sweep attempt — the documented retry path.
    inbox = Path(root) / "inbox"
    assert inbox.exists() and any(inbox.iterdir()), (
        "archive_capture failed; capture should remain in inbox/ for retry"
    )


async def test_sweep_write_capture_failure_skips_archive(monkeypatch):
    """MEDIUM: when ``sweep.write_capture`` itself raises (disk full,
    permission denied, race with a concurrent delete), no capture is ever
    created — the M1 finally must skip the archive (no orphan to clean up)
    rather than crash on a NameError or try to move a non-existent file.

    ASGITransport defaults to ``raise_app_exceptions=True``, so the OSError
    surfaces in the test as the original exception — not a NameError on
    the unbound ``capture`` reference. That is exactly the contract we
    want to pin: an unexpected error in write_capture propagates cleanly,
    and the finally block does the right thing (skip archive, no crash).
    """
    from frontend import sweep as _sweep

    def _raise_oserror(_root, _text, *, stamp):
        raise OSError("simulated write_capture failure (disk full)")

    monkeypatch.setattr(_sweep, "write_capture", _raise_oserror)

    transcript = [
        {"info": {"id": "m1", "role": "user"}, "parts": [{"type": "text", "text": "x"}]},
        {"info": {"id": "m_final", "role": "assistant"},
         "parts": [{"type": "text", "text": _PROPOSAL_JSON}]},
    ]
    root = tempfile.mkdtemp()
    app = _sweep_app(transcript, notes_root=root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        with pytest.raises(OSError, match="simulated write_capture failure"):
            await c.post("/api/sweep")
    # No inbox/ or archive/ was created (capture never landed).
    assert not (Path(root) / "inbox").exists()
    assert not (Path(root) / "archive").exists()
