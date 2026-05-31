# Chief-of-Staff Notes — Launcher

`launcher/run.py` is the single entry point that pre-flights the environment,
starts OpenCode and the FastAPI frontend, waits for both to be healthy, then
shuts them down cleanly on Ctrl+C.

## Quick start

```
python launcher/run.py
```

The launcher expects `frontend.bootstrap.init_install(...)` to have been run
first so that `<INSTALL_ROOT>/workspace/` exists.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `INSTALL_ROOT` | `~/cos-notes` | Root of the installed notes tree. `workspace/` and `notes.git` live inside here. |
| `OPENCODE_PORT` | `4096` | Port for the OpenCode server (`opencode serve`). |
| `WEB_PORT` | `8000` | Port for the FastAPI frontend (uvicorn). |

## Pre-flight checks (abort if any fail)

1. `opencode` is on PATH.
2. `<INSTALL_ROOT>/workspace/` exists.
3. `<INSTALL_ROOT>/notes.git` exists (the split git-dir; run bootstrap first).
4. No `.git` at or above `<INSTALL_ROOT>/workspace/` — see ADR-0005 below.
5. The `agenda-server` configured in `opencode.json` (`mcp.agenda.command`) exists
   on disk or PATH — otherwise the agent's deterministic agenda tools would fail.
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

- This is a pure-Python launcher; no PowerShell or shell scripts are used.
  On Windows it works the same way (replace `python` with `py` if needed).
- The split git-dir (`<install-root>/notes.git`) is passed to the frontend
  via `NOTES_GIT_DIR` so that there is no `.git` inside `workspace/` itself,
  consistent with the ADR-0005 sandbox requirement.
