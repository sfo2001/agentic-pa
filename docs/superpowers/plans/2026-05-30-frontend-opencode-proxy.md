# Frontend — OpenCode Proxy & SSE Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend half of the notes frontend — a Python web service that is the *sole* OpenCode HTTP client: it owns one long-lived session, relays the OpenCode event stream to the browser as SSE, and never exposes the OpenCode server or its credential to the browser.

**Architecture:** A small FastAPI app (`frontend/app.py`) exposes a browser-facing API (`/health`, `POST /api/message`, `GET /api/events`). It delegates to an async OpenCode client (`frontend/opencode_client.py`, talks to `opencode serve` over HTTP with basic auth) and a session/relay layer (`frontend/proxy.py`, one session, transforms OpenCode events → a small browser event model). All messages target the `workspace-assistant` agent. Unit tests run against an in-process **fake OpenCode** ASGI server (no network, deterministic); one integration smoke runs against a real `opencode serve`.

**Tech Stack:** Python 3.12 · FastAPI + uvicorn · httpx (async, streaming) · pytest + pytest-asyncio · stdlib `json`. (Pins the frontend framework left open in the implementation plan's N0.)

**Scope note:** Plan **3 of (now) 5** for Milestone 1 (design `mvp-chief-of-staff-notes-design.md` §3.2/§5.3/§7.5; plan WP **N3**; mirrors the general spec's WP2). Plans 1–2 (Agenda service; OpenCode config + wiring) are merged on `main`. Follow-ups: **plan 4 = N4** (chat UI + notes buttons + upload + changelog render), **plan 5 = N5** (frontend-owned `notes/` git versioning), then N6–N7 (launcher + integration). This plan builds NO browser UI — it exposes the API the UI will consume and is verified with a test client.

**Verified integration facts (from plan 2):**
- `opencode serve --hostname 127.0.0.1 --port <p>` exposes an OpenAPI at `/doc`, `GET /global/health`, session endpoints, `POST /session/{id}/message`, `GET /event` (SSE), `GET /mcp`.
- `OPENCODE_CONFIG` is NOT honored (1.15.0); `opencode serve` discovers config by directory-walk from its CWD, so it must be launched from the notes-mvp dir. (Launching is the launcher's job — plan for N6; here we assume a serve is reachable.)
- The restricted agent is `workspace-assistant`; **all traffic must target that agent** or the unrestricted default agent is used (a sandbox escape — confirmed in plan 2).
- Optional basic auth via `OPENCODE_SERVER_PASSWORD` (username `opencode`).

**Browser-facing event model (consumed by N4):** the proxy relays a small, stable JSON shape, decoupled from OpenCode's internal events:
- `{"type":"message_delta","text":"<chunk>"}` — assistant text chunk (from `message.part.delta`, `properties.delta`).
- `{"type":"tool_call","name":"agenda_today","status":"completed"}` — a tool invocation. **Emitted post-idle** by fetching `GET /session/{sid}/message` after `session.idle` fires; tool calls do NOT appear in the SSE stream.
- `{"type":"done"}` — assistant turn finished (emitted after all tool_call events).
- `{"type":"error","kind":"session_lost|upstream","message":"<text>"}`.

**Verified SSE facts (from spike, `docs/decisions/D-opencode-http.md`):**
- Text delta: `{"type":"message.part.delta","properties":{"sessionID":"...","field":"text","delta":"<chunk>"}}` — text at `properties.delta`.
- Turn done: `{"type":"session.idle","properties":{"sessionID":"..."}}` — filter by `properties.sessionID`.
- `GET /event` is global (all sessions); proxy must filter by `properties.sessionID`.
- Tool calls NOT in SSE; after `session.idle`, fetch `GET /session/{sid}/message` → `[{info:{role:"assistant",...},parts:[...]}]`; tool parts have `type:"tool"`, `tool:"<name>"`, `state.status:"completed"`.

**Files created by this plan:**
- `frontend/__init__.py`, `frontend/pyproject.toml`, `frontend/requirements-dev.txt`
- `frontend/opencode_client.py` — async OpenCode HTTP client.
- `frontend/proxy.py` — session lifecycle + event transform.
- `frontend/app.py` — FastAPI app (browser API).
- `frontend/events.py` — the browser event model + OpenCode→browser mapping (pure, unit-tested).
- `tests/frontend/fake_opencode.py` — in-process fake OpenCode ASGI app for tests.
- `tests/frontend/test_*.py`
- `docs/decisions/D-opencode-http.md` — spike output (the confirmed HTTP surface).

---

### Task 0: Frontend package skeleton + deps

**Files:**
- Create: `frontend/__init__.py`, `frontend/pyproject.toml`, `frontend/requirements-dev.txt`, `tests/frontend/__init__.py`

- [ ] **Step 1: Create the package + project files**

`frontend/__init__.py`:

```python
"""Browser-facing web service: the sole OpenCode HTTP client and SSE relay."""

__version__ = "0.1.0"
```

`frontend/pyproject.toml`:

```toml
[project]
name = "notes-frontend"
version = "0.1.0"
description = "OpenCode proxy + SSE backend for the Chief-of-Staff Notes assistant"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
    "httpx>=0.27,<1",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = [".."]
include = ["frontend*"]
```

`frontend/requirements-dev.txt`:

```
pytest>=8.0
pytest-asyncio>=0.24
pytest-cov>=5.0
asgi-lifespan>=2.1
```

Create empty `tests/frontend/__init__.py`.

- [ ] **Step 2: Install into the repo venv**

```bash
.venv/bin/pip install -e ./frontend
.venv/bin/pip install -r frontend/requirements-dev.txt
```

Expected: installs fastapi, uvicorn, httpx, pytest-asyncio, asgi-lifespan without error.

- [ ] **Step 3: Configure pytest-asyncio**

Append to the existing `pytest.ini` (under `[pytest]`): `asyncio_mode = auto`. If `pytest.ini` does not exist, create it:

```ini
[pytest]
pythonpath = .
addopts = --import-mode=importlib
asyncio_mode = auto
```

- [ ] **Step 4: Verify import + commit**

```bash
.venv/bin/python -c "import frontend; print(frontend.__version__)"   # 0.1.0
git add frontend/ tests/frontend/__init__.py pytest.ini
git commit -m "feat(frontend): package skeleton + web deps"
```

---

### Task 1 (SPIKE): Confirm the OpenCode HTTP surface

**Goal:** Pin exactly how to (a) create a session, (b) send a message targeting the `workspace-assistant` agent, and (c) read streamed events — for OpenCode 1.15.0. A build task depends on this.

**Files:**
- Create: `docs/decisions/D-opencode-http.md`

- [ ] **Step 1: Start a serve and dump the OpenAPI**

```bash
cd notes-mvp/sample-notes   # so serve finds notes-mvp/opencode.json (directory-walk)
opencode serve --hostname 127.0.0.1 --port 4178 > /tmp/oc-spike.log 2>&1 &
echo $! > /tmp/oc-spike.pid; sleep 4
curl -s http://127.0.0.1:4178/doc > /tmp/oc-openapi.json
```

- [ ] **Step 2: Extract the relevant paths and schemas**

```bash
.venv/bin/python - <<'PY'
import json
d = json.load(open("/tmp/oc-openapi.json"))
for path, item in sorted(d.get("paths", {}).items()):
    if any(k in path for k in ("session", "event", "message", "health")):
        print(path, sorted(item.keys()))
PY
```

Record the exact paths/methods.

- [ ] **Step 3: Find how to select the agent on a message**

Inspect the request body schema for the send-message operation (look for an `agent` / `agentName` field) and how a session is created. Empirically probe: create a session, post a message with the agent field, read `/event`, and confirm the `workspace-assistant` agent (sandboxed) handled it — i.e. a follow-up "use bash" message is refused (as in plan 2). Capture the exact field name.

- [ ] **Step 4: Write the decision record and stop the serve**

Create `docs/decisions/D-opencode-http.md` recording, for the pinned OpenCode 1.15.0:
- session create: method + path + minimal body (+ how the agent is bound: at session creation vs per message).
- send message: method + path + the exact field that selects the `workspace-assistant` agent + the message text field.
- events: the `GET /event` SSE framing and the JSON event shapes that carry (i) assistant text deltas and (ii) tool-call start/finish, with the field names this plan's mapper will read.
- auth: how `OPENCODE_SERVER_PASSWORD` is supplied (basic auth header).

```bash
kill "$(cat /tmp/oc-spike.pid)"; sleep 1
```

**Acceptance:** `docs/decisions/D-opencode-http.md` exists and names exact paths, the agent-selection field, and the two event shapes — no "TBD".

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/D-opencode-http.md
git commit -m "docs(frontend): spike — OpenCode 1.15.0 HTTP surface decision record"
```

---

### Task 2: The browser event model + OpenCode→browser mapper (pure)

**Files:**
- Create: `frontend/events.py`
- Test: `tests/frontend/test_events.py`

- [x] **Step 1: Write the failing test**

`tests/frontend/test_events.py` (uses confirmed 1.15.0 shapes from `D-opencode-http.md`):

```python
from frontend.events import to_browser_events


def test_text_delta_becomes_message_delta():
    """message.part.delta with field=text maps to message_delta using properties.delta."""
    oc = {
        "type": "message.part.delta",
        "properties": {"sessionID": "ses_test", "field": "text", "delta": "Hello world"},
    }
    assert to_browser_events(oc) == [{"type": "message_delta", "text": "Hello world"}]


def test_session_idle_becomes_done():
    oc = {"type": "session.idle", "properties": {"sessionID": "ses_test"}}
    assert to_browser_events(oc) == [{"type": "done"}]


def test_unknown_event_is_ignored():
    assert to_browser_events({"type": "server.connected"}) == []
    assert to_browser_events({"type": "server.heartbeat"}) == []


def test_tool_calls_not_in_sse():
    """Tool calls do NOT appear in SSE — confirmed by spike. Any such event is ignored."""
    oc = {"type": "message.part.delta", "properties": {"sessionID": "ses_fake", "field": "text", "delta": "hi"}}
    assert to_browser_events(oc) == [{"type": "message_delta", "text": "hi"}]
```

**NOTE:** Tool handling is NOT in `to_browser_events`. Tool events are emitted by `proxy.relay()` after `session.idle` by fetching `GET /session/{sid}/message`. The `events.py` mapper is text-delta-only.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_events.py -v`
Expected: FAIL — `No module named 'frontend.events'`.

- [x] **Step 3: Implement the mapper**

`frontend/events.py` (confirmed 1.15.0 shapes — text at `properties.delta`, NO tool handling):

```python
"""Pure mapping from OpenCode SSE events to the browser event model.

Confirmed OpenCode 1.15.0 shapes (docs/decisions/D-opencode-http.md):
- Text delta: type="message.part.delta", properties.field="text", properties.delta=<chunk>
- Turn done:  type="session.idle"
- Tool calls: NOT in SSE — fetched post-idle via GET /session/{sid}/message (proxy.py)
"""
from __future__ import annotations


def to_browser_events(oc_event: dict) -> list[dict]:
    """Translate one OpenCode SSE event into zero or more browser events."""
    etype = oc_event.get("type")

    if etype == "session.idle":
        return [{"type": "done"}]

    if etype == "message.part.delta":
        props = oc_event.get("properties", {})
        if props.get("field") == "text":
            delta = props.get("delta", "")
            if delta:
                return [{"type": "message_delta", "text": delta}]

    return []
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_events.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/events.py tests/frontend/test_events.py
git commit -m "feat(frontend): OpenCode->browser event mapper"
```

---

### Task 3: Fake OpenCode server (test harness)

A minimal in-process ASGI app mimicking the OpenCode endpoints we use, so the client/proxy are tested deterministically without a real model.

**Files:**
- Create: `tests/frontend/fake_opencode.py`
- Test: `tests/frontend/test_fake_opencode.py`

- [x] **Step 1: Write the failing test**

`tests/frontend/test_fake_opencode.py` — tests use confirmed 1.15.0 shapes. Script events must include `properties.sessionID` for proxy session filtering.

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_fake_opencode.py -v`
Expected: FAIL — `No module named 'tests.frontend.fake_opencode'`.

- [x] **Step 3: Implement the fake**

`tests/frontend/fake_opencode.py`:

```python
"""Minimal in-process fake of the OpenCode 1.15.0 HTTP API for tests."""
from __future__ import annotations
import asyncio, json
from collections.abc import Sequence
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


def make_fake_opencode(script: list[dict], *, tool_parts: Sequence[dict] = ()) -> FastAPI:
    """Factory for the fake server.

    script: SSE events for GET /event (each must include properties.sessionID).
    tool_parts: ToolPart dicts for GET /session/{sid}/message (empty → returns []).
    app.state.fake = {"sessions": [...], "messages": [...]}
    """
    app = FastAPI()
    state: dict = {"sessions": [], "messages": []}

    @app.get("/global/health")
    async def health():
        return {"healthy": True, "version": "fake"}

    @app.post("/session")
    async def create_session(request: Request):
        body = await request.json()
        state["sessions"].append({"agent": body.get("agent")})
        return {"id": "ses_fake"}

    @app.post("/session/{sid}/message")
    async def send_message(sid: str, request: Request):
        body = await request.json()
        state["messages"].append({"sid": sid, "body": body})
        return {"ok": True}

    @app.get("/event")
    async def event_stream():
        async def gen():
            for evt in script:
                yield f"data: {json.dumps(evt)}\n\n"
                await asyncio.sleep(0)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/session/{sid}/message")
    async def get_messages(sid: str):
        """Returns [{info: {role:"assistant", ...}, parts: [...tool_parts]}] or []."""
        if not tool_parts:
            return []
        return [{
            "info": {"id": "msg_fake", "sessionID": sid, "role": "assistant",
                     "time": {"created": 0, "completed": 0}},
            "parts": list(tool_parts),
        }]

    app.state.fake = state
    return app
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_fake_opencode.py -v`
Expected: PASS (6 passed).

- [x] **Step 5: Commit**

```bash
git add tests/frontend/fake_opencode.py tests/frontend/test_fake_opencode.py
git commit -m "test(frontend): in-process fake OpenCode server with confirmed shapes"
```

---

### Task 4: OpenCode async client

**Files:**
- Create: `frontend/opencode_client.py`
- Test: `tests/frontend/test_opencode_client.py`

- [ ] **Step 1: Write the failing test**

`tests/frontend/test_opencode_client.py`:

```python
import httpx
import pytest

from frontend.opencode_client import OpenCodeClient
from tests.frontend.fake_opencode import make_fake_opencode


def _client_for(app):
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://oc")
    return OpenCodeClient(http, agent="workspace-assistant")


async def test_health_create_send():
    app = make_fake_opencode(script=[])
    oc = _client_for(app)
    assert await oc.healthy() is True
    sid = await oc.create_session()
    assert sid == "ses_fake"
    await oc.send_message(sid, "hello")
    msg = app.state.fake["messages"][0]
    assert msg["body"]["agent"] == "workspace-assistant"
    assert msg["body"]["parts"][0]["text"] == "hello"
    await oc.aclose()


async def test_iter_events_parses_sse_json():
    script = [
        {"type": "message.part.delta",
         "properties": {"sessionID": "ses_fake", "field": "text", "delta": "yo"}},
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    app = make_fake_opencode(script=script)
    oc = _client_for(app)
    got = []
    async for evt in oc.iter_events():
        got.append(evt.get("type"))
        if evt.get("type") == "session.idle":
            break
    assert "message.part.delta" in got and "session.idle" in got
    await oc.aclose()


async def test_tool_calls_returns_tool_parts():
    tool_parts = [{"id": "prt_1", "type": "tool", "tool": "agenda_today",
                   "state": {"status": "completed"}}]
    app = make_fake_opencode(script=[], tool_parts=tool_parts)
    oc = _client_for(app)
    calls = await oc.tool_calls("ses_fake")
    assert calls == [{"name": "agenda_today", "status": "completed"}]
    await oc.aclose()
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_opencode_client.py -v`
Expected: FAIL — `No module named 'frontend.opencode_client'`.

- [x] **Step 3: Implement the client**

`frontend/opencode_client.py` — adds `tool_calls(sid)` which fetches
`GET /session/{sid}/message` → `[{info, parts}]` and extracts tool parts:

```python
async def tool_calls(self, session_id: str) -> list[dict]:
    r = await self._http.get(f"/session/{session_id}/message")
    r.raise_for_status()
    messages = r.json()  # list of {info: {role, ...}, parts: [...]}
    # Scans all assistant messages (multi-turn fix) — a model turn can produce
    # multiple assistant messages (reasoning/tool-call turn + final text-only answer).
    # Scanning only assistant_messages[-1] misses tool parts in earlier messages.
    result = []
    for m in messages:
        if m.get("info", {}).get("role") != "assistant":
            continue
        for part in m.get("parts", []):
            if part.get("type") == "tool":
                result.append(
                    {
                        "name": part.get("tool", "unknown"),
                        "status": part.get("state", {}).get("status", "unknown"),
                    }
                )
    return result
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_opencode_client.py -v`
Expected: PASS (6 passed).

- [x] **Step 5: Commit**

```bash
git add frontend/opencode_client.py tests/frontend/test_opencode_client.py
git commit -m "feat(frontend): async OpenCode HTTP client (agent-targeted, basic auth, tool_calls)"
```

---

### Task 5: Session/relay proxy

**Files:**
- Create: `frontend/proxy.py`
- Test: `tests/frontend/test_proxy.py`

- [ ] **Step 1: Write the failing test**

`tests/frontend/test_proxy.py`:

```python
import httpx
import pytest

from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy
from tests.frontend.fake_opencode import make_fake_opencode


def _proxy_for(app):
    oc = OpenCodeClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                          base_url="http://oc"),
                        agent="workspace-assistant")
    return NotesProxy(oc)


@pytest.mark.asyncio
async def test_one_session_reused():
    proxy = _proxy_for(make_fake_opencode(script=[{"type": "session.idle"}]))
    s1 = await proxy.ensure_session()
    s2 = await proxy.ensure_session()
    assert s1 == s2 == "ses_fake"
    await proxy.aclose()


async def test_relay_maps_events_to_browser_model():
    script = [
        {"type": "message.part.delta",
         "properties": {"sessionID": "ses_fake", "field": "text", "delta": "hi"}},
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    proxy = _proxy_for(make_fake_opencode(script=script))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    assert {"type": "message_delta", "text": "hi"} in out
    assert out[-1] == {"type": "done"}
    await proxy.aclose()


async def test_relay_ignores_events_for_other_sessions():
    """Events for other sessions are silently dropped."""
    script = [
        {"type": "message.part.delta",
         "properties": {"sessionID": "ses_OTHER", "field": "text", "delta": "interloper"}},
        {"type": "message.part.delta",
         "properties": {"sessionID": "ses_fake", "field": "text", "delta": "ours"}},
        {"type": "session.idle", "properties": {"sessionID": "ses_OTHER"}},
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    proxy = _proxy_for(make_fake_opencode(script=script))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    texts = [e["text"] for e in out if e["type"] == "message_delta"]
    assert "interloper" not in texts and "ours" in texts
    await proxy.aclose()
```

- [x] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_proxy.py -v`
Expected: FAIL — `No module named 'frontend.proxy'`.

- [x] **Step 3: Implement the proxy**

`frontend/proxy.py` — key behaviours vs old plan:
1. Filters events: `if event_sid is not None and event_sid != sid: continue`
2. On `session.idle`, calls `tool_calls(sid)` and yields `tool_call` events before `done`
3. Does NOT yield `done` from `to_browser_events(oc_event)` — intercepts `session.idle` directly

```python
async def relay(self) -> AsyncIterator[dict]:
    sid = self._session_id or await self.ensure_session()
    try:
        async for oc_event in self._oc.iter_events():
            props = oc_event.get("properties", {})
            event_sid = props.get("sessionID")
            if event_sid is not None and event_sid != sid:
                continue  # ignore other sessions
            if oc_event.get("type") == "session.idle":
                for tc in await self._oc.tool_calls(sid):
                    yield {"type": "tool_call", "name": tc["name"], "status": tc["status"]}
                yield {"type": "done"}
                return
            for browser_evt in to_browser_events(oc_event):
                yield browser_evt
    except httpx.HTTPError as exc:
        yield {"type": "error", "kind": "session_lost", "message": str(exc)}
```

- [x] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_proxy.py -v`
Expected: PASS (6 passed).

- [x] **Step 5: Commit**

```bash
git add frontend/proxy.py tests/frontend/test_proxy.py
git commit -m "feat(frontend): single-session proxy, session filter, post-idle tool fetch"
```

---

### Task 6: FastAPI app (browser API)

**Files:**
- Create: `frontend/app.py`
- Test: `tests/frontend/test_app.py`

- [ ] **Step 1: Write the failing test**

`tests/frontend/test_app.py`:

```python
import httpx
import pytest

from frontend.app import create_app
from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy
from tests.frontend.fake_opencode import make_fake_opencode


def _app_with_fake(script):
    oc = OpenCodeClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode(script)),
                                          base_url="http://oc"),
                        agent="workspace-assistant")
    return create_app(NotesProxy(oc))


@pytest.mark.asyncio
async def test_health_endpoint():
    app = _app_with_fake([{"type": "session.idle"}])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/health")).json()["ok"] is True


@pytest.mark.asyncio
async def test_message_then_events_stream():
    app = _app_with_fake([
        {"type": "message.part.delta", "properties": {"sessionID": "ses_fake", "field": "text", "delta": "hi"}},
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post("/api/message", json={"text": "hello"})).status_code == 200
        chunks = []
        async with c.stream("GET", "/api/events") as resp:
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunks.append(line)
                    if "done" in line:
                        break
        assert any("message_delta" in ln and "hi" in ln for ln in chunks)


@pytest.mark.asyncio
async def test_no_credential_in_browser_responses():
    import os
    os.environ["OPENCODE_SERVER_PASSWORD"] = "s3cret"
    app = _app_with_fake([{"type": "session.idle"}])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        body = (await c.get("/health")).text
        assert "s3cret" not in body
    del os.environ["OPENCODE_SERVER_PASSWORD"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_app.py -v`
Expected: FAIL — `No module named 'frontend.app'`.

- [ ] **Step 3: Implement the app**

`frontend/app.py`:

```python
"""FastAPI app: the browser-facing API. The browser never reaches OpenCode."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy


class MessageIn(BaseModel):
    text: str


def create_app(proxy: NotesProxy) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/api/message")
    async def post_message(msg: MessageIn):
        await proxy.send(msg.text)
        return {"ok": True}

    @app.get("/api/events")
    async def events():
        async def gen():
            async for evt in proxy.relay():
                yield f"data: {json.dumps(evt)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def build_default_app() -> FastAPI:
    """Production wiring: connect to a running opencode serve."""
    base = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
    oc = OpenCodeClient.connect(base, agent="workspace-assistant")
    return create_app(NotesProxy(oc))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_app.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole frontend suite + commit**

```bash
.venv/bin/pytest tests/frontend/ -v
git add frontend/app.py tests/frontend/test_app.py
git commit -m "feat(frontend): FastAPI browser API (message + SSE relay)"
```

---

### Task 7: Integration smoke against a real opencode serve

**Files:** none committed (a documented manual check; keep it out of the default test run since it needs a live model).

- [ ] **Step 1: Document and run the smoke**

With a real serve (started from `notes-mvp/sample-notes` so it finds the config), point the app at it and drive one message. Add this as a section to `frontend/README.md` (create it):

```markdown
# notes-frontend — OpenCode proxy + SSE backend

The sole OpenCode HTTP client. Exposes `/health`, `POST /api/message`,
`GET /api/events` (SSE). The browser talks only to this service.

## Run (against a running opencode serve)

    cd notes-mvp/sample-notes
    opencode serve --hostname 127.0.0.1 --port 4096 &   # finds notes-mvp/opencode.json
    OPENCODE_BASE_URL=http://127.0.0.1:4096 \
      .venv/bin/uvicorn --factory frontend.app:build_default_app --port 8000

## Integration smoke

    curl -s localhost:8000/health                                 # {"ok":true}
    curl -s -XPOST localhost:8000/api/message -H 'content-type: application/json' \
      -d '{"text":"What should I focus on today?"}'
    curl -s -N localhost:8000/api/events                          # streams message_delta/tool_call/done

Expected: the events stream shows a `tool_call` for `agenda_today` and
`message_delta` chunks naming the do-now item, then `done`.
```

- [ ] **Step 2: Run the smoke and confirm**

Start the serve + app per the README, then run the three curls. Confirm `/health` is `{"ok":true}`, the message POST returns `{"ok":true}`, and `/api/events` streams `tool_call`/`message_delta`/`done`. (Uses the fast A3B model.) Record the observed event stream. Stop both processes.

- [ ] **Step 3: Commit the README**

```bash
git add frontend/README.md
git commit -m "docs(frontend): run + integration-smoke instructions"
```

---

## Self-Review

**Spec coverage (design §3.2/§5.3/§7.5, spec WP2):**
- Sole OpenCode HTTP client, basic auth from `OPENCODE_SERVER_PASSWORD` → Task 4 ✓
- Exactly one long-lived session, reused → Task 5 (`ensure_session`) ✓
- SSE relay of assistant deltas AND tool-call events → Tasks 2/5/6 ✓
- Browser never reaches OpenCode; credential never browser-bound → Task 6 (`test_no_credential_in_browser_responses`; the app exposes only `/health`+`/api/*`, no OpenCode URL) ✓
- Session-lost surfaced, no silent retry → Task 5 (`SessionLost`, `error` event) ✓
- All traffic targets `workspace-assistant` → Task 4 (`send_message` body) ✓
- Agent-selection + event shapes pinned for 1.15.0 → Task 1 spike ✓

**Placeholder scan:** The OpenCode event field names in Tasks 2/3/4 are the *assumed* 1.15.0 shapes; the spike (Task 1) confirms them and Tasks 2–4 must be aligned to `D-opencode-http.md` before implementation. This is an explicit, gated dependency (the spike runs first), not a skipped detail — every code block is complete and runnable against the fake server, which encodes the same shapes.

**Type consistency:** `OpenCodeClient` (`healthy`/`create_session`/`send_message`/`iter_events`/`aclose`), `NotesProxy` (`ensure_session`/`send`/`relay`/`aclose`), `to_browser_events`, and `create_app(proxy)` signatures match across tasks and tests. The browser event model (`message_delta`/`tool_call`/`done`/`error`) is identical in `events.py`, the proxy, the app test, and the documented N4 contract.

**Out of scope (later plans):** the browser chat UI, notes buttons, upload, and changelog rendering (N4, plan 4); frontend-owned `notes/` git versioning (N5, plan 5); the launcher that starts serve+app together (N6); end-to-end profile smokes (N7). This plan exposes the API those build on and is verified with a fake server + one live smoke.
```
