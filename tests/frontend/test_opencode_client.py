"""Tests for the async OpenCode HTTP client."""
import httpx
import pytest

from frontend.opencode_client import OpenCodeClient
from tests.frontend.fake_opencode import make_fake_opencode


def _mock_client(handler) -> OpenCodeClient:
    """Build an OpenCodeClient backed by a synchronous MockTransport handler."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://oc")
    return OpenCodeClient(http, agent="test-agent")


def _client_for(app) -> OpenCodeClient:
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://oc")
    return OpenCodeClient(http, agent="workspace-assistant")


async def test_healthy_returns_true():
    """healthy() returns True when server responds with healthy."""
    app = make_fake_opencode(script=[])
    oc = _client_for(app)
    assert await oc.healthy() is True
    await oc.aclose()


async def test_create_session_sends_agent():
    """create_session() posts the agent and returns the session ID."""
    app = make_fake_opencode(script=[])
    oc = _client_for(app)
    sid = await oc.create_session()
    assert sid == "ses_fake"
    assert app.state.fake["sessions"][0]["agent"] == "workspace-assistant"
    await oc.aclose()


async def test_send_message_includes_parts():
    """send_message() POSTs parts array with text and includes the agent."""
    app = make_fake_opencode(script=[])
    oc = _client_for(app)
    await oc.send_message("ses_fake", "hello world")
    msg = app.state.fake["messages"][0]
    assert msg["sid"] == "ses_fake"
    body = msg["body"]
    assert body["parts"][0]["type"] == "text"
    assert body["parts"][0]["text"] == "hello world"
    await oc.aclose()


async def test_iter_events_parses_sse_json():
    """iter_events() yields parsed JSON dicts from /event SSE stream."""
    script = [
        {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_fake", "field": "text", "delta": "yo"},
        },
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    app = make_fake_opencode(script=script)
    oc = _client_for(app)
    got = []
    async for evt in oc.iter_events():
        got.append(evt)
        if evt.get("type") == "session.idle":
            break
    assert got[0]["type"] == "message.part.delta"
    assert got[0]["properties"]["delta"] == "yo"
    assert got[-1]["type"] == "session.idle"
    await oc.aclose()


async def test_tool_calls_returns_tool_parts():
    """tool_calls() returns [{name, status}] from the last assistant message."""
    tool_parts = [
        {
            "id": "prt_1",
            "type": "tool",
            "tool": "notes_today",
            "state": {"status": "completed"},
        },
        {
            "id": "prt_2",
            "type": "tool",
            "tool": "list_notes",
            "state": {"status": "completed"},
        },
    ]
    app = make_fake_opencode(script=[], tool_parts=tool_parts)
    oc = _client_for(app)
    calls = await oc.tool_calls("ses_fake")
    assert calls == [
        {"name": "notes_today", "status": "completed", "input": {}},
        {"name": "list_notes", "status": "completed", "input": {}},
    ]
    await oc.aclose()


async def test_tool_calls_empty_when_no_tool_parts():
    """tool_calls() returns [] when no messages or no tool parts."""
    app = make_fake_opencode(script=[])
    oc = _client_for(app)
    calls = await oc.tool_calls("ses_fake")
    assert calls == []
    await oc.aclose()


async def test_connect_uses_basic_auth_when_password_set(monkeypatch):
    """connect() wires httpx.BasicAuth when OPENCODE_SERVER_PASSWORD is set."""
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "s3cret")
    oc = OpenCodeClient.connect("http://oc", agent="workspace-assistant")
    assert isinstance(oc._http.auth, httpx.BasicAuth)
    await oc.aclose()


async def test_healthy_returns_false_on_error():
    """healthy() returns False when the HTTP call raises ConnectError."""

    class _FailTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("connection refused")

    http = httpx.AsyncClient(transport=_FailTransport(), base_url="http://oc")
    oc = OpenCodeClient(http, agent="workspace-assistant")
    assert await oc.healthy() is False
    await oc.aclose()


async def test_tool_calls_finds_part_in_earlier_message():
    """tool_calls() finds a tool part in an earlier message (not the last).

    Reproduces the live smoke bug: the model produced two assistant messages —
    a reasoning/tool-call turn (notes_today completed) followed by a text-only
    final answer turn. The old code only scanned assistant_messages[-1] (the
    text-only message) and returned []. The fix scans all assistant messages.
    """
    early_tool_parts = [
        {
            "id": "prt_early",
            "type": "tool",
            "tool": "notes_today",
            "state": {"status": "completed"},
        }
    ]
    # Fake returns two assistant messages: early_tool_parts in msg[0],
    # a text-only part in msg[1] (the "last" message).
    app = make_fake_opencode(script=[], early_tool_parts=early_tool_parts)
    oc = _client_for(app)
    calls = await oc.tool_calls("ses_fake")
    assert calls == [{"name": "notes_today", "status": "completed", "input": {}}]
    await oc.aclose()


# ── BH-04 & BH-05: iter_events() robustness ─────────────────────────────────


async def test_bh04_iter_events_skips_non_json_data_line():
    """BH-04: iter_events() must not raise on non-JSON data: lines like [DONE].

    A valid event precedes [DONE], another valid event follows; the consumer
    should yield both valid dicts and never raise JSONDecodeError.
    """
    sse_body = (
        b'data: {"type":"message.part.delta","properties":{"sessionID":"s1"}}\n\n'
        b"data: [DONE]\n\n"
        b'data: {"type":"session.idle","properties":{"sessionID":"s1"}}\n\n'
    )

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_body,
        )

    oc = _mock_client(handler)
    got = []
    async for evt in oc.iter_events():
        got.append(evt)
    await oc.aclose()

    types = [e["type"] for e in got]
    assert "message.part.delta" in types
    assert "session.idle" in types
    # [DONE] must NOT appear as a yielded item
    assert all(isinstance(e, dict) for e in got)


async def test_bh05_iter_events_skips_non_dict_json():
    """BH-05: iter_events() must skip non-dict JSON payloads (42, [1,2]).

    Only dict events should be yielded; scalars and arrays must be dropped
    so callers using .get("type") never hit AttributeError.
    """
    sse_body = (
        b'data: {"type":"ok"}\n\n'
        b"data: 42\n\n"
        b"data: [1,2]\n\n"
        b'data: {"type":"done"}\n\n'
    )

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_body,
        )

    oc = _mock_client(handler)
    got = []
    async for evt in oc.iter_events():
        got.append(evt)
    await oc.aclose()

    assert all(isinstance(e, dict) for e in got), f"Non-dict item yielded: {got}"
    assert len(got) == 2
    assert got[0]["type"] == "ok"
    assert got[1]["type"] == "done"


# ── BH-11: healthy() exception catch too narrow ──────────────────────────────


async def test_bh11_healthy_returns_false_on_non_json_200():
    """BH-11: healthy() must return False when 200 body is not valid JSON."""

    def handler(request):
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

    oc = _mock_client(handler)
    result = await oc.healthy()
    await oc.aclose()
    assert result is False


async def test_bh11_healthy_returns_false_on_list_200():
    """BH-11: healthy() must return False when 200 body is a JSON list (no .get)."""

    def handler(request):
        return httpx.Response(200, json=[])

    oc = _mock_client(handler)
    result = await oc.healthy()
    await oc.aclose()
    assert result is False


# ── BH-12: create_session() bare KeyError ───────────────────────────────────


async def test_bh12_create_session_raises_runtime_error_on_missing_id():
    """BH-12: create_session() must raise RuntimeError (not KeyError) when the
    2xx response body lacks an 'id' field."""

    def handler(request):
        return httpx.Response(200, json={})

    oc = _mock_client(handler)
    with pytest.raises(RuntimeError, match="missing 'id'"):
        await oc.create_session()
    await oc.aclose()


# ── BH-13: tool_calls() shape fragility ─────────────────────────────────────


async def test_bh13_tool_calls_returns_empty_on_non_list_body():
    """BH-13a: tool_calls() must return [] when the response body is not a list."""

    def handler(request):
        # A non-empty dict (realistic error body) rather than [] to trigger failure
        return httpx.Response(200, json={"error": "unexpected"})

    oc = _mock_client(handler)
    calls = await oc.tool_calls("ses_test")
    await oc.aclose()
    assert calls == []


# ── BH-16: create_session() must guard against non-dict JSON response ─────────


async def test_bh16_create_session_raises_runtime_error_on_list_body():
    """BH-16: create_session() must raise RuntimeError (not AttributeError) when
    the 2xx response body is a JSON list (valid JSON, not a dict)."""

    def handler(request):
        return httpx.Response(200, json=[])  # list, not dict

    oc = _mock_client(handler)
    with pytest.raises(RuntimeError, match="missing 'id'"):
        await oc.create_session()
    await oc.aclose()


# ── BH-17: iter_events() must parse SSE data: without trailing space ─────────


async def test_bh17_iter_events_parses_data_without_space():
    """BH-17: iter_events() must parse SSE lines like 'data:{"type":...}' where
    there is no space after 'data:' (valid SSE per spec).

    The code checks line.startswith('data: ') which requires a trailing space.
    Lines starting with 'data:{"' are skipped, silently dropping events.
    """
    sse_body = (
        b'data:{"type":"message.part.delta","properties":{"sessionID":"s1","field":"text","delta":"hi"}}\n\n'
        b'data:{"type":"session.idle","properties":{"sessionID":"s1"}}\n\n'
    )

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_body,
        )

    oc = _mock_client(handler)
    got = []
    async for evt in oc.iter_events():
        got.append(evt)
    await oc.aclose()

    types = [e["type"] for e in got]
    assert "message.part.delta" in types, (
        f"Expected message.part.delta in types, got {types}"
    )
    assert "session.idle" in types, (
        f"Expected session.idle in types, got {types}"
    )


async def test_tool_calls_includes_input():
    import httpx

    from frontend.opencode_client import OpenCodeClient
    from tests.frontend.fake_opencode import make_fake_opencode
    tool_parts = [{
        "id": "prt_p", "type": "tool", "tool": "present",
        "state": {"status": "completed", "input": {"path": "meetings/x.md"}},
    }]
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([], tool_parts=tool_parts)),
                          base_url="http://oc"),
        agent="workspace-assistant",
    )
    sid = await oc.create_session()
    calls = await oc.tool_calls(sid)
    assert calls == [{"name": "present", "status": "completed", "input": {"path": "meetings/x.md"}}]
    await oc.aclose()


async def test_bh13_tool_calls_handles_null_state():
    """BH-13b: tool_calls() must not raise when a tool part has state: null.

    part.get('state', {}) returns None (the explicit null) not {} (the default),
    so .get('status') on None raises AttributeError. The fix uses `or {}`.
    """
    messages = [
        {
            "info": {"id": "msg1", "sessionID": "ses_test", "role": "assistant"},
            "parts": [{"type": "tool", "tool": "my_tool", "state": None}],
        }
    ]

    def handler(request):
        return httpx.Response(200, json=messages)

    oc = _mock_client(handler)
    calls = await oc.tool_calls("ses_test")
    await oc.aclose()
    # Must not raise; status falls back gracefully
    assert len(calls) == 1
    assert calls[0]["name"] == "my_tool"
    assert isinstance(calls[0]["status"], str)
