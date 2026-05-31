"""Pure mapping from OpenCode SSE events to the browser event model.

Confirmed OpenCode 1.15.0 event shapes (from docs/decisions/D-opencode-http.md):

- Text delta: type="message.part.delta", properties.field="text", properties.delta=<chunk>
- Turn done:  type="session.idle", properties.sessionID=<sid>
- Tool calls: NOT in SSE stream — fetched post-idle via GET /session/{sid}/message

The browser event model (consumed by the UI):
- {"type": "message_delta", "text": "<chunk>"}      — final answer text
- {"type": "reasoning_delta", "text": "<chunk>"}    — model thinking (UI shows collapsed)
- {"type": "done"}
- {"type": "tool_call", "name": "<tool>", "status": "<status>"}  (emitted by proxy, not here)
- {"type": "error", "kind": "upstream|busy", "message": "<text>"}  (emitted by proxy as SSE)
- session_lost is NOT an SSE event kind — it surfaces as HTTP 503 from POST /api/message

Note on reasoning: OpenCode streams the model's reasoning as `message.part.delta`
with `field="text"` (same as the answer) but a *different* partID whose part has
`type="reasoning"`. The relay accumulates partID→type from `message.part.updated`
and passes it here so reasoning deltas become `reasoning_delta`, not the answer.
"""
from __future__ import annotations


def to_browser_events(oc_event: dict, part_types: dict | None = None) -> list[dict]:
    """Translate one OpenCode SSE event into zero or more browser events.

    ``part_types`` maps partID → the part's type ("text" | "reasoning" | "tool"),
    accumulated by the relay. A text delta whose part is a *reasoning* part becomes
    a ``reasoning_delta`` (the UI renders it collapsed) rather than the answer. An
    unknown partID defaults to ``message_delta`` — never hide the final answer.

    This function is pure: no I/O, no side-effects, always returns a list.
    """
    etype = oc_event.get("type")

    # Note: in the live relay (proxy.relay) session.idle is handled directly — the
    # relay must fetch + emit tool_call events BEFORE the terminal done, so it does
    # not route idle through this mapper. This branch is the mapper's own contract
    # (idle → done) and keeps the function total + independently testable.
    if etype == "session.idle":
        return [{"type": "done"}]

    if etype == "message.part.delta":
        props = oc_event.get("properties", {})
        if props.get("field") == "text":
            delta = props.get("delta", "")
            if delta:
                ptype = (part_types or {}).get(props.get("partID"))
                kind = "reasoning_delta" if ptype == "reasoning" else "message_delta"
                return [{"type": kind, "text": delta}]

    # Everything else — session.status, session.diff, server.*, message.part.updated
    # — is ignored here (message.part.updated is consumed by the relay for part_types).
    return []
