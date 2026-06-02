# D-opencode-http: OpenCode 1.15.0 HTTP Surface (Spike Decision Record)

**Date:** 2026-05-30  
**Status:** Confirmed via live spike against `opencode serve 1.15.0`  
**Spike session:** `notes-mvp/sample-notes` (so `opencode serve` directory-walks up to `notes-mvp/opencode.json`)  
**Port used:** 4178

---

## 1. Session Create

**Method + Path:** `POST /session`

**Minimal request body:**
```json
{"agent": "workspace-assistant"}
```

**Agent binding:** The `agent` field is set **at session creation** (in the POST body). It is NOT a per-message field.  
The session object returned confirms `"agent": "workspace-assistant"`.

**Response shape (relevant fields):**
```json
{
  "id": "ses_1866dab56ffemKJDeCn61ZB1Un",
  "agent": "workspace-assistant",
  "directory": "/path/to/notes-mvp/sample-notes",
  "time": {"created": 1780156093609, "updated": 1780156093609}
}
```

The session `id` starts with `ses_`.

---

## 2. Send Message

**Method + Path:** `POST /session/{sessionID}/message`

**Minimal request body:**
```json
{
  "agent": "workspace-assistant",
  "parts": [{"type": "text", "text": "What should I focus on today? Use your agenda tools."}]
}
```

**Agent selection field:** `"agent"` — present in both the session-create body (binds the session) and the per-message body. The session-level binding is what matters; the per-message `agent` field repeats it for clarity but is not the primary mechanism.

**Parts array:** Each part has a `"type"` field. For a user prompt, use `{"type": "text", "text": "..."}`.

**Response:** The endpoint returns after the full model turn completes (synchronous, not streaming). It returns the assistant message with all its parts.

---

## 3. Events SSE

**Path:** `GET /event`

**Framing:** Standard SSE — each event is `data: {JSON}\n\n`. No `event:` type line — the event type is inside the JSON.

### 3a. Text Delta Events (CONFIRMED)

The live event type for streaming assistant text is **`message.part.delta`**, NOT `message.part.updated`.

Each token-level delta carries:
- `properties.partID` — the part being built up
- `properties.field` — always `"text"` for text parts (also `"text"` for reasoning parts)
- `properties.delta` — the incremental text chunk

**VERBATIM example (real captured event):**
```json
{
  "id": "evt_e79a2e843001OxM6BZ60LCm2Q7",
  "type": "message.part.delta",
  "properties": {
    "sessionID": "ses_1865e1c51ffeh1JFVnHBz26kGq",
    "messageID": "msg_e79a1e5d3001Qxjw394kzOGtbx",
    "partID": "prt_e79a2dda8001GBFsnt57FpI5Gy",
    "field": "text",
    "delta": " world"
  }
}
```

**Another example (first delta of a turn):**
```json
{
  "id": "evt_e79a2ddab001GL93q4lgFoeB0u",
  "type": "message.part.delta",
  "properties": {
    "sessionID": "ses_1865e1c51ffeh1JFVnHBz26kGq",
    "messageID": "msg_e79a1e5d3001Qxjw394kzOGtbx",
    "partID": "prt_e79a2dda8001GBFsnt57FpI5Gy",
    "field": "text",
    "delta": "════"
  }
}
```

**Mapper field path for text content:** `properties.delta` (not `.properties.part.text`).

### 3b. Tool Call Events (CRITICAL DIFFERENCE FROM PLAN ASSUMPTION)

**Tool call parts do NOT appear in the SSE stream as events.**

Confirmed by cross-referencing partIDs: the SSE stream emits `message.part.delta` for `reasoning` and `text` parts only. The `tool` part (type `"tool"`) is created server-side when the model decides to call a tool, but no SSE event is emitted for it — neither `message.part.updated` nor `session.next.tool.called`.

To observe a completed tool call, poll `GET /session/{sessionID}/message` after `session.idle`. Tool parts appear there with the following shape:

**VERBATIM example (from `GET /session/{id}/message` — NOT from SSE):**
```json
{
  "id": "prt_e79aa41f40019lKFY6trBpYWkJ",
  "sessionID": "ses_18658797bffe1yNmboI4fTq6IS",
  "messageID": "msg_e79a788a20015qOMAN14hx0k5Z",
  "type": "tool",
  "callID": "call_orb5rxao",
  "tool": "agenda_today",
  "state": {
    "status": "completed",
    "input": {},
    "output": "{...JSON string...}",
    "title": "",
    "metadata": {"truncated": false},
    "time": {"start": 1780156231641, "end": 1780156231666}
  }
}
```

**Tool state values:** `pending` | `running` | `completed` | `error`

The `tool` field is the tool name (e.g. `"agenda_today"`). The `callID` matches the model's function-call ID.

### 3c. Turn-Done / Idle Event (CONFIRMED)

**VERBATIM example:**
```json
{
  "id": "evt_e79a2ed6b002m13IYKwoEp2bVu",
  "type": "session.idle",
  "properties": {
    "sessionID": "ses_1865e1c51ffeh1JFVnHBz26kGq"
  }
}
```

**Field path to check:** `type === "session.idle"` AND `properties.sessionID === <our_session_id>` (the event stream is global; events from other sessions appear too).

### 3d. Other Common Events (observed, not used by proxy)

- `session.status` — `{"type": "busy"}` or `{"type": "idle"}` — emitted at turn start/end
- `session.diff` — git diff summary (usually empty `{"diff": []}`)
- `server.connected` — first event on connect
- `server.heartbeat` — periodic keep-alive, ignore

---

## 4. Divergence from Plan's Assumed Shapes

| Plan assumption | Actual OpenCode 1.15.0 |
|---|---|
| Text delta type: `message.part.updated` | **WRONG** — actual: `message.part.delta` |
| Text field path: `properties.part.text` | **WRONG** — actual: `properties.delta` |
| Tool event type: `message.part.updated` with `properties.part.type == "tool"` | **WRONG** — no SSE event for tool calls |
| Tool field: `properties.part.state.status` | N/A (not in SSE stream) |
| Turn-done: `session.idle` | **CORRECT** |
| Session-idle `properties.sessionID` for filtering | **CORRECT** |

**Impact on Tasks 2–6:** The `to_browser_events()` mapper (Task 2) and the fake server (Task 3) must be updated to use `message.part.delta` with `properties.delta`, and tool-call detection must be removed from SSE-based mapping. Tool events should either be omitted from the browser model, or polled via the message API after `session.idle`.

---

## 5. Authentication

`OPENCODE_SERVER_PASSWORD` — when set, `opencode serve` requires HTTP Basic auth:
- Username: `opencode` (hardcoded)
- Password: value of `OPENCODE_SERVER_PASSWORD`
- Header: `Authorization: Basic base64(opencode:<password>)`

When no password is set (as in this spike), any request (including those with wrong credentials) is accepted — no 401 is returned. Confirmed: `curl -u opencode:wrongpassword http://127.0.0.1:4178/global/health` → `{"healthy":true,"version":"1.15.0"}`.

---

## 6. OpenAPI Endpoint Reference

Full OpenAPI spec at `GET /doc`. Key paths:

| Operation | Method | Path |
|---|---|---|
| Health check | GET | `/global/health` |
| Create session | POST | `/session` |
| Send message (blocking) | POST | `/session/{sessionID}/message` |
| Get messages (poll) | GET | `/session/{sessionID}/message` |
| Event stream (SSE) | GET | `/event` |

---

## 7. Recommended Proxy Design (adjusted for real shapes)

Given the above findings, the proxy should:

1. **Text streaming:** consume `message.part.delta` events; for events where `properties.field == "text"`, emit `{"type":"message_delta","text":properties.delta}` to the browser.
2. **Tool calls:** NOT available in real-time SSE. Options:
   - (a) Omit tool_call events from the browser model entirely (simplest).
   - (b) After `session.idle`, poll `GET /session/{id}/message`, inspect tool parts, emit summary events.
   - (c) Watch for part-boundary signals in `message.part.delta` to infer tool invocations (fragile).
3. **Turn done:** on `session.idle` with matching `properties.sessionID`, emit `{"type":"done"}`.
4. **Reasoning parts:** `message.part.delta` events also carry reasoning chunks (`field: "text"`, different `partID`). The proxy can ignore these (they duplicate the model's internal thinking, not final output), or forward them under a separate browser event type.

---

## 8. Live re-verification (2026-05-31) + SSE transport caveat

Re-verified live against `opencode serve 1.15.0` during a full text turn (a separate
capture run on 2026-05-31). The §3 shapes hold exactly: `message.part.delta`
(`properties.field == "text"`, `properties.delta`), `session.idle`, and
`properties.sessionID` for filtering. A turn produced 49 events including 14
`message.part.delta` and 1 `session.idle`. **`frontend/events.py` and
`frontend/opencode_client.iter_events` match this protocol and need no change.**

**Version stability.** Cross-checked the OpenCode **1.15.13** SDK type
(`packages/sdk/js/src/v2/gen/types.gen.ts`, `EventMessagePartDelta`):
`properties: { sessionID, messageID, partID, field: string, delta: string }` —
identical to the 1.15.0 wire shape. The schema is stable across 1.15.0 → 1.15.13.

**Source-name caveat (do not be misled).** The OpenCode *source's* internal
event-v2 system uses `session.next.*` type names (e.g. `session.next.text.delta`).
These are **bridged to the legacy wire names** (`message.part.delta`,
`message.part.updated`, `session.idle`) before they reach `/event`. When matching
event types, read the **wire** protocol (a live capture, or the SDK
`EventMessagePartDelta` / legacy event types) — **not** the internal
`session.next.*` definitions. (Reading the internal names led to a false "the
event names are wrong" conclusion during the 2026-05-31 diagnosis; the wire names
are as documented in §3.)

**SSE TRANSPORT CAVEAT (the real cause of the integration smoke's "0 events").**
OpenCode serves `/event` as **chunked** `text/event-stream`. The HTTP client used
to read it matters:

| Reader | Result on a 49-event turn |
|---|---|
| `httpx` streaming (`client.stream(...).iter_lines()`) | reads the **full** stream (all 49 events incl. deltas + `session.idle`) |
| raw `http.client.HTTPConnection` | drops the stream early — `RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)`; captured only **9** of 49 |

The frontend **relay** reads the upstream via `httpx` (`iter_events`) and is
therefore correct. The **integration smoke** (`tests/smoke/notes-mvp/run_smoke.py`,
`_consume_sse`) reads the frontend's `/api/events` with raw `http.client`, which
drops the chunked stream early and reports 0 browser events — a **test-harness
defect, not a product defect**. Fix: rewrite `_consume_sse` to use `httpx`
streaming (already a dependency).

**Workspace routing.** The `/event` route carries `WorkspaceRoutingMiddleware`, but
`GET /event` (no query) and `GET /event?directory=<workspace>` delivered an
identical event set in testing — no query parameter is needed for the
single-workspace MVP.
