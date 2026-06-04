"""Async OpenCode HTTP client. The sole talker to `opencode serve`.

Confirmed OpenCode 1.15.0 API surface (docs/decisions/D-opencode-http.md):
- POST /session {"agent": "<name>"} → {"id": "ses_..."}
- POST /session/{sid}/message {"agent": "<name>", "parts": [{"type":"text","text":"..."}]}
- GET /event → SSE stream (global, all sessions); events include properties.sessionID
- GET /session/{sid}/message → [{info: {role, ...}, parts: [Part, ...]}, ...]
- Basic auth: username="opencode", password=OPENCODE_SERVER_PASSWORD (optional)
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

# Defense-in-depth: refuse transcripts longer than this (prevents OOM from
# a hostile or buggy local OpenCode). 10k messages ≈ ~hours of conversation.
MAX_MESSAGES = 10000


class OpenCodeClient:

    def __init__(self, http: httpx.AsyncClient, *, agent: str) -> None:
        self._http = http
        self._agent = agent

    @classmethod
    def connect(cls, base_url: str, *, agent: str) -> OpenCodeClient:
        """Create a client connected to a running opencode serve.

        Reads OPENCODE_SERVER_PASSWORD from the environment to configure
        HTTP Basic auth (username hardcoded as "opencode" per the spec).
        """
        auth = None
        pw = os.environ.get("OPENCODE_SERVER_PASSWORD")
        if pw:
            username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
            auth = httpx.BasicAuth(username, pw)
        http = httpx.AsyncClient(
            base_url=base_url,
            auth=auth,
            timeout=httpx.Timeout(None, connect=30.0),
        )
        return cls(http, agent=agent)

    async def healthy(self) -> bool:
        """Return True if the server responds with a healthy status."""
        try:
            r = await self._http.get("/global/health")
            if r.status_code != 200:
                return False
            data = r.json()
            if not isinstance(data, dict):
                return False
            return bool(data.get("healthy", True))
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, AttributeError):
            return False

    async def create_session(self) -> str:
        """Create a new session bound to self._agent. Returns the session ID."""
        r = await self._http.post("/session", json={"agent": self._agent})
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("OpenCode session response was not an object (missing 'id')")
        sid = data.get("id")
        if not sid:
            raise RuntimeError("OpenCode session response missing 'id'")
        return sid

    async def send_message(self, session_id: str, text: str) -> None:
        """Send a user message to the session. Blocks until the turn completes."""
        r = await self._http.post(
            f"/session/{session_id}/message",
            json={
                "agent": self._agent,  # harmless to repeat; session binding is authoritative
                "parts": [{"type": "text", "text": text}],
            },
        )
        r.raise_for_status()

    async def iter_events(self) -> AsyncIterator[dict]:
        """Async-generate parsed JSON dicts from the global /event SSE stream.

        The stream is global (all sessions). Callers must filter by
        properties.sessionID if they only want events for one session.
        """
        async with self._http.stream("GET", "/event") as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    if payload:
                        try:
                            parsed = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict):
                            yield parsed

    async def tool_calls(self, session_id: str) -> list[dict]:
        """Fetch completed tool calls for a session.

        Calls GET /session/{sid}/message and returns a list of
        {"name": <tool_name>, "status": <state.status>} dicts
        extracted from ALL assistant messages' tool parts, in order.

        A model turn can produce multiple assistant messages (e.g. a
        reasoning/tool-call turn followed by a final text-only answer turn).
        Scanning only the last message misses tool parts in earlier messages.

        Returns [] if there are no messages or no tool parts.
        """
        r = await self._http.get(f"/session/{session_id}/message")
        r.raise_for_status()
        messages = r.json()
        if not isinstance(messages, list):
            return []
        # Collect tool parts across ALL assistant messages, in order
        result = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            if m.get("info", {}).get("role") != "assistant":
                continue
            for part in m.get("parts", []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool":
                    state = part.get("state") or {}
                    result.append(
                        {
                            "name": part.get("tool", "unknown"),
                            "status": state.get("status", "unknown"),
                            "input": state.get("input", {}),
                        }
                    )
        return result

    async def final_text(self, session_id: str) -> str:
        """Return the concatenated text of the LAST assistant message in the session.

        Used to derive a meaningful commit subject from the agent's end-of-turn
        changelog. Returns "" if there are no assistant messages or no text parts.
        """
        r = await self._http.get(f"/session/{session_id}/message")
        r.raise_for_status()
        messages = r.json()
        if not isinstance(messages, list):
            return ""
        for m in reversed(messages):
            if not isinstance(m, dict) or m.get("info", {}).get("role") != "assistant":
                continue
            texts = [
                part.get("text", "")
                for part in m.get("parts", [])
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            if texts:
                return "".join(texts)
        return ""

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def messages(self, session_id: str) -> list[dict]:
        """Return the ordered transcript as ``[{"id", "role", "text"}]``.

        Concatenates the ``text`` parts of each message (ignoring reasoning/tool
        parts). Used by the Sweep to read the braindump. Returns [] on no messages.
        Raises ``ValueError`` if the server returns more than ``MAX_MESSAGES``
        entries (defense-in-depth against OOM).
        """
        r = await self._http.get(f"/session/{session_id}/message")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        if len(data) > MAX_MESSAGES:
            raise ValueError(
                f"too many messages ({len(data)} > {MAX_MESSAGES})"
            )
        out: list[dict] = []
        for m in data:
            if not isinstance(m, dict):
                continue
            info = m.get("info", {})
            text = "".join(
                part.get("text", "")
                for part in m.get("parts", [])
                if isinstance(part, dict) and part.get("type") == "text"
            )
            out.append({"id": info.get("id", ""), "role": info.get("role", ""), "text": text})
        return out
