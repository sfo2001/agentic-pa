# Chief-of-Staff Notes — Launcher

`launcher/run.py` is the single entry point that pre-flights the environment,
starts OpenCode and the FastAPI frontend, waits for both to be healthy, then
shuts them down cleanly on Ctrl+C.

## Quick start

**Recommended — use the run shims.** They resolve the correct interpreter
(venv python if the venv's binary runs, else base interpreter +
`PYTHONPATH=.pysite`) and then delegate to `launcher/run.py`:

```bash
# Linux / macOS
INSTALL_ROOT=~/cos-notes ./run.sh

# Windows, cmd.exe (works under Group Policy execution restrictions)
set INSTALL_ROOT=<install-root> && run.cmd

# Windows, PowerShell (.cmd runs fine from a PS prompt — no .ps1 needed)
$env:INSTALL_ROOT="<install-root>"; .\run.cmd
```

`launcher/run.py` itself is unchanged; you can still invoke it directly when
you know the venv python is available and you want minimal indirection:

```
python launcher/run.py
```

The launcher expects `frontend.bootstrap.init_install(...)` to have been run
first so that `<INSTALL_ROOT>/workspace/` exists.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `INSTALL_ROOT` | `~/cos-notes` | Root of the installed notes tree. `workspace/` and `notes.git` live inside here. |
| `OPENCODE_PORT` | `4096` | Port for the OpenCode server (`opencode serve`). Preflight-validated as an integer in 1–65535. |
| `WEB_PORT` | `8000` | Port for the FastAPI frontend (uvicorn). Preflight-validated as an integer in 1–65535. |
| `PYTHON` | `py`/`python3` | Override the base interpreter the `setup.*` / `run.*` shims use before handing off to `install.py` / `launch.py`. |
| `SETUP_MODE` | _(unset)_ | Set to `target` to force the venv-less `pip install --target .pysite` install path (e.g. on an AppLocker-restricted Windows box). Read by the `setup.*` shims. |
| `LLM_WIKI_TOOLS` | `../llm-wiki-tools` | Absolute path to the sibling `llm-wiki-tools` checkout. Surfaced by the `install.py` preflight. |
| `NOTES_GIT_DIR` | _(required)_ | Split git-dir for the notes audit repo (e.g. `<INSTALL_ROOT>/notes.git`), outside the `workspace/` sandbox. **Required** by `frontend/app.py` — start fails with `SystemExit(2)` if unset; normally set by the launcher (ADR-0005). |
| `NOTES_ROOT` | `.` | Root of the notes tree the frontend serves. Surfaced by the `frontend/app.py` preflight. |
| `OPENCODE_BASE_URL` | `http://127.0.0.1:4096` | Base URL the frontend uses to reach `opencode serve`. Preflight-validated as an `http`/`https` URL. |
| `COS_PYSITE` | _(unset)_ | Internal handoff from `install.py` in target/venv-less mode — the absolute `.pysite` path. Surfaced by the `setup_wizard` preflight. |

## Pre-flight checks (abort if any fail)

1. `opencode` is on PATH.
2. `<INSTALL_ROOT>/workspace/` exists.
3. `<INSTALL_ROOT>/notes.git` exists (the split git-dir; run bootstrap first).
4. No `.git` at or above `<INSTALL_ROOT>/workspace/` — see ADR-0005 below.
5. The notes MCP command in `opencode.json` (`mcp.notes.command`) is runnable: its
   interpreter exists on disk/PATH and — for the `python -m <module>` form — the
   module imports under that interpreter. Otherwise the agent's deterministic
   agenda tools would fail.
6. Both `OPENCODE_PORT` and `WEB_PORT` are free. (A benign check-then-bind race
   exists; acceptable for a single-user localhost deployment.)

## Server authentication

The launcher generates a **fresh random `OPENCODE_SERVER_PASSWORD` per run** and
passes it to both `opencode serve` and the frontend. The localhost OpenCode server
therefore requires HTTP Basic auth — other local processes cannot drive the
sandboxed agent. The password is never written to disk and never reaches the
browser (the frontend is the only client that holds it).

## Isolated HOME / XDG + env (security)

OpenCode runs with a synthetic home directory at `<INSTALL_ROOT>/oc-home`, and the
inherited environment is sanitised, so neither the user's global config files nor
their `OPENCODE_*` env vars leak into the sandboxed agent:

- **File channel:** `HOME`, `USERPROFILE` → `<install-root>/oc-home`;
  `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME`;
  `APPDATA`, `LOCALAPPDATA` (Windows).
- **Env channel:** every `OPENCODE_*` variable is **stripped** (notably
  `OPENCODE_CONFIG`, which OpenCode *merges* and could otherwise loosen the
  agent's permissions). Only `OPENCODE_SERVER_PASSWORD` is re-added.

`PATH` is inherited unchanged.

## Logs

OpenCode's stdout/stderr are captured to `<INSTALL_ROOT>/opencode.log` rather than
interleaving with the launcher's own output.

## ADR-0005 — install root must not be inside a git repo

OpenCode's sandbox boundary is the launch cwd **or** the enclosing git
work-tree root. If `workspace/` is anywhere inside a git repo, the agent
could read or write files outside `workspace/` (up to the repo root).

The launcher **refuses to start** if it finds a `.git` directory at
`<INSTALL_ROOT>/workspace/` or any of its ancestor directories.
Install `cos-notes` in a plain directory, e.g. `~/cos-notes` (not under
`~/devel/myproject`).

## Shutdown

Ctrl+C terminates both processes in reverse start order (frontend first,
then OpenCode). Each gets 10 seconds to exit gracefully before `SIGKILL`.

## Notes

- `launcher/run.py` itself is pure Python and cross-platform. The thin
  `run.sh`/`run.cmd` shims (see Quick start) only resolve the interpreter (venv
  python, or a base interpreter + `PYTHONPATH=.pysite`) before delegating to it —
  `run.py`'s own logic is unchanged on every platform.
- The split git-dir (`<install-root>/notes.git`) is passed to the frontend
  via `NOTES_GIT_DIR` so that there is no `.git` inside `workspace/` itself,
  consistent with the ADR-0005 sandbox requirement.
