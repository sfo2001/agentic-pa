# Smoke Test Checklist — Chief-of-Staff Notes MVP

## Prerequisites

1. **OpenCode is on PATH**: `which opencode` must succeed.
2. **Model is running** on your inference host: `MODEL_ENDPOINT` must be reachable and the model loaded. Example: `http://<your-host>:11434/v1`, model `<your-model>`.
3. **Venv is active** and project packages are installed:
   ```
   source .venv/bin/activate
   pip install -e '.[dev]'   # ensures agenda/presenter import for `python -m` spawn
   ```
4. **Bootstrap an install root** outside any git repository (e.g. `~/cos-notes-test`):
   ```
   export INSTALL_ROOT=~/cos-notes-test
   export MODEL_ENDPOINT=http://<your-host>:11434/v1
   export MODEL_ID=<your-model>
   python -c "
   from frontend.bootstrap import init_install
   import sys, os
   info = init_install(
       os.environ['INSTALL_ROOT'],
       model_endpoint=os.environ['MODEL_ID'],   # INTENTIONAL — see bootstrap sig
       model_id=os.environ['MODEL_ID'],
       python_executable=sys.executable,
   )
   print(info)
   "
   ```
   Or just let `run_smoke.py` do it in a temp directory (recommended for CI).

5. **`opencode` on PATH**: confirm `which opencode` returns a path.

---

## Running the Automated Smoke Script

The script creates a throwaway install root under `/tmp`, starts OpenCode and the frontend on free ports, sends one message, asserts the full turn cycle (ingest → SSE stream → git commit → undo), then tears everything down.

```bash
# From the repo root, with the venv active:
MODEL_ENDPOINT=http://<your-host>:11434/v1 \
MODEL_ID=<your-model> \
python tests/smoke/notes-mvp/run_smoke.py
```

Optional env vars:

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_ENDPOINT` | `http://<your-host>:11434/v1` | OpenAI-compatible inference base URL |
| `MODEL_ID` | `<your-model>` | Model identifier |
| `SMOKE_TURN_TIMEOUT` | `180` | Seconds to wait for a full SSE turn (model inference) |
| `SMOKE_OC_HEALTH_TIMEOUT` | `60` | Seconds to wait for opencode /global/health |
| `SMOKE_FRONTEND_HEALTH_TIMEOUT` | `30` | Seconds to wait for frontend /health |

Exit code `0` = all checks passed. Exit code `1` = one or more checks failed.

The script checks:
- [ ] SSE stream delivered at least one `message_delta` event
- [ ] SSE stream ended with a `done` event (not `error`)
- [ ] workspace gained a file under `meetings/`, `topics/`, or `tasks.todo.txt` was modified
- [ ] `notes.git` log contains a commit whose subject includes `Process the inbox`
- [ ] No `.git` exists at or above `workspace/` (sandbox boundary intact)
- [ ] `POST /api/undo` returns `{"ok": true}`
- [ ] git log changes after undo (revert commit is added, content is rolled back)

---

## Manual Browser Smoke Checklist

### Setup

1. Start the stack with a real install root:
   ```bash
   INSTALL_ROOT=~/cos-notes-test python -m launcher.run
   ```
   Open `http://127.0.0.1:8000/` in a browser.

2. Confirm the UI loads (chat panel, toolbar visible).

### Checklist

- [ ] **Health**: `GET http://127.0.0.1:8000/health` returns `{"ok": true}` (or check the browser network tab).

- [ ] **Send a message and confirm streaming**:
  - Type "What meetings do I have this week?" in the chat input and press Send.
  - The response should stream in character-by-character (text chunks appear progressively).
  - Wait for the response to complete (stream ends).

- [ ] **Tool chip appears**:
  - Click the "Daily brief" button (or send "Prepare today's briefing.").
  - Confirm that at least one tool chip (e.g. `agenda_today_brief`) is rendered in the chat alongside the response text.

- [ ] **Upload a document**:
  - Use the upload button/drag-drop to send a `.pdf`, `.docx`, or `.txt` file.
  - Confirm the API returns `{"ok": true, ...}`.
  - Confirm the file is present under `$INSTALL_ROOT/workspace/documents/`.

- [ ] **Inbox badge**:
  - Drop a `.md` file into `$INSTALL_ROOT/workspace/inbox/`.
  - Refresh the browser (or wait for the badge to update if polling is active).
  - Confirm the inbox badge/count is non-zero.

- [ ] **Undo last**:
  - After any message that results in a file change, click the Undo button.
  - Confirm the UI reports success.
  - Confirm the most recent edit is rolled back in the workspace.

### Audit repo verification

Confirm the audit repository is stored as a **split git-dir** — `notes.git/` lives in the install root's parent directory, and there is NO `.git` directory at or below `workspace/`:

```bash
# This should FAIL (no .git in or above workspace):
git -C $INSTALL_ROOT/workspace rev-parse --show-toplevel
# Expected: error: "not a git repository"

# This should SUCCEED (notes.git is valid):
git --git-dir=$INSTALL_ROOT/notes.git log --oneline | head -5
```

If `git -C $INSTALL_ROOT/workspace rev-parse --show-toplevel` succeeds, the sandbox boundary is broken — do NOT proceed.
