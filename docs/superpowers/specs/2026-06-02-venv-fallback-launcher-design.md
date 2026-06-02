# venv-Optional Install + Policy-Robust Launchers

**Status:** Design (this session) — scope + design only, no production code.
**Origin:** A locked-down Windows box where Group Policy (AppLocker/SRP) blocks
executing the `.exe` shims a venv creates (`.venv\Scripts\python.exe`, console
scripts), so `python -m venv .venv` is effectively unusable — even though a base
`python`/`py` from `Program Files` runs fine. Pairs with the launcher subsystem
(`docs/superpowers/plans/2026-05-30-launcher-and-integration.md`), which already
flagged thin `start.ps1`/`start.sh` wrappers as future work.

## Summary

Today `setup.sh`/`setup.ps1` create a `.venv`, `pip install -e` the four local
packages (`llm-wiki-tools`, `agenda`, `frontend`, `presenter`), and run the
wizard; `launcher/run.py` then drives the app off `sys.executable` (the venv
python) using `python -m uvicorn`/`python -m agenda.server`. Commit `3d9ddbf`
already moved the MCP spawn to the `python -m` form for Windows robustness — this
design extends that same instinct to the **interpreter itself**.

The insight: AppLocker blocks *executing* exes in user-writable dirs, not *having*
the packages. So we keep the packages and drop the requirement to run any
venv-created exe. **Two roots, kept distinct:** the *package site* lives with the repo checkout
(`<repo>/.venv` in venv mode, `<repo>/.pysite` in target mode — both gitignored);
the *install root* (`~/cos-notes`, chosen in the wizard) holds only runtime data
(workspace, `opencode.json`, `notes.git`) and is unchanged by this design.

The result is **one install layout, two interpreter modes,
selected at runtime**:

- **venv mode** (default, dev + unrestricted machines): editable installs exactly
  as today; the launcher uses the venv python.
- **target mode** (AppLocker/restricted machines): no venv; deps installed with
  `pip install --target <repo>/.pysite`; the launcher uses a base interpreter with
  `PYTHONPATH=<repo>/.pysite`. No venv exe is ever executed.

The platform entry scripts (`setup.*`, `run.*`) become **thin shims over a
stdlib-only Python installer/launcher**, with `.cmd` as the canonical Windows
entry (a batch file is immune to the PowerShell-execution-policy GPO axis, and is
not itself an exe).

## Background: the two distinct Windows policy axes

These are routinely conflated; the fix differs per axis. This design targets axis
2 (the user's confirmed case) and incidentally hardens axis 1.

| Axis | What it blocks | `-ExecutionPolicy Bypass`? | This design's answer |
|---|---|---|---|
| **1. PowerShell Execution Policy** (esp. when set by GPO, `MachinePolicy`/`UserPolicy` scope) | Running `.ps1` scripts. GPO-set policy **ignores** the `Bypass` flag. | Useless under GPO | `.cmd` canonical entry (batch is not governed by PS execution policy); `.ps1` kept as convenience only |
| **2. AppLocker / SRP / WDAC** (confirmed case) | Executing `.exe` by path — default rules deny exe under the user profile, allow only `Program Files`/`Windows`. The venv's `python.exe` + console-script `.exe` live in the profile → blocked. | No effect (it governs exes, not scripts) | **target mode** — base interpreter + `pip --target` + `PYTHONPATH` + `python -m`; never execute a venv/user-profile exe |

**Confirmed for this deployment:** axis 2 (AppLocker blocks venv exes) **and** a
base `python`/`py` runs from user space → an app-side fix is sufficient; no IT
ticket required. (If a base interpreter were *also* blocked, no app-side trick
would help — that needs an allow-listed interpreter or an IT publisher rule, and
is explicitly out of scope.)

## Approved decisions

1. **Keep the packages, drop the exes.** Use `pip install --target <repo>/.pysite`
   for the restricted path, not the venv's `Scripts/*.exe`. Launch via a base
   interpreter + `PYTHONPATH` + `python -m`.
2. **venv stays the default; auto-fall-back to target mode.** The installer tries
   `python -m venv .venv`, then **probes** it (`<venv>/python -c "pass"`); on
   failure — or when `SETUP_MODE=target` is forced — it removes the partial
   `.venv` and switches to target mode. venv mode preserves editable (`-e`)
   installs for development.
3. **Reject `shiv`/zipapp here.** A zipapp's bundled deps are not visible to the
   `python -m uvicorn` child the launcher spawns as a separate process, so it
   would need `PYTHONPATH` re-plumbing anyway — adding a moving part to solve a
   problem `--target` solves without one. (Recorded as considered-and-rejected.)
4. **Thin platform shims over Python.** Real install/launch logic lives in
   stdlib-only Python (extending `frontend/bootstrap.py` / `launcher/run.py`);
   `setup.cmd`/`setup.sh`/`setup.ps1` and `run.cmd`/`run.sh`/`run.ps1` only locate
   an interpreter and hand off. This removes the bash/PowerShell duplication and
   makes the logic unit-testable.
5. **`.cmd` is the canonical Windows entry; do NOT rename `setup.ps1`.** A `.cmd`
   that delegated to `powershell` would re-inherit the execution-policy problem;
   one that delegates to a base `python`/`py` does not. `.ps1` is retained as a
   convenience shim over the same Python entry.
6. **The launcher stays interpreter-agnostic.** `launcher/run.py` is unchanged in
   substance: it inherits whatever interpreter invoked it and whatever
   `PYTHONPATH` the shim set, and that env propagates to its `uvicorn` child and
   to OpenCode's MCP spawn.

## Architecture

### Mode selection (install time)

```
setup.cmd / setup.sh / setup.ps1   (thin shim: find base python, hand off)
        │
        ▼
python install.py        (stdlib-only; runnable by base interpreter)
        │
        ├── try: python -m venv .venv
        │     └── probe: <venv>/python -c "pass"
        │           ├── ok  ──► VENV MODE:   pip install -e <pkgs> (+ dev reqs)
        │           └── fail ─► fall through ↓
        └── TARGET MODE (probe failed, or SETUP_MODE=target):
              rm -rf partial .venv
              <base> -m pip install --target <repo>/.pysite <lwt> ./agenda ./frontend ./presenter
        │
        ▼
record chosen interpreter into the generated machine-local opencode.json
(MCP command[0]); run the setup wizard
```

Where `<base>` is the resolved base interpreter (`py -3` / `python3` / `python`).

### Launch (deployed install dir)

```
run.cmd / run.sh / run.ps1   (thin shim: resolve interpreter, set PYTHONPATH)
        │   if .venv/python exists AND runs ──► use it
        │   else                            ──► base python + PYTHONPATH=<repo>/.pysite
        ▼
<python> launcher/run.py   (unchanged)
        ├── spawn: opencode serve            (isolated_env preserves PYTHONPATH)
        │     └── opencode spawns MCP: python -m agenda.server  (inherits PYTHONPATH)
        └── spawn: <same python> -m uvicorn frontend.app  (inherits PYTHONPATH via env)
```

### Why the wiring holds

- `launcher/run.py` already builds the uvicorn subprocess `env` from `os.environ`
  (`launcher/run.py:226`), so a `PYTHONPATH` set by the shim flows to the uvicorn
  child unchanged.
- `isolated_env` strips `OPENCODE_*` and `LD_*`/`DYLD_*` but **preserves
  `PYTHONPATH`** (`launcher/run.py:64-78`), so OpenCode — and the `python -m
  agenda.server` MCP process it spawns from `opencode.json` — both see the target
  `site` dir.
- The launch path only ever uses `python -m <module>`; it never executes a
  console-script `.exe`. So even though `pip install --target` may drop unused
  `Scripts/*.exe` wrappers into `<repo>/.pysite`, that is harmless: AppLocker
  blocks *executing* an exe, not pip *writing* one, and nothing in the launch path
  runs them.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `install.py` (new, stdlib-only) | venv-attempt → probe → fallback → install; resolve & record interpreter; invoke wizard | stdlib `subprocess`/`venv`/`shutil`; `frontend.setup_wizard` (post-install) |
| `setup.cmd`/`.sh`/`.ps1` (shims) | locate base interpreter, `<py> install.py "$@"` | a base `python`/`py` on PATH |
| `run.cmd`/`.sh`/`.ps1` (new/rework) | resolve interpreter (venv-if-runs else base+`PYTHONPATH`), `<py> launcher/run.py` | install layout produced above |
| `launcher/run.py` (unchanged) | preflight + start/stop OpenCode + frontend | inherited interpreter + `PYTHONPATH` |
| `opencode.json` generator | record `command[0]` = chosen interpreter (venv python or base) | `install.py` mode decision |

## Detection design (the fallback trigger)

Probe, don't trust. AppLocker failure surfaces either at venv's own `ensurepip`
step (venv creation runs the new `python.exe`) or at an explicit post-create
probe. The installer therefore wraps **both** venv creation and a
`<venv>/python -c "pass"` probe; any non-zero exit / OS error / "blocked by group
policy" signal trips the fallback. An explicit `SETUP_MODE=target` escape hatch
lets an operator who already knows the box is locked down skip the venv attempt
entirely.

## Error handling

- Base interpreter missing → both shims and `install.py` fail fast with the same
  "install Python 3.10+ / set PYTHON=…" message the current scripts emit.
- venv attempt fails for a non-policy reason (disk, perms) → still falls back to
  target mode; the failure is logged so a genuine environment problem is visible,
  not silently masked.
- `llm-wiki-tools` sibling missing → unchanged hard error (as today).
- target-mode `--target` re-runs → use `--upgrade` and tolerate pip's "target
  already exists" notices; document that a clean reinstall is `rm -rf
  <repo>/.pysite` then re-run (known `--target` staleness caveat).

## Testing

- **Unit (TDD-able):** `install.py` mode-selection logic with the venv-probe
  mocked (probe-ok → venv mode; probe-fail → target mode; `SETUP_MODE=target` →
  target mode without attempting venv). Interpreter-recording into `opencode.json`
  asserted per mode.
- **Unit:** run-shim interpreter resolution — venv-python-runs → venv; else base +
  `PYTHONPATH`. (Logic in a small Python helper the shims call, so it is testable
  rather than living in batch/sh.)
- **Smoke (manual + scripted subset):** on a clean machine, force `SETUP_MODE=target`,
  confirm no `.venv` is used, the app launches, the MCP `python -m agenda.server`
  resolves (deterministic agenda tools work), and no console-script exe is invoked.
- Existing launcher/bootstrap suites stay green (the launcher is unchanged).

## Scope

**In scope:** venv-probe + `--target` fallback in a new stdlib `install.py`; thin
`setup.*`/`run.*` shims with `.cmd` canonical on Windows; recording the chosen
interpreter into `opencode.json`; tests for the mode-selection + interpreter
resolution.

**Out of scope:** the case where even a base interpreter is policy-blocked (needs
an allow-listed interpreter / IT publisher rule); a packaged MSI/service installer;
`shiv`/zipapp packaging; signing.

## How this could age badly

- pip's `--target` semantics for scripts/`.pth`/re-runs have shifted across
  versions; pin the documented reinstall recipe and keep the smoke that exercises
  target mode so a pip change is caught.
- If a future launch path ever calls a console-script exe directly (instead of
  `python -m`), target mode silently breaks on AppLocker boxes. The smoke's
  "no exe invoked" assertion is the guard; keep it.
