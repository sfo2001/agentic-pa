# notes-frontend — OpenCode proxy + SSE backend

The sole OpenCode HTTP client for the Chief-of-Staff Notes assistant.
Exposes `/health`, `POST /api/message`, `GET /api/events` (SSE), and
the **Sweep** endpoints (`POST /api/sweep`, `POST /api/sweep/confirm`)
that turn the live conversation transcript into a confirmed Diary entry
plus Actions/Topic updates via the propose-confirm Ingest flow (ADR-0009).
The browser talks only to this service; OpenCode and its credentials are
never exposed to the browser.

## Diary Sweep (ADR-0009)

On demand, the frontend reads the live OpenCode conversation transcript
(since a per-session watermark in the notes git-dir's
`.sweep-state.json` — outside the agent's `workspace/` sandbox so the
agent can't read or write it; see ADR-0005), slices it into size-bounded
windows, snapshots each as an `inbox/` capture, and asks the agent to
Ingest in **PROPOSE mode** (structured JSON: `diary / actions / topics /
meetings`). The browser shows a review panel; on **Confirm**, the
frontend applies the (possibly edited) proposal deterministically to
`diary/`, `tasks.todo.txt`, `topics/`, regenerates each touched topic's
`## Open actions (as of YYYY-MM-DD)` snapshot from the current task list,
runs housekeeping + git commit, and advances the watermark. The agent
never writes directly during a Sweep.

- `POST /api/sweep` → `{ok, proposal, capture, session, last_id}` (or
  `{ok, proposal: null}` when nothing new)
- `POST /api/sweep/confirm` body `{proposal, capture, session, last_id}` →
  `{ok, applied, committed, lint}`. The body is validated by a Pydantic
  v2 model with `Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")` on slugs,
  `Field(max_length=…)` on list caps, and a literal-set `field_validator`
  on topic section headings. A malformed body → **422** at the HTTP
  boundary, not silent drop in the applier.

The Diary is a backward-looking, accreted record at
`workspace/diary/YYYY-MM-DD.md` — opposite lifecycle to the regenerated
**Brief**. `diary/` is excluded from housekeeping (index + orphan lint)
so it coexists without change. See
`docs/adr/0009-propose-confirm-ingest-and-diary-sweep.md` for the full
design.

## Run (against a running opencode serve)

Start `opencode serve` from the notes-mvp workspace directory so it discovers
`opencode.json` by directory-walk:

```sh
# Terminal 1 — OpenCode serve (discovers opencode.json by directory-walk from CWD)
cd $(git rev-parse --show-toplevel)/notes-mvp/sample-notes
OPENCODE_SERVER_PASSWORD=        opencode serve --hostname 127.0.0.1 --port 4096

# Terminal 2 — Frontend (FastAPI + uvicorn factory)
cd $(git rev-parse --show-toplevel)
OPENCODE_BASE_URL=http://127.0.0.1:4096 NOTES_ROOT="$PWD" \
  .venv/bin/uvicorn --factory frontend.app:build_default_app \
    --host 127.0.0.1 --port 8000
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `OPENCODE_BASE_URL` | `http://127.0.0.1:4096` | URL of the running `opencode serve` |
| `OPENCODE_SERVER_PASSWORD` | *(unset)* | Basic-auth password for `opencode serve` (optional) |
| `NOTES_ROOT` | `.` | Root of the notes/ tree for inbox count + upload storage |
| `MODEL_ENDPOINT` | — | Ollama-compatible base URL (written into `opencode.json` by `gen_opencode_config.py`) |
| `MODEL_ID` | — | Model ID to pass to `<ollama-host>` (e.g. `<model-id>`) |

To generate `notes-mvp/opencode.json` from a `.env` file:

```sh
cd $(git rev-parse --show-toplevel)
set -a; . notes-mvp/.env; set +a
.venv/bin/python notes-mvp/gen_opencode_config.py
```

## Single-turn-at-a-time constraint (BH-16)

`NotesProxy.relay()` is **single-flight**: only one SSE stream may be active at a time.
If a second concurrent `GET /api/events` arrives while the first is still streaming,
the proxy immediately returns `{"type":"error","kind":"busy","message":"a turn is already streaming"}`
and closes — it does **not** open a second upstream stream to OpenCode.

**Client requirement:** The N4 browser client must not `POST /api/message` (or open a
new `GET /api/events`) while an existing `/api/events` stream is active.
The intended flow is:

1. POST /api/message — sends the user turn to OpenCode
2. GET /api/events — streams `message_delta` / `tool_call` / `done` events
3. After receiving `done`, the stream is closed and the next turn may begin

This is a design-enforced constraint. There is no queuing of concurrent turns.

If the browser disconnects before `session.idle` arrives from OpenCode (e.g. a page
reload mid-turn), the server-side relay self-clears when `session.idle` eventually
arrives — the relay generator completes and the single-flight lock is released.
A reconnect attempted before that point will receive a `busy` error event; the
client should wait and retry after a short delay.

## Integration smoke

With both services running (ports 4096 and 8000):

```sh
# 1. Health checks (both must return ok)
curl -s http://127.0.0.1:4096/global/health   # {"healthy":true,"version":"1.15.0"}
curl -s http://127.0.0.1:8000/health           # {"ok":true}

# 2. Open SSE event stream FIRST (in a separate terminal / background)
curl -s -N http://127.0.0.1:8000/api/events    # streams message_delta/tool_call/done

# 3. POST a message (blocks until the model turn completes)
curl -s -XPOST http://127.0.0.1:8000/api/message \
  -H 'content-type: application/json' \
  -d '{"text":"What should I focus on today? Use your agenda tools."}'
# → {"ok":true}
```

Expected: the `/api/events` stream shows:

- `{"type":"message_delta","text":"..."}` — one per streamed token
- `{"type":"tool_call","name":"notes_today","status":"completed"}` — after the model
  calls the agenda tool (emitted via post-idle fetch from `GET /session/{id}/message`)
- `{"type":"done"}` — end of turn

The final `done` event is emitted after the proxy receives `session.idle` from OpenCode,
fetches completed tool-call parts via `GET /session/{id}/message`, and emits one
`tool_call` event per tool part before closing the stream.

## Chat UI (manual smoke)

1. One-time: `pip install -e ./frontend` (pulls python-multipart + markitdown).
2. Start OpenCode from the notes dir and the app pointed at it:

       cd notes-mvp/sample-notes
       opencode serve --hostname 127.0.0.1 --port 4096 &
       OPENCODE_BASE_URL=http://127.0.0.1:4096 NOTES_ROOT="$PWD" \
         "$(git rev-parse --show-toplevel)/.venv/bin/uvicorn" \
         --factory frontend.app:build_default_app --port 8000

3. Open http://127.0.0.1:8000/ and verify:
   - Typing a message + Send streams the assistant reply token-by-token; the
     composer disables while streaming and re-enables on completion.
   - "Daily brief" button streams a brief and a `notes_today` tool chip appears.
   - Uploading a .docx/.pdf shows "Stored documents/…(+ Markdown)" and the file
     lands in `notes-mvp/sample-notes/documents/`.
   - The inbox badge shows the count of files in `inbox/` (drop a file there and
     reload, or click Process inbox).
   - A second action while a turn is streaming is ignored (single-turn).

Assistant text is rendered as plain text (untrusted-output safety); Markdown
styling is a future enhancement.

## Notes versioning & undo (ADR-0003)

The frontend versions the notes tree in git (the agent is sandboxed and cannot run
git itself). On startup it initialises `NOTES_ROOT` as **its own git repo** (committer
`Notes Assistant <notes@localhost>`); after each chat turn it commits any changes with
a `notes: <your prompt>` subject; the "Undo last" button (or `POST /api/undo`) reverts
the most recent commit.

**Important:** point `NOTES_ROOT` at a directory **outside this code repo** (e.g.
`~/cos-notes`). A nested `.git` inside `notes-mvp/sample-notes/` would make the code
repo stop tracking that fixture. History: `git -C "$NOTES_ROOT" log --oneline`.

This constraint is now enforced at startup — `ensure_repo` raises a `RuntimeError` with
a clear message if `NOTES_ROOT` overlaps with the application source tree.

A direct `POST /api/undo` during an active `/api/message` turn is serialized server-side
by an `asyncio.Lock` (the UI also disables the Undo button while streaming); concurrent
git index access that would otherwise cause a 500 is prevented.

## Unit tests

```sh
cd $(git rev-parse --show-toplevel)
.venv/bin/pytest tests/frontend/ -v
```

All unit tests run against an in-process fake OpenCode server (no network, no model,
deterministic). The integration smoke above is the only test that requires a live
`opencode serve` and a reachable model endpoint.

## Architecture

```
Browser
  │
  ├─ GET  /                ──► serves frontend/ui/index.html (static chat UI)
  ├─ GET  /health
  ├─ GET  /api/inbox       ──► counts files in notes_root/inbox/
  ├─ POST /api/upload      ──► upload.store_upload() → notes_root/documents/
  ├─ POST /api/message     ──► proxy.send()  ──► OpenCodeClient.send_message()
  ├─ GET  /api/events      ──► proxy.relay() ──► OpenCodeClient.iter_events()
  │                                              │   (SSE: GET /event)
  │                                              └─► OpenCodeClient.tool_calls()
  │                                                      (poll: GET /session/{id}/message)
  ├─ POST /api/sweep       ──► proxy.transcript() + slice + propose_ingest()
  │                          → returns {proposal, capture, session, last_id}
  │                          (no writes; agent emits a structured JSON block)
  └─ POST /api/sweep/confirm ──► proposal.apply_proposal() (deterministic)
                                + sweep.archive_capture() + wiki housekeeping
                                + versioning.commit_all() + watermark advance
```

- **`frontend/events.py`** — pure mapper: OpenCode SSE events → browser event model
- **`frontend/opencode_client.py`** — async HTTP client for `opencode serve`
- **`frontend/proxy.py`** — one long-lived session, relay loop, post-idle tool fetch; `transcript()` + `propose_ingest()` for Sweep
- **`frontend/sweep.py`** — per-session watermark (`.sweep-state.json`), size-bounded window slicing, capture write/archive
- **`frontend/proposal.py`** — parse the agent's structured JSON proposal; apply it deterministically to `diary/`, `tasks.todo.txt`, `topics/`, `meetings/`
- **`frontend/upload.py`** — `store_upload()` + `lwt_convert()` (llm-wiki-tools, adds traceability frontmatter) for office/PDF→Markdown; `markitdown_convert()` retained as a fallback
- **`frontend/app.py`** — FastAPI app; browser-facing endpoints only
