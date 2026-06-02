# First run — standing up your own Chief-of-Staff Notes install

This walks you from a clone to a running assistant on your real notes. Everything
is local; nothing leaves your machine except calls to your own model endpoint.

> **Fastest path — the guided wizard.**
>
> | Platform | Canonical entry | Convenience alternative |
> |---|---|---|
> | Linux / macOS | `./setup.sh` | — |
> | Windows | `setup.cmd` (double-click, or run from cmd.exe or PowerShell) | — |
>
> The wizard creates a venv, installs the packages, checks your environment (and tells
> you how to fix anything missing), then prompts for your model endpoint (with a model
> pick-list), install location, and writes the install.
>
> **Windows note:** `setup.cmd` is the canonical Windows entry. 
>
> The manual steps below are what the wizard automates — read them if you want to
> understand or script it yourself.

## 0. Prerequisites

- **Python 3.10+**
- **[`opencode`](https://opencode.ai)** on your `PATH` (`opencode --version`)
- An **OpenAI-compatible model endpoint** — e.g. a local ollama at
  `http://<host>:11434/v1` serving a capable instruct model.

## 1. Install the packages

The setup shim (`setup.sh` / `setup.cmd`) hands off to `install.py`, which
handles the full install automatically. Two modes are supported:

**Normal mode (venv — default)**

```bash
# Linux / macOS
./setup.sh

# Windows (cmd.exe or PowerShell)
setup.cmd
```

`install.py` creates a `.venv/`, installs the project packages into it, then
probes whether the venv's interpreter actually runs. On most systems this just
works and you never need to think about it.

**Fallback mode (venv-less — `.pysite/`)**

If the venv's `python.exe` can't execute — for example, AppLocker or SRP on a
managed Windows box blocks running the venv's binary — `install.py`
automatically falls back to a venv-less install:

```
pip install --target .pysite <packages>
```

The launcher then invokes the base interpreter with `PYTHONPATH=.pysite` so
that no venv binary is ever required.  Everything runs as `python -m <module>`.

You can also force this mode explicitly:

```bash
# Linux / macOS
SETUP_MODE=target ./setup.sh

# Windows
set SETUP_MODE=target && setup.cmd
```

**Assumption / limit:** the fallback needs a base `python` / `py` interpreter
that itself runs from user space (e.g. a Program Files install accessible to
your account). If even the base interpreter is policy-blocked you need an
allow-listed interpreter or an IT AppLocker publisher rule — that is out of
scope here.

After either mode, `agenda` and `presenter` are importable under the resolved
interpreter (`python -c "import agenda.server, presenter.server"`) — the MCP
servers are spawned via `python -m`, not console-script executables.

## 2. Bootstrap an install root (OUTSIDE any git repo)

The install root holds your config, the system prompt, the notes audit repo, and
the agent's `workspace/`. **It must not live inside a git repository** (the
launcher refuses to start otherwise — see ADR-0005). `~/cos-notes` is a good spot.

```bash
python - <<'PY'
import sys
from frontend.bootstrap import init_install
from pathlib import Path
layout = init_install(
    Path.home() / "cos-notes",
    model_endpoint="http://<your-host>:11434/v1",   # your model endpoint
    model_id="<your-model-id>",                      # e.g. a 64k-context instruct model
    python_executable=sys.executable,               # spawns the MCP servers via `python -m`
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
  opencode.json   notes-agent.md   notes.git/   oc-home/
  workspace/      ← your notes live here (inbox/ meetings/ topics/ documents/ briefs/ archive/)
```

`opencode.json` carries your endpoint/model and is **machine-specific — it is not
committed** (the repo only ships the generic generator).

## 3. Run it

Use the launch shim, which picks the right interpreter automatically (venv
python if available, else base interpreter + `PYTHONPATH=.pysite`):

```bash
# Linux / macOS
INSTALL_ROOT=~/cos-notes ./run.sh

# Windows, cmd.exe
set INSTALL_ROOT=<install-root> && run.cmd

# Windows, PowerShell (.cmd runs fine from a PS prompt — no .ps1 needed)
$env:INSTALL_ROOT="<install-root>"; .\run.cmd
```

```
# Ready — open http://127.0.0.1:8000/   (Ctrl+C to stop)
```

`INSTALL_ROOT` defaults to `~/cos-notes` if unset. The shims delegate to
`launcher/run.py`, which pre-flights (tools present, `notes.git` exists, no
`.git` above `workspace/`, the notes MCP interpreter present + `agenda`
importable, ports free), generates a per-run server password, isolates the
agent's HOME/XDG + env, starts OpenCode and the frontend, and waits for both
to be healthy. OpenCode's log goes to `<install-root>/opencode.log`. Override
ports with `OPENCODE_PORT` / `WEB_PORT`.

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
