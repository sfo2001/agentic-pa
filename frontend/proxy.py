"""Session lifecycle + relay of OpenCode events to the browser event model.

One long-lived session is created on first use and reused for all subsequent
messages. The relay loop reads the global /event SSE stream, filters to our
session, translates text deltas to browser events, and after the session goes
idle fetches completed tool calls and emits them before the final "done" event.

Design constraint: one turn streams at a time. Callers (e.g. the N4 browser
client) must not POST a new message while GET /api/events is active. A second
concurrent relay() call will immediately yield a ``{"type":"error","kind":"busy"}``
event and return — it will NOT open a second upstream stream.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx

from frontend.events import to_browser_events
from frontend.opencode_client import OpenCodeClient


class SessionLost(Exception):
    """Raised when an HTTP error occurs while sending a message."""


class NotesProxy:
    """Proxy between the browser and a single OpenCode session.

    Concurrency contract: exactly one ``relay()`` may be active at a time.
    A second concurrent caller receives an immediate
    ``{"type": "error", "kind": "busy", ...}`` event and the generator returns.
    This is design-enforced via ``_relaying``; the HTTP layer (N4) must not POST
    a new message while ``GET /api/events`` is still streaming.
    """

    def __init__(self, client: OpenCodeClient) -> None:
        self._oc = client
        self._session_id: str | None = None
        # BH-01: serialise concurrent ensure_session() calls so only one
        # create_session() RPC is issued regardless of concurrent awaiters.
        self._session_lock: asyncio.Lock = asyncio.Lock()
        # BH-07: single-flight guard — True while a relay is in progress.
        self._relaying: bool = False

    async def ensure_session(self) -> str:
        """Return the current session ID, creating one if needed.

        Thread-safe via ``_session_lock``: concurrent awaiters will wait for
        the first caller to finish and then reuse the session ID it created
        (double-checked pattern).
        """
        # Fast path — no lock needed when session already exists.
        if self._session_id is not None:
            return self._session_id
        async with self._session_lock:
            # Double-checked: another coroutine may have created the session
            # while we were waiting for the lock.
            if self._session_id is None:
                self._session_id = await self._oc.create_session()
        return self._session_id

    async def send(self, text: str) -> None:
        """Send a user message to the session.

        Raises SessionLost if ensure_session() or the HTTP send fails.
        Wraps both httpx.HTTPError and RuntimeError (e.g. malformed server
        response missing the session 'id') so callers always see SessionLost.
        """
        try:
            sid = await self.ensure_session()
            await self._oc.send_message(sid, text)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise SessionLost("session unavailable") from exc

    async def relay(self) -> AsyncIterator[dict]:
        """Async-generate browser events from the OpenCode event stream.

        Single-flight: if another relay is already active, immediately yields
        ``{"type": "error", "kind": "busy", "message": "a turn is already streaming"}``
        and returns — it does NOT open a second upstream stream.

        Reads the global SSE stream and:
        1. Ignores events for other sessions (properties.sessionID != our session).
        2. Maps text deltas via to_browser_events → message_delta events.
        3. When our session.idle arrives:
           a. Fetches tool_calls(sid) from GET /session/{sid}/message.
           b. Yields one tool_call event per tool part.
           c. Yields {"type": "done"}.
           d. Stops iteration.

        On any exception (httpx.HTTPError or unexpected), yields a clean error
        event, resets the session ID so the next turn can recover, and stops.
        """
        # BH-07: single-flight guard.
        if self._relaying:
            yield {"type": "error", "kind": "busy", "message": "a turn is already streaming"}
            return

        self._relaying = True
        # partID -> part type ("text"|"reasoning"|"tool"), learned from
        # message.part.updated, so reasoning text deltas can be split off (BH/UX).
        part_types: dict[str, str] = {}
        try:
            try:
                sid = self._session_id or await self.ensure_session()
                async for oc_event in self._oc.iter_events():
                    props = oc_event.get("properties", {})
                    event_sid = props.get("sessionID")

                    # Filter: ignore events for other sessions.
                    # Note: events without a sessionID (e.g. server.connected) also pass through
                    # to_browser_events which will return [] for them, so we only filter when
                    # a sessionID is present and doesn't match.
                    if event_sid is not None and event_sid != sid:
                        continue

                    # Learn each part's type so reasoning deltas route to a separate
                    # (collapsible) browser event rather than the answer.
                    if oc_event.get("type") == "message.part.updated":
                        part = props.get("part")
                        if isinstance(part, dict) and part.get("id"):
                            part_types[part["id"]] = part.get("type")

                    # Check for our session.idle — this ends the relay.
                    if oc_event.get("type") == "session.idle":
                        # Fetch tool calls from the finished message.
                        tool_calls = await self._oc.tool_calls(sid)
                        for tc in tool_calls:
                            # OpenCode namespaces MCP tools as <serverkey>_<tool>;
                            # our present tool registers as "present_present".
                            if tc["name"] in ("present_present", "present"):
                                path = (tc.get("input") or {}).get("path")
                                if path:
                                    yield {"type": "present", "path": path}
                                continue
                            yield {
                                "type": "tool_call",
                                "name": tc["name"],
                                "status": tc["status"],
                            }
                        yield {"type": "done"}
                        return

                    # Map other events (text deltas, etc.) via the pure mapper,
                    # passing the part-type map so reasoning is split from the answer.
                    for browser_evt in to_browser_events(oc_event, part_types):
                        yield browser_evt

            except Exception:  # noqa: BLE001 — boundary code; convert all upstream failures to a clean browser event
                # BH-02 + BH-08: reset session so the next turn creates a fresh one,
                # and emit a fixed-text error event (no raw exception text — security boundary).
                self._session_id = None
                yield {"type": "error", "kind": "upstream", "message": "upstream connection failed"}
        finally:
            # BH-07: always release the single-flight guard, even on cancellation.
            self._relaying = False

    async def final_agent_text(self) -> str:
        """Best-effort assistant text from the just-completed turn, for deriving a
        commit subject. Returns "" if no session exists or on any upstream error."""
        if self._session_id is None:
            return ""
        try:
            return await self._oc.final_text(self._session_id)
        except (httpx.HTTPError, RuntimeError):
            return ""

    async def transcript(self) -> list[dict]:
        """Ordered transcript of the current session ([] if none)."""
        if self._session_id is None:
            return []
        return await self._oc.messages(self._session_id)

    async def aclose(self) -> None:
        """Close the underlying OpenCode client."""
        await self._oc.aclose()
