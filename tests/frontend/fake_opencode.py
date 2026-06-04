"""Minimal in-process fake of the OpenCode 1.15.0 HTTP API for deterministic tests.

Confirmed shapes (docs/decisions/D-opencode-http.md):
- POST /session → {"id": "ses_fake"}
- POST /session/{sid}/message → {"ok": true}  (blocking, synchronous)
- GET /event → SSE stream, each event is: data: <json>\n\n
- GET /session/{sid}/message → list of {info: {role, id, ...}, parts: [Part, ...]}

make_fake_opencode(script, *, tool_parts=(), early_tool_parts=()) — factory function.
  script: list of event dicts to stream from GET /event (each must already include
          properties.sessionID so the proxy's session filter can be tested).
  tool_parts: sequence of ToolPart-shaped dicts to return from
              GET /session/{sid}/message in the last assistant message.
              If empty (and early_tool_parts also empty), the endpoint returns [].
  early_tool_parts: sequence of ToolPart-shaped dicts to place in an EARLIER
              assistant message (before a final text-only message). Use this to
              test that tool_calls() correctly scans all messages, not just the last.
              When set, GET /session/{sid}/message returns two assistant messages:
              the first containing early_tool_parts, the second a text-only message.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


def make_fake_opencode(
    script: list[dict],
    *,
    tool_parts: Sequence[dict] = (),
    early_tool_parts: Sequence[dict] = (),
    final_text: str | None = None,
) -> FastAPI:
    """Create an in-process fake OpenCode ASGI app.

    Args:
        script: SSE events to emit from GET /event (in order).
        tool_parts: ToolPart dicts to include in the last (only) assistant message
                    returned by GET /session/{sid}/message.
        early_tool_parts: ToolPart dicts to place in an EARLIER assistant message
                    (before a final text-only message). When set, two assistant
                    messages are returned: the first with early_tool_parts, the
                    second with a text-only part (simulating a multi-turn response
                    where the tool call precedes the final answer).

    Returns:
        A FastAPI app whose ``app.state.fake`` holds recorded calls:
        - ``sessions``: list of {"agent": ...} dicts from POST /session
        - ``messages``: list of {"sid": ..., "body": ...} dicts from POST /session/{sid}/message
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
        """Return a list of {info, parts} message objects.

        Shape confirmed from GET /doc OpenAPI spec:
          [{"info": {role, id, sessionID, ...}, "parts": [Part, ...]}, ...]

        If app.state.transcript is set, returns that (used by Sweep tests
        to inject a pre-canned transcript). Otherwise the original rules:
        - early_tool_parts: two assistant messages
        - tool_parts only: one assistant message with the tool parts
        - final_text only: one assistant message with text
        - else: []
        """
        transcript = getattr(app.state, "transcript", None)
        if transcript is not None:
            return transcript
        if early_tool_parts:
            return [
                {
                    "info": {
                        "id": "msg_early",
                        "sessionID": sid,
                        "role": "assistant",
                        "time": {"created": 0, "completed": 1},
                    },
                    "parts": list(early_tool_parts),
                },
                {
                    "info": {
                        "id": "msg_final",
                        "sessionID": sid,
                        "role": "assistant",
                        "time": {"created": 1, "completed": 2},
                    },
                    "parts": [{"type": "text", "text": final_text or "Here is your agenda."}],
                },
            ]
        if not tool_parts:
            if final_text is not None:
                # One assistant message carrying just the final text (for testing
                # final_text()/changelog extraction without tool parts).
                return [
                    {
                        "info": {"id": "msg_text", "sessionID": sid, "role": "assistant",
                                 "time": {"created": 0, "completed": 1}},
                        "parts": [{"type": "text", "text": final_text}],
                    }
                ]
            return []
        return [
            {
                "info": {
                    "id": "msg_fake",
                    "sessionID": sid,
                    "role": "assistant",
                    "time": {"created": 0, "completed": 0},
                },
                "parts": list(tool_parts),
            }
        ]

    app.state.fake = state
    return app
