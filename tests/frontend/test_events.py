"""Tests for the pure OpenCode→browser event mapper."""
from frontend.events import to_browser_events


def test_text_delta_becomes_message_delta():
    """message.part.delta with field=text maps to message_delta using properties.delta."""
    oc = {
        "type": "message.part.delta",
        "properties": {
            "sessionID": "ses_test",
            "messageID": "msg_test",
            "partID": "prt_test",
            "field": "text",
            "delta": "Hello world",
        },
    }
    assert to_browser_events(oc) == [{"type": "message_delta", "text": "Hello world"}]


def test_reasoning_delta_is_ignored():
    """message.part.delta with field=reasoning is not forwarded to browser."""
    oc = {
        "type": "message.part.delta",
        "properties": {
            "sessionID": "ses_test",
            "field": "reasoning",
            "delta": "I am thinking...",
        },
    }
    assert to_browser_events(oc) == []


def test_session_idle_becomes_done():
    """session.idle maps to done event."""
    oc = {
        "type": "session.idle",
        "properties": {"sessionID": "ses_test"},
    }
    assert to_browser_events(oc) == [{"type": "done"}]


def test_unknown_event_is_ignored():
    """Unrecognised event types produce empty list."""
    assert to_browser_events({"type": "server.connected"}) == []
    assert to_browser_events({"type": "server.heartbeat"}) == []
    assert to_browser_events({"type": "session.status"}) == []


def test_empty_delta_is_ignored():
    """Empty text delta is not forwarded."""
    oc = {
        "type": "message.part.delta",
        "properties": {"field": "text", "delta": ""},
    }
    assert to_browser_events(oc) == []


def test_tool_calls_not_in_sse():
    """There is no SSE event type for tool calls — confirmed by spike."""
    # The old plan assumed message.part.updated with part.type=tool.
    # In reality, tool events do NOT appear in SSE. This test documents that
    # a hypothetical such event would be ignored (returns []).
    oc = {
        "type": "message.part.updated",
        "properties": {"part": {"type": "tool", "tool": "notes_today"}},
    }
    assert to_browser_events(oc) == []


def _delta(part_id, delta):
    return {
        "type": "message.part.delta",
        "properties": {"sessionID": "s", "partID": part_id, "field": "text", "delta": delta},
    }


def test_reasoning_part_text_delta_becomes_reasoning_delta():
    """A text delta whose part is a reasoning part → reasoning_delta (not the answer)."""
    assert to_browser_events(_delta("prt_r", "let me think"), {"prt_r": "reasoning"}) == [
        {"type": "reasoning_delta", "text": "let me think"}
    ]


def test_text_part_delta_becomes_message_delta():
    assert to_browser_events(_delta("prt_t", "the answer"), {"prt_t": "text"}) == [
        {"type": "message_delta", "text": "the answer"}
    ]


def test_unknown_part_delta_defaults_to_message_delta():
    # No/empty part_types → never hide the answer.
    assert to_browser_events(_delta("prt_x", "x")) == [{"type": "message_delta", "text": "x"}]
    assert to_browser_events(_delta("prt_x", "x"), {}) == [{"type": "message_delta", "text": "x"}]
