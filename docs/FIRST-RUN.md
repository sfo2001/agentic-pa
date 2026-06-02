# First run — standing up your own Chief-of-Staff Notes install

This walks you from a clone to a running assistant on your real notes. Everything
is local; nothing leaves your machine except calls to your own model endpoint.

> **Fastest path — the guided wizard.** Run `./setup.sh` (Linux/macOS) or
> `powershell -ExecutionPolicy Bypass -File setup.ps1` (Windows). It creates the
> venv, installs the packages, checks your environment (and tells you how to fix
> anything missing), then prompts for your model endpoint (with a model pick-list),
> install location, and writes the install. The manual steps below are what the
> wizard automates — read them if you want to understand or script it yourself.

## 0. Prerequisites

- **Python 3.10+**
- **[`opencode`](https://opencode.ai)** on your `PATH` (`opencode --version`)
- An **OpenAI-compatible model endpoint** — e.g. a local ollama at
  `http://<host>:11434/v1` serving a capable instruct model.

## 1. Install the packages (in a venv)

```bash
cd /path/to/agentic-pa
python3 -m venv .venv && . .venv/bin/activate
pip install -e ./agenda -e ./frontend -e ./presenter
pip install -r agenda/requirements-dev.txt -r frontend/requirements-dev.txt
```

`agenda-server` is now on the venv's `PATH` (`which agenda-server`).

## 2. Bootstrap an install root (OUTSIDE any git repo)

The install root holds your config, the system prompt, the notes audit repo, and
the agent's `workspace/`. **It must not live inside a git repository** (the
launcher refuses to start otherwise — see ADR-0005). `~/cos-notes` is a good spot.

```bash
python - <<'PY'
from frontend.bootstrap import init_install
from pathlib import Path
layout = init_install(
    Path.home() / "cos-notes",
    model_endpoint="http://<your-host>:11434/v1",   # your model endpoint
    model_id="<your-model-id>",                      # e.g. a 64k-context instruct model
    agenda_server=str(Path(".venv/bin/agenda-server").resolve()),
    # api_key="sk-...",   # only if your endpoint requires auth (omit for Ollama/local)
)
print("installed:", layout["install_root"])
PY
```

> **Authenticated endpoints:** if your endpoint needs an API key, pass
> `api_key="sk-..."`. The key is stored in OpenCode's own credential file
> (`<install>/oc-home/.local/share/opencode/auth.json`, mode 600) and is
> deliberately **kept out of `opencode.json`** — an inline `apiKey` there would
> shadow it. The interactive `setup_wizard` does this for you: it detects a
> 401/403 from the endpoint and prompts for the key (input hidden).

This creates:

```
~/cos-notes/
  opencode.json   .env(.example)   notes-agent.md   notes.git/   oc-home/
  workspace/      ← your notes live here (inbox/ meetings/ topics/ documents/ briefs/ archive/)
```

`opencode.json` carries your endpoint/model and is **machine-specific — it is not
committed** (the repo only ships the generic generator).

## 3. Run it

```bash
INSTALL_ROOT=$HOME/cos-notes .venv/bin/python launcher/run.py
# Ready — open http://127.0.0.1:8000/   (Ctrl+C to stop)
```

The launcher pre-flights (tools present, `notes.git` exists, no `.git` above
`workspace/`, `agenda-server` resolvable, ports free), generates a per-run server
password, isolates the agent's HOME/XDG + env, starts OpenCode and the frontend,
and waits for both to be healthy. OpenCode's log goes to
`~/cos-notes/opencode.log`. Override ports with `OPENCODE_PORT` / `WEB_PORT`.

## 4. Use it

- **Drop raw notes** into `~/cos-notes/workspace/inbox/` (any `.md`/`.txt`), then
  click **Process inbox** (or type "Process the inbox.").
- **Daily brief** / **Weekly review** buttons run the deterministic agenda loop.
- **Upload** a PPTX/DOCX/PDF — it lands in `workspace/documents/` with a `.md`
  sibling, linkable from a topic.
- Every notes-changing turn is **committed** to `notes.git` with the agent's
  one-line changelog as the subject; **Undo last** reverts it.

## 5. Daily-driver tips

- Keep the launcher running in a terminal (or wrap it in a `tmux`/user service).
- Your notes are plain Markdown + `tasks.todo.txt` — greppable and hand-editable.
- The agenda math (what's due / resurfacing / stale) is deterministic code, so a
  date-based follow-up never silently slips even if the model misses it.
