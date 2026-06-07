"""Tests for the session/relay proxy."""
import asyncio

import httpx
import pytest

from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy, SessionLost
from tests.frontend.fake_opencode import make_fake_opencode


def _proxy_for(app) -> NotesProxy:
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://oc"),
        agent="workspace-assistant",
    )
    return NotesProxy(oc)


async def test_ensure_session_creates_once_and_reuses():
    """ensure_session() creates a session on first call, returns same ID on second."""
    proxy = _proxy_for(make_fake_opencode(script=[]))
    s1 = await proxy.ensure_session()
    s2 = await proxy.ensure_session()
    assert s1 == s2 == "ses_fake"
    await proxy.aclose()


async def test_relay_maps_text_delta_to_message_delta():
    """relay() emits message_delta events from message.part.delta SSE events."""
    script = [
        {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_fake", "field": "text", "delta": "hello"},
        },
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    proxy = _proxy_for(make_fake_opencode(script=script))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    assert {"type": "message_delta", "text": "hello"} in out
    assert out[-1] == {"type": "done"}
    await proxy.aclose()


async def test_relay_splits_reasoning_from_answer():
    """relay() routes a reasoning part's text deltas to reasoning_delta and the
    answer part's deltas to message_delta, using partID->type from part.updated."""
    script = [
        {"type": "message.part.updated",
         "properties": {"sessionID": "ses_fake", "part": {"id": "prt_r", "type": "reasoning"}}},
        {"type": "message.part.delta",
         "properties": {"sessionID": "ses_fake", "partID": "prt_r", "field": "text", "delta": "let me think"}},
        {"type": "message.part.updated",
         "properties": {"sessionID": "ses_fake", "part": {"id": "prt_t", "type": "text"}}},
        {"type": "message.part.delta",
         "properties": {"sessionID": "ses_fake", "partID": "prt_t", "field": "text", "delta": "the answer"}},
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    proxy = _proxy_for(make_fake_opencode(script=script))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    assert {"type": "reasoning_delta", "text": "let me think"} in out
    assert {"type": "message_delta", "text": "the answer"} in out
    assert out[-1] == {"type": "done"}
    await proxy.aclose()


async def test_relay_emits_present_event_for_present_tool():
    script = [{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}]
    tool_parts = [{
        "id": "prt_p", "type": "tool", "tool": "present_present",
        "state": {"status": "completed", "input": {"path": "topics/atlas.md"}},
    }]
    proxy = _proxy_for(make_fake_opencode(script=script, tool_parts=tool_parts))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    assert {"type": "present", "path": "topics/atlas.md"} in out
    assert out[-1] == {"type": "done"}
    await proxy.aclose()


async def test_relay_emits_tool_calls_after_idle():
    """relay() fetches tool_calls after session.idle and yields tool_call events."""
    tool_parts = [
        {
            "id": "prt_1",
            "type": "tool",
            "tool": "notes_today",
            "state": {"status": "completed"},
        }
    ]
    script = [
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    proxy = _proxy_for(make_fake_opencode(script=script, tool_parts=tool_parts))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    tool_evts = [e for e in out if e["type"] == "tool_call"]
    assert len(tool_evts) == 1
    assert tool_evts[0] == {"type": "tool_call", "name": "notes_today", "status": "completed"}
    assert out[-1] == {"type": "done"}
    await proxy.aclose()


async def test_relay_ignores_events_for_other_sessions():
    """relay() ignores events whose properties.sessionID doesn't match our session."""
    script = [
        # Event for a different session — must be ignored
        {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_OTHER", "field": "text", "delta": "interloper"},
        },
        # Our session text delta
        {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_fake", "field": "text", "delta": "ours"},
        },
        # Idle for another session — must be ignored
        {"type": "session.idle", "properties": {"sessionID": "ses_OTHER"}},
        # Our session idle — ends relay
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
    assert "interloper" not in texts
    assert "ours" in texts
    assert out[-1] == {"type": "done"}
    await proxy.aclose()


async def test_send_raises_session_lost_on_http_error():
    """send() raises SessionLost when the HTTP call fails."""
    # Create a fake that makes /session/{sid}/message fail by using an unreachable transport
    import httpx

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    oc = OpenCodeClient(
        httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc"),
        agent="workspace-assistant",
    )
    proxy = NotesProxy(oc)
    proxy._session_id = "ses_fake"  # bypass ensure_session
    with pytest.raises(SessionLost):
        await proxy.send("hello")
    await proxy.aclose()


async def test_relay_yields_error_on_http_error():
    """relay() yields an error event when iter_events raises an HTTP error."""

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    oc = OpenCodeClient(
        httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc"),
        agent="workspace-assistant",
    )
    proxy = NotesProxy(oc)
    proxy._session_id = "ses_fake"
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        break
    assert out[0]["type"] == "error"
    # BH-08: broad exception handler now uses kind="upstream" for all relay failures
    assert out[0]["kind"] == "upstream"
    await proxy.aclose()


# ── BH-01: ensure_session must not race under concurrent calls ──────────────

async def test_bh01_ensure_session_no_concurrent_double_create():
    """BH-01: Two concurrent ensure_session() calls must call create_session exactly once."""

    gate = asyncio.Event()
    call_count = 0

    class _GatedClient:
        """Spy client whose create_session gates on an asyncio.Event."""

        async def create_session(self):
            nonlocal call_count
            call_count += 1
            await gate.wait()  # pause so the second caller enters while first is waiting
            return "ses_fake"

        async def aclose(self):
            pass

    proxy = NotesProxy(_GatedClient())

    async def _release_after_both_enter():
        # Give both coroutines a chance to hit the await inside create_session
        await asyncio.sleep(0.05)
        gate.set()

    ids = await asyncio.gather(
        proxy.ensure_session(),
        proxy.ensure_session(),
        _release_after_both_enter(),
    )
    # First two results are the session IDs from the two ensure_session calls
    assert ids[0] == "ses_fake"
    assert ids[1] == "ses_fake"
    assert call_count == 1, f"Expected 1 create_session call, got {call_count}"
    await proxy.aclose()


# ── BH-02: relay() must clear _session_id after an HTTP error ───────────────

async def test_bh02_relay_clears_session_id_after_http_error():
    """BH-02: After relay() yields an error event, _session_id must be None."""

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    oc = OpenCodeClient(
        httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc"),
        agent="workspace-assistant",
    )
    proxy = NotesProxy(oc)
    proxy._session_id = "ses_fake"

    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] == "error":
            break

    assert out[0]["type"] == "error"
    assert proxy._session_id is None, (
        f"Expected _session_id=None after error, got {proxy._session_id!r}"
    )
    await proxy.aclose()


# ── BH-07: relay() must be single-flight ────────────────────────────────────

async def test_bh07_second_concurrent_relay_yields_busy_and_returns():
    """BH-07: A second concurrent relay() call yields a busy error and returns promptly."""

    # A fake that holds open the event stream until released
    hold = asyncio.Event()
    app = _make_hold_open_fake(hold)

    proxy = _proxy_for(app)
    await proxy.ensure_session()

    # Start the first relay but don't await it fully — just get the async generator
    first_gen = proxy.relay()
    # Advance first relay past any initial setup (get first event)
    # It will then block waiting for more events (the stream is held)
    # We use a task to drive the first relay in background
    first_task = asyncio.create_task(_drain_until_hold(first_gen))

    # Give first relay a moment to enter and block
    await asyncio.sleep(0.05)

    # Now attempt a second concurrent relay — it must yield busy immediately
    second_events = []
    try:
        async def _collect_second():
            async for evt in proxy.relay():
                second_events.append(evt)
                break

        await asyncio.wait_for(_collect_second(), timeout=1.0)
    finally:
        hold.set()  # release first relay
        first_task.cancel()
        try:
            await first_task
        except asyncio.CancelledError:
            pass

    assert len(second_events) == 1, f"Expected 1 event from second relay, got {second_events}"
    assert second_events[0]["type"] == "error"
    assert second_events[0]["kind"] == "busy"
    await proxy.aclose()


def _make_hold_open_fake(hold: asyncio.Event):
    """Create a fake opencode that blocks the event stream until `hold` is set."""
    import json

    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    fake = FastAPI()

    @fake.get("/global/health")
    async def health():
        return {"healthy": True, "version": "fake"}

    @fake.post("/session")
    async def create_session():
        return {"id": "ses_fake"}

    @fake.post("/session/{sid}/message")
    async def send_message(sid: str):
        return {"ok": True}

    @fake.get("/event")
    async def event_stream():
        async def gen():
            # Block until hold is set, then emit idle
            await hold.wait()
            yield f"data: {json.dumps({'type': 'session.idle', 'properties': {'sessionID': 'ses_fake'}})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @fake.get("/session/{sid}/message")
    async def get_messages(sid: str):
        return []

    return fake


async def _drain_until_hold(gen):
    """Drive an async generator until exhausted (used to run relay in background)."""
    async for _ in gen:
        pass


# ── BH-08: relay() must catch non-HTTPError exceptions ──────────────────────

async def test_bh08_relay_yields_error_on_unexpected_exception():
    """BH-08: relay() yields a clean error event when a RuntimeError escapes the pipeline."""

    class _BoomClient:
        """Client whose iter_events raises a RuntimeError mid-stream."""

        async def create_session(self):
            return "ses_fake"

        async def iter_events(self):
            raise RuntimeError("unexpected internal failure")
            yield  # make this an async generator

        async def tool_calls(self, sid):
            return []

        async def aclose(self):
            pass

    proxy = NotesProxy(_BoomClient())
    proxy._session_id = "ses_fake"

    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] == "error":
            break

    assert len(out) >= 1
    assert out[-1]["type"] == "error", f"Expected error event, got {out}"
    # Must NOT contain raw exception text
    assert "unexpected internal failure" not in out[-1].get("message", "")
    await proxy.aclose()


# ── BH-21: Pattern P — relay() unhandled exception before inner try ──────────


async def test_bh21_relay_ensure_session_failure_yields_error_event():
    """BH-21: When relay()'s initial ``ensure_session()`` call at line 103 fails,
    the exception is NOT caught by the inner ``except Exception`` at line 133
    (it's before the inner try). The outer finally resets _relaying, but the
    exception propagates to the caller without yielding an error event.

    Expected: relay() should yield an error event and handle gracefully.
    Currently: the raw exception propagates, causing an incomplete SSE stream."""
    import httpx

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    oc = OpenCodeClient(
        httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc"),
        agent="workspace-assistant",
    )
    proxy = NotesProxy(oc)
    # Don't set _session_id, so relay() calls ensure_session() which fails

    out = []
    try:
        async for evt in proxy.relay():
            out.append(evt)
            break
    except Exception as exc:
        # BUG: exception propagates unhandled instead of becoming an error event
        pytest.fail(f"relay() raised instead of yielding error event: {exc}")

    # Should yield an error event, not raise
    assert len(out) >= 1, "relay() yielded no events before failing"
    assert out[0]["type"] == "error", (
        f"Expected error event, got {out[0]}"
    )
    await proxy.aclose()


# ── BH-15: send() must raise SessionLost when ensure_session fails ───────────

async def test_bh15_send_raises_session_lost_when_create_session_fails():
    """BH-15: send() raises SessionLost when create_session raises (not raw error)."""

    class _FailCreateClient:
        """Client whose create_session always raises RuntimeError."""

        async def create_session(self):
            raise RuntimeError("malformed response: missing 'id'")

        async def aclose(self):
            pass

    proxy = NotesProxy(_FailCreateClient())
    # _session_id is None so send() will call ensure_session -> create_session -> raises

    with pytest.raises(SessionLost):
        await proxy.send("hello")

    await proxy.aclose()


# ── Group K: transcript before session / propose_ingest error handling ───────


async def test_transcript_before_session_returns_empty_list():
    """K-1: transcript() before any ensure_session() returns [] (not raises).

    The Sweep endpoint calls proxy.transcript() right after ensure_session(),
    so the case of "transcript without a session" is real: e.g. an old state
    file with a session_id that the upstream has since discarded. The proxy
    must hand back an empty list so the Sweep returns "nothing new" cleanly.
    """
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode(script=[])), base_url="http://oc"),
        agent="workspace-assistant",
    )
    proxy = NotesProxy(oc)
    msgs = await proxy.transcript()
    assert msgs == []
    await proxy.aclose()



