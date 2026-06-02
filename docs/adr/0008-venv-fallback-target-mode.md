# Install supports a venv-less "target" mode so it works where Group Policy blocks executing a venv's exe shims

The installer creates a virtualenv by default, but **probes** whether the venv's
interpreter can actually run and, when it cannot (or when `SETUP_MODE=target` is
set), falls back to a venv-less install: dependencies go into `<repo>/.pysite` via
`pip install --target`, and the app launches with a base interpreter plus
`PYTHONPATH=.pysite`. Platform entry points are thin shims (`setup.*` / `run.*`)
over stdlib Python (`install.py`, `launch.py`, `bootstrap_env.py`), with `.cmd` as
the canonical Windows entry.

## Context

On managed Windows machines, **AppLocker / SRP** commonly blocks executing `.exe`
files from user-writable locations. A virtualenv created under the repo places
`python.exe` (and console-script `*.exe` shims) exactly there, so `python -m venv
.venv` "succeeds" but the resulting interpreter **cannot be executed** — the app
never starts. A *separate* axis, the **PowerShell execution policy**, can block
`.ps1` scripts entirely when set by Group Policy (it ignores `-ExecutionPolicy
Bypass`). The case we must support: AppLocker blocks the venv exe, **but a base
`python`/`py` (e.g. a Program Files install) still runs from user space**.

## Decision

1. **Keep the packages, drop the requirement to run a venv exe.** In target mode,
   `pip install --target <repo>/.pysite <packages>` installs everything beside the
   repo, and the launcher runs a base interpreter with `PYTHONPATH=.pysite`,
   invoking everything as `python -m <module>` — never a console-script `.exe`.
   *Ruled out:* a `shiv`/zipapp bundle (its bundled deps aren't visible to the
   uvicorn subprocess the launcher spawns, so it would need `PYTHONPATH`
   re-plumbing anyway); requiring an IT AppLocker publisher rule (out of our
   control).

2. **venv stays the default; the fallback is auto-detected by probing.** After
   `python -m venv`, run `<venv>/python -c "pass"`; any failure (or
   `SETUP_MODE=target`) switches to target mode. venv mode keeps editable installs
   for development.

3. **`.cmd` is the canonical Windows entry.** A batch file is immune to the
   PowerShell execution-policy axis, is not itself an `.exe`, and runs from both
   `cmd.exe` and PowerShell. The shims hold no logic — they locate a base
   interpreter and hand off to the Python modules.

4. **In target mode, `PYTHONPATH` is baked into the generated `opencode.json` MCP
   `environment`** so OpenCode's `python -m agenda.server` / `presenter.server`
   children are self-sufficient rather than relying on env inheritance down the
   launch chain. `opencode.json` is machine-specific and gitignored, so this
   carries no leak risk.

## Consequences

- One install layout, two interpreter modes, selected at runtime: the same repo
  works on unrestricted dev boxes (venv) and AppLocker-locked boxes (`.pysite`).
- `opencode.json` records the chosen interpreter automatically (the wizard runs
  under it and passes `sys.executable` through), so no config-schema change was
  needed beyond the optional `mcp_pythonpath`.
- **Assumption / limit:** target mode requires a base interpreter that itself runs
  from user space. If even that is policy-blocked, an allow-listed interpreter or
  an IT AppLocker publisher rule is required — out of scope.
- **Could age badly:** `pip install --target` semantics for scripts / `.pth` /
  re-runs have shifted across pip versions; a target-mode smoke that forces
  `SETUP_MODE=target` guards against drift. If any future launch path invokes a
  console-script `.exe` instead of `python -m`, target mode would silently break
  on AppLocker boxes.
