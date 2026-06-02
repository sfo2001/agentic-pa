"""Tests for the FastAPI browser-facing app."""
import json
import os
import subprocess
import sys
import tempfile

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


def test_build_default_app_requires_notes_git_dir(monkeypatch):
    """When NOTES_GIT_DIR is unset, build_default_app must refuse to start —
    otherwise the notes .git would be created inside the agent's sandbox,
    breaking confinement (ADR-0005)."""
    import frontend.app as app_mod

    monkeypatch.delenv("NOTES_GIT_DIR", raising=False)
    with pytest.raises(RuntimeError, match="NOTES_GIT_DIR"):
        app_mod.build_default_app()


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
