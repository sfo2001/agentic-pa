"""Tests for the in-process fake OpenCode server."""
import json

import httpx

from tests.frontend.fake_opencode import make_fake_opencode


async def test_health():
    """GET /global/health returns healthy."""
    app = make_fake_opencode(script=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://oc"
    ) as c:
        r = await c.get("/global/health")
        assert r.status_code == 200
        assert r.json()["healthy"] is True


async def test_create_session_records_agent():
    """POST /session records agent from body, returns ses_fake."""
    app = make_fake_opencode(script=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://oc"
    ) as c:
        r = await c.post("/session", json={"agent": "workspace-assistant"})
        assert r.status_code == 200
        assert r.json()["id"] == "ses_fake"
    assert app.state.fake["sessions"][0]["agent"] == "workspace-assistant"


async def test_send_message_recorded():
    """POST /session/{sid}/message records the call."""
    app = make_fake_opencode(script=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://oc"
    ) as c:
        await c.post(
            "/session/ses_fake/message",
            json={"agent": "workspace-assistant", "parts": [{"type": "text", "text": "hello"}]},
        )
    msg = app.state.fake["messages"][0]
    assert msg["sid"] == "ses_fake"
    assert msg["body"]["parts"][0]["text"] == "hello"


async def test_event_stream_contains_script_events():
    """GET /event streams script as SSE data: lines."""
    script = [
        {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses_fake", "field": "text", "delta": "hi"},
        },
        {"type": "session.idle", "properties": {"sessionID": "ses_fake"}},
    ]
    app = make_fake_opencode(script=script)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://oc"
    ) as c:
        lines = []
        async with c.stream("GET", "/event") as resp:
            assert "text/event-stream" in resp.headers["content-type"]
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    lines.append(data)
                    if data.get("type") == "session.idle":
                        break
    assert lines[0]["type"] == "message.part.delta"
    assert lines[0]["properties"]["delta"] == "hi"
    assert lines[-1]["type"] == "session.idle"


async def test_get_session_message_returns_tool_parts():
    """GET /session/{sid}/message returns configured tool parts in the last assistant message."""
    tool_parts = [
        {
            "id": "prt_test",
            "type": "tool",
            "tool": "notes_today",
            "state": {"status": "completed"},
        }
    ]
    app = make_fake_opencode(script=[], tool_parts=tool_parts)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://oc"
    ) as c:
        r = await c.get("/session/ses_fake/message")
        assert r.status_code == 200
        msgs = r.json()
        # Must be a list of {info, parts} objects
        assert isinstance(msgs, list)
        assert len(msgs) >= 1
        last = msgs[-1]
        assert "info" in last and "parts" in last
        assert last["info"]["role"] == "assistant"
        tool = next(p for p in last["parts"] if p.get("type") == "tool")
        assert tool["tool"] == "notes_today"
        assert tool["state"]["status"] == "completed"


async def test_get_session_message_empty_when_no_tool_parts():
    """GET /session/{sid}/message returns empty list when no tool_parts configured."""
    app = make_fake_opencode(script=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://oc"
    ) as c:
        r = await c.get("/session/ses_fake/message")
        assert r.json() == []
