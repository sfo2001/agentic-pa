# venv-Optional Install + Policy-Robust Launchers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make install + launch work on a Windows box where AppLocker/SRP blocks executing the `.exe` shims a venv creates, while keeping the editable-venv flow as the default for development.

**Architecture:** Keep venv as the default; **probe** the venv's `python` after creating it and, on failure (or when `SETUP_MODE=target` is set), fall back to a venv-less mode that installs deps with `pip install --target <repo>/.pysite` and launches with a base interpreter + `PYTHONPATH`. All real logic moves into three stdlib-only Python modules (`bootstrap_env.py`, `install.py`, `launch.py`); the platform scripts (`setup.*`, `run.*`) become thin shims that locate a base interpreter and hand off, with `.cmd` as the canonical Windows entry (a batch file is immune to the PowerShell-execution-policy GPO axis, and is not itself an exe).

**Tech Stack:** Python 3.10+ stdlib (`subprocess`, `venv`, `shutil`, `pathlib`) · pip `--target` · pytest · existing `frontend`/`launcher` packages.

**Spec:** `docs/superpowers/specs/2026-06-02-venv-fallback-launcher-design.md`

---

## Refinements locked in from spec review

- **Two distinct roots.** The *package site* lives with the repo checkout: `<repo>/.venv` (venv mode) or `<repo>/.pysite` (target mode), both gitignored. The *install root* (`~/cos-notes`, chosen in the wizard) holds only runtime data and is unchanged. The launcher resolves the interpreter relative to the **repo**, not the install root.
- **The interpreter is already recorded correctly today.** `frontend/setup_wizard.py:255-261` passes `python_executable=sys.executable` into `init_install`, and `frontend.config.build_opencode_config` already emits the MCP command in `python -m <module>` form. So in target mode the wizard simply runs under the base interpreter and the right interpreter lands in `opencode.json` automatically — no config-schema change needed.
- **Unused `.exe` wrappers are harmless.** `pip install --target` may still write `Scripts/*.exe`; nothing in the launch path runs them (it is all `python -m`), and AppLocker blocks *executing* an exe, not pip *writing* one.

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `bootstrap_env.py` | Create | Stdlib helpers shared by install + launch: locate `.venv` python / `.pysite`, probe whether an interpreter runs, resolve the launch interpreter + env. |
| `install.py` | Create | venv-attempt → probe → fallback; install deps (editable in venv mode, `--target` in target mode); run the wizard under the chosen interpreter. Replaces the venv/pip logic currently inlined in `setup.sh`/`setup.ps1`. |
| `launch.py` | Create | Resolve the interpreter (venv-if-runs else base + `PYTHONPATH=.pysite`) and delegate to `launcher.run`. |
| `setup.sh` / `setup.ps1` | Modify (gut to shim) | Locate a base interpreter, `cd` to repo, `<py> install.py "$@"`. |
| `setup.cmd` | Create | Canonical Windows setup entry (batch shim → `install.py`). |
| `run.sh` / `run.ps1` | Create | Thin launch shims → `launch.py`. |
| `run.cmd` | Create | Canonical Windows launch entry (batch shim → `launch.py`). |
| `frontend/setup_wizard.py` | Modify `:268-274` | Print the run-shim command as the primary launch instruction (mode-aware), via a testable `launch_command` helper. |
| `.gitignore` | Modify `:1` area | Add `.pysite/`. |
| `tests/install/__init__.py` | Create | Package marker. |
| `tests/install/test_bootstrap_env.py` | Create | Tests for `python_runs`, `resolve_launch`. |
| `tests/install/test_install_mode.py` | Create | Tests for `choose_mode`, `forced_target`. |
| `tests/frontend/test_setup_wizard.py` | Modify | Test for `launch_command`. |
| `docs/FIRST-RUN.md`, `launcher/README.md` | Modify | Document the two modes + the `.cmd`/`SETUP_MODE` entry points. |

> All `pytest` commands below assume the dev machine's venv (`.venv/bin/pytest`). The new logic is pure stdlib and runs under any Python 3.10+.

---

### Task 1: Shared bootstrap helpers + gitignore

**Files:**
- Create: `bootstrap_env.py`
- Modify: `.gitignore:1`
- Create: `tests/install/__init__.py`
- Test: `tests/install/test_bootstrap_env.py`

- [ ] **Step 1: Add `.pysite/` to `.gitignore`**

Change the top of `.gitignore` from:

```
.venv/
```

to:

```
.venv/
.pysite/
```

- [ ] **Step 2: Create the test package marker**

Create `tests/install/__init__.py` as an empty file:

```python
```

- [ ] **Step 3: Write the failing tests**

Create `tests/install/test_bootstrap_env.py`:

```python
import os
import sys
from pathlib import Path

import bootstrap_env


def test_python_runs_true_for_current_interpreter():
    assert bootstrap_env.python_runs(sys.executable) is True


def test_python_runs_false_for_missing_path(tmp_path):
    assert bootstrap_env.python_runs(tmp_path / "nope" / "python") is False


def test_resolve_launch_prefers_runnable_venv(tmp_path, monkeypatch):
    vpy = bootstrap_env.venv_python(tmp_path)
    vpy.parent.mkdir(parents=True)
    vpy.write_text("")  # presence only; we stub the run-probe
    monkeypatch.setattr(bootstrap_env, "python_runs", lambda p: True)
    interp, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert interp == str(vpy)
    assert env == {}


def test_resolve_launch_falls_back_to_pysite_when_no_venv(tmp_path, monkeypatch):
    (tmp_path / ".pysite").mkdir()
    monkeypatch.delenv("PYTHONPATH", raising=False)
    interp, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert interp == "/usr/bin/python3"
    assert env["PYTHONPATH"] == str(tmp_path / ".pysite")


def test_resolve_launch_prepends_existing_pythonpath(tmp_path, monkeypatch):
    (tmp_path / ".pysite").mkdir()
    monkeypatch.setenv("PYTHONPATH", "/existing")
    _, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert env["PYTHONPATH"] == str(tmp_path / ".pysite") + os.pathsep + "/existing"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/install/test_bootstrap_env.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bootstrap_env'`.

- [ ] **Step 5: Implement `bootstrap_env.py`**

Create `bootstrap_env.py`:

```python
"""Stdlib-only helpers shared by install.py and launch.py.

Two roots, kept distinct: the *package site* lives with the repo checkout
(``<repo>/.venv`` in venv mode, ``<repo>/.pysite`` in target mode); the *install
root* (``~/cos-notes``) holds runtime data and is not this module's concern.

The target mode exists for locked-down Windows where AppLocker/SRP blocks
executing the venv's ``python.exe`` — we never run a venv exe, only a base
interpreter + ``PYTHONPATH`` pointed at ``.pysite`` (see
docs/superpowers/specs/2026-06-02-venv-fallback-launcher-design.md).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def venv_python(repo: Path | str) -> Path:
    """Path to the venv's interpreter under <repo>/.venv (may not exist)."""
    base = Path(repo) / ".venv"
    return base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def pysite_dir(repo: Path | str) -> Path:
    """The target-mode package directory (``pip install --target`` destination)."""
    return Path(repo) / ".pysite"


def python_runs(interpreter: Path | str) -> bool:
    """True iff *interpreter* can actually execute. On AppLocker/SRP boxes the
    venv's python.exe exists but is blocked from running — this is the probe that
    distinguishes 'created' from 'usable'. Fails closed on any error/timeout."""
    try:
        return subprocess.run(
            [str(interpreter), "-c", "pass"],
            capture_output=True, timeout=10,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_launch(repo: Path | str, base: str | None = None) -> tuple[str, dict]:
    """Pick the launch interpreter and any env overrides.

    Returns ``(interpreter, env_overrides)``:
      * venv python if it exists AND runs  → (venv_python, {})
      * else if <repo>/.pysite exists       → (base, {"PYTHONPATH": .pysite[:existing]})
      * else                                → (base, {})  (let the launcher's own
                                               preflight report the missing install)
    """
    repo = Path(repo)
    base = base or sys.executable
    vpy = venv_python(repo)
    if vpy.exists() and python_runs(vpy):
        return str(vpy), {}
    site = pysite_dir(repo)
    if site.is_dir():
        existing = os.environ.get("PYTHONPATH", "")
        pythonpath = str(site) + (os.pathsep + existing if existing else "")
        return base, {"PYTHONPATH": pythonpath}
    return base, {}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/install/test_bootstrap_env.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add bootstrap_env.py tests/install/__init__.py tests/install/test_bootstrap_env.py .gitignore
git commit -m "feat(install): shared bootstrap_env helpers (venv probe + launch resolution)"
```

---

### Task 2: Install mode decision + orchestration

**Files:**
- Create: `install.py`
- Test: `tests/install/test_install_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/install/test_install_mode.py`:

```python
import install


def test_choose_mode_venv_when_probe_ok():
    assert install.choose_mode(forced_target=False, venv_ok=True) == "venv"


def test_choose_mode_target_when_probe_fails():
    assert install.choose_mode(forced_target=False, venv_ok=False) == "target"


def test_choose_mode_target_when_forced_skips_venv():
    # forced wins even if a venv would have worked — operator override
    assert install.choose_mode(forced_target=True, venv_ok=True) == "target"


def test_forced_target_reads_env():
    assert install.forced_target({"SETUP_MODE": "target"}) is True
    assert install.forced_target({"SETUP_MODE": "TARGET"}) is True
    assert install.forced_target({"SETUP_MODE": "venv"}) is False
    assert install.forced_target({}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/install/test_install_mode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'install'`.

- [ ] **Step 3: Implement `install.py`**

Create `install.py`:

```python
"""One-command setup with venv→target fallback (cross-platform, stdlib only).

Invoked by the thin shims (setup.cmd / setup.sh / setup.ps1) under a *base*
interpreter. Tries to create and USE a venv; if the venv's python can't run
(AppLocker/SRP) or ``SETUP_MODE=target`` is set, falls back to a venv-less
``pip install --target <repo>/.pysite`` and launches the wizard under the base
interpreter with PYTHONPATH set. See the design spec for the policy rationale.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import bootstrap_env

REPO = Path(__file__).resolve().parent
LOCAL_PKGS = ["./agenda", "./frontend", "./presenter"]


def forced_target(env: dict) -> bool:
    """True iff the operator forced target mode via ``SETUP_MODE=target``."""
    return env.get("SETUP_MODE", "").strip().lower() == "target"


def choose_mode(*, forced_target: bool, venv_ok: bool) -> str:
    """Pure mode decision. Forced target wins; else venv if the probe passed."""
    if forced_target:
        return "target"
    return "venv" if venv_ok else "target"


def _run(cmd: list[str], **kw) -> None:
    """Run *cmd*, echoing it; raise on non-zero so setup fails loudly."""
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def _lwt_path() -> str:
    """Resolve the required llm-wiki-tools sibling checkout (or exit with help)."""
    lwt = os.environ.get("LLM_WIKI_TOOLS", "../llm-wiki-tools")
    if not Path(lwt).is_dir():
        sys.exit(
            f"ERROR: llm-wiki-tools not found at '{lwt}' (a required sibling "
            "checkout). Clone it next to this repo (../llm-wiki-tools) or set "
            "LLM_WIKI_TOOLS=/path and re-run."
        )
    return lwt


def try_make_venv() -> bool:
    """Create <repo>/.venv and probe its python. True iff usable.

    On failure (creation error OR the probe shows the exe is policy-blocked),
    remove the partial venv and return False so the caller falls back."""
    venv_dir = REPO / ".venv"
    try:
        _run([sys.executable, "-m", "venv", str(venv_dir)])
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(venv_dir, ignore_errors=True)
        return False
    if bootstrap_env.python_runs(bootstrap_env.venv_python(REPO)):
        return True
    print("  ! venv created but its python can't run (AppLocker/SRP?) — "
          "falling back to a venv-less install.")
    shutil.rmtree(venv_dir, ignore_errors=True)
    return False


def main() -> int:
    os.chdir(REPO)
    lwt = _lwt_path()
    forced = forced_target(os.environ)
    venv_ok = False if forced else try_make_venv()
    mode = choose_mode(forced_target=forced, venv_ok=venv_ok)
    print(f"Install mode: {mode}")

    if mode == "venv":
        py = str(bootstrap_env.venv_python(REPO))
        _run([py, "-m", "pip", "install", "--upgrade", "pip"])
        _run([py, "-m", "pip", "install", "-e", lwt, *sum((["-e", p] for p in LOCAL_PKGS), [])])
        _run([py, "-m", "pip", "install",
              "-r", "agenda/requirements-dev.txt", "-r", "frontend/requirements-dev.txt"])
        wiz_env = dict(os.environ)
    else:  # target
        site = bootstrap_env.pysite_dir(REPO)
        site.mkdir(parents=True, exist_ok=True)
        py = sys.executable
        _run([py, "-m", "pip", "install", "--upgrade", "--target", str(site),
              lwt, *LOCAL_PKGS])
        wiz_env = dict(os.environ)
        existing = wiz_env.get("PYTHONPATH", "")
        wiz_env["PYTHONPATH"] = str(site) + (os.pathsep + existing if existing else "")
        wiz_env["COS_LAUNCH_MODE"] = "target"

    print()
    return subprocess.run([py, "-m", "frontend.setup_wizard"], env=wiz_env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/install/test_install_mode.py -v`
Expected: PASS (4 tests). (Only the pure helpers are unit-tested; the pip/venv orchestration is exercised by the Task 6 smoke.)

- [ ] **Step 5: Commit**

```bash
git add install.py tests/install/test_install_mode.py
git commit -m "feat(install): install.py with venv->--target fallback orchestration"
```

---

### Task 3: The launch delegator

**Files:**
- Create: `launch.py`
- Test: `tests/install/test_launch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/install/test_launch.py`:

```python
import subprocess

import launch


def test_main_delegates_to_launcher_run_with_resolved_interp(monkeypatch, tmp_path):
    calls = {}

    def fake_resolve(repo, base=None):
        return "/usr/bin/python3", {"PYTHONPATH": "/site"}

    class FakeCompleted:
        returncode = 0

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["env"] = kw.get("env")
        calls["cwd"] = kw.get("cwd")
        return FakeCompleted()

    monkeypatch.setattr(launch.bootstrap_env, "resolve_launch", fake_resolve)
    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    rc = launch.main(["--flag"])
    assert rc == 0
    assert calls["cmd"] == ["/usr/bin/python3", "-m", "launcher.run", "--flag"]
    assert calls["env"]["PYTHONPATH"] == "/site"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/install/test_launch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'launch'`.

- [ ] **Step 3: Implement `launch.py`**

Create `launch.py`:

```python
"""Resolve the right interpreter and start the app (stdlib only).

Invoked by run.cmd / run.sh / run.ps1 under a base interpreter. Picks the venv
python if it runs, else a base interpreter + PYTHONPATH=<repo>/.pysite, then
delegates to ``launcher.run`` (which is unchanged and inherits the env)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import bootstrap_env

REPO = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    interp, env_overrides = bootstrap_env.resolve_launch(REPO)
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [interp, "-m", "launcher.run", *argv], cwd=str(REPO), env=env
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/install/test_launch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launch.py tests/install/test_launch.py
git commit -m "feat(launch): launch.py resolves interpreter and delegates to launcher.run"
```

---

### Task 4: Mode-aware launch hint in the wizard

**Files:**
- Modify: `frontend/setup_wizard.py:268-274`
- Test: `tests/frontend/test_setup_wizard.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/frontend/test_setup_wizard.py`:

```python
from frontend import setup_wizard


def test_launch_command_posix_uses_run_sh():
    cmd = setup_wizard.launch_command("/home/u/cos-notes", windows=False)
    assert cmd == "INSTALL_ROOT=/home/u/cos-notes ./run.sh"


def test_launch_command_windows_uses_run_cmd():
    cmd = setup_wizard.launch_command(r"C:\Users\u\cos-notes", windows=True)
    # cmd.exe sets env on a separate line, then runs the batch shim
    assert "run.cmd" in cmd
    assert r"set INSTALL_ROOT=C:\Users\u\cos-notes" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_setup_wizard.py -k launch_command -v`
Expected: FAIL — `AttributeError: module 'frontend.setup_wizard' has no attribute 'launch_command'`.

- [ ] **Step 3: Implement `launch_command` and wire it into `main`**

Add this function to `frontend/setup_wizard.py` (near the other module-level helpers, e.g. after `_choose_model`):

```python
def launch_command(install_root: str, *, windows: bool) -> str:
    """The recommended start command, using the run-shim so the right interpreter
    and PYTHONPATH are resolved (works in both venv and target mode)."""
    if windows:
        return f"set INSTALL_ROOT={install_root}\n  run.cmd"
    return f"INSTALL_ROOT={install_root} ./run.sh"
```

Then replace the launch-command block in `main` — currently `frontend/setup_wizard.py:268-274`:

```python
    # Use THIS interpreter (the venv's python that ran the wizard) — a bare
    # `python`/`python3` would pick the system interpreter, which doesn't have the
    # packages we just installed into the venv.
    run_cmd = f"INSTALL_ROOT={install_root} {sys.executable} -m launcher.run"
    print("\nDone. Start the assistant with:\n")
    print(f"  {run_cmd}")
    print("\nthen open http://127.0.0.1:8000/  — see docs/FIRST-RUN.md for daily use.")
```

with:

```python
    # Recommend the run-shim: it resolves the interpreter (venv python if it runs,
    # else a base interpreter + PYTHONPATH=.pysite for AppLocker-restricted boxes),
    # so the same instruction works regardless of install mode.
    run_cmd = launch_command(str(install_root), windows=(os.name == "nt"))
    print("\nDone. Start the assistant with:\n")
    print(f"  {run_cmd}")
    print("\nthen open http://127.0.0.1:8000/  — see docs/FIRST-RUN.md for daily use.")
```

(`os` and `sys` are already imported at the top of the file; the `sys.executable`-based command is fully replaced.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/frontend/test_setup_wizard.py -v`
Expected: PASS (the two new tests plus the existing wizard tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/setup_wizard.py tests/frontend/test_setup_wizard.py
git commit -m "feat(wizard): recommend run-shim launch command (mode-aware)"
```

---

### Task 5: Thin platform shims (setup.* / run.*)

**Files:**
- Modify: `setup.sh`, `setup.ps1`
- Create: `setup.cmd`, `run.sh`, `run.ps1`, `run.cmd`

No unit tests (shell/batch); a manual smoke covers them in Task 6. Each shim's only job: locate a base interpreter, `cd` to the repo, hand off to the Python module.

- [ ] **Step 1: Rewrite `setup.sh` as a thin shim**

Replace the entire contents of `setup.sh` with:

```bash
#!/usr/bin/env bash
# One-command setup (Linux/macOS): hand off to install.py under a base
# interpreter, which creates a venv (or falls back to a venv-less --target
# install if the venv's python is policy-blocked). Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.10+ and re-run (or set PYTHON=…)." >&2
  exit 1
fi
exec "$PY" install.py "$@"
```

- [ ] **Step 2: Rewrite `setup.ps1` as a thin shim**

Replace the entire contents of `setup.ps1` with:

```powershell
# One-command setup (Windows, PowerShell): hand off to install.py under a base
# interpreter. Prefer setup.cmd over setup.ps1 execution.
# Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.10+ and re-run (or set `$env:PYTHON)."
    exit 1
}
& $py install.py @args
exit $LASTEXITCODE
```

- [ ] **Step 3: Create `setup.cmd` (canonical Windows setup entry)**

Create `setup.cmd`:

```bat
@echo off
REM One-command setup (Windows, canonical). A batch file is immune to the
REM PowerShell execution-policy GPO axis and is not itself an .exe, so it runs
REM where setup.ps1 may be blocked. Delegates to install.py under a base python.
setlocal
cd /d "%~dp0"
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=py -3")
%PY% install.py %*
exit /b %ERRORLEVEL%
```

- [ ] **Step 4: Create `run.sh`**

Create `run.sh`:

```bash
#!/usr/bin/env bash
# Start the assistant (Linux/macOS): hand off to launch.py, which resolves the
# venv python (or a base interpreter + PYTHONPATH=.pysite) and starts the app.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.10+ (or set PYTHON=…)." >&2
  exit 1
fi
exec "$PY" launch.py "$@"
```

- [ ] **Step 5: Create `run.ps1`**

Create `run.ps1`:

```powershell
# Start the assistant (Windows, PowerShell). Prefer run.cmd on locked-down boxes.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.10+ (or set `$env:PYTHON)."
    exit 1
}
& $py launch.py @args
exit $LASTEXITCODE
```

- [ ] **Step 6: Create `run.cmd` (canonical Windows launch entry)**

Create `run.cmd`:

```bat
@echo off
REM Start the assistant (Windows, canonical). Batch entry — immune to the
REM PowerShell execution-policy GPO axis. Delegates to launch.py under a base python.
setlocal
cd /d "%~dp0"
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=py -3")
%PY% launch.py %*
exit /b %ERRORLEVEL%
```

- [ ] **Step 7: Make the shell shims executable + commit**

```bash
chmod +x setup.sh run.sh
git add setup.sh setup.ps1 setup.cmd run.sh run.ps1 run.cmd
git commit -m "feat(launcher): thin setup/run shims with .cmd canonical on Windows"
```

---

### Task 6: Docs, full suite, and target-mode smoke

**Files:**
- Modify: `docs/FIRST-RUN.md`, `launcher/README.md`

- [ ] **Step 1: Full unit suite green**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS — all existing tests plus the new `tests/install/` suite and the wizard `launch_command` tests.

- [ ] **Step 2: Target-mode smoke (forces the fallback on a clean tree)**

From a checkout with no `.venv`/`.pysite`, with `llm-wiki-tools` present as a sibling, run:

```bash
rm -rf .venv .pysite
SETUP_MODE=target PYTHON=python3 ./setup.sh </dev/null
```

Confirm, by inspection of the output and tree:
- `Install mode: target` is printed; **no `.venv`** is created.
- `.pysite/` exists and contains `frontend/`, `agenda/`, `presenter/`, `llm_wiki*`.
- The wizard runs (it imports `frontend`/`agenda` via the injected `PYTHONPATH`).
- The generated `opencode.json` MCP command starts with the base interpreter and uses the `-m` form (`["…/python3", "-m", "agenda.server"]`).

Then verify launch resolves target mode without executing any venv exe:

```bash
INSTALL_ROOT="$PWD/.smoke-root" python3 -c "import bootstrap_env, os; \
print(bootstrap_env.resolve_launch(os.getcwd()))"
```

Expected: prints `('…/python3', {'PYTHONPATH': '…/.pysite'})` (base interpreter + `.pysite`), confirming no venv python is selected.

- [ ] **Step 3: Sanity-check venv mode still works (default path)**

```bash
rm -rf .venv .pysite
PYTHON=python3 ./setup.sh </dev/null
```

Expected: `Install mode: venv`, `.venv/` created, editable installs succeed, wizard runs. (This is the unchanged developer path.)

- [ ] **Step 4: Update `docs/FIRST-RUN.md` and `launcher/README.md`**

In `docs/FIRST-RUN.md`, document the entry points and the two modes:
- Setup: `./setup.sh` (Linux/macOS) · `setup.cmd` (Windows, canonical) · `setup.ps1` (Windows, convenience — needs `-ExecutionPolicy Bypass`).
- Launch: `./run.sh` · `run.cmd` · `run.ps1` (same precedence note).
- The fallback: "Setup creates a venv by default. If the venv's `python.exe` can't run (e.g. AppLocker/SRP on a managed Windows box), setup automatically falls back to a venv-less install in `.pysite/` and launches with a base interpreter + `PYTHONPATH`. Force this with `SETUP_MODE=target`."
- Note the requirement the fallback assumes: a base `python`/`py` that *does* run from user space (Program Files install). If even that is blocked, you need an allow-listed interpreter or an IT AppLocker publisher rule — out of scope here.

In `launcher/README.md`, add the same two-mode note next to the existing `INSTALL_ROOT`/`python launcher/run.py` instructions, and point at the run-shims (`run.cmd`/`run.sh`) as the recommended entry now that they resolve the interpreter.

- [ ] **Step 5: Commit**

```bash
git add docs/FIRST-RUN.md launcher/README.md
git commit -m "docs: document venv->target fallback and the .cmd/.sh/.ps1 entry points"
```

---

## Self-Review

**Spec coverage:**
- Decision 1 (keep packages, drop exes — `--target` + base interp + `PYTHONPATH` + `python -m`) → Tasks 1–3 (`bootstrap_env.resolve_launch`, `install.py` target branch, `launch.py`). ✓
- Decision 2 (venv default + auto-fallback, with `SETUP_MODE=target` override + probe) → Task 2 (`try_make_venv` probe, `forced_target`, `choose_mode`). ✓
- Decision 3 (reject shiv) → recorded in spec; no zipapp task. ✓
- Decision 4 (thin shims over stdlib Python) → Tasks 1–3 (modules) + Task 5 (shims). ✓
- Decision 5 (`.cmd` canonical; don't rename `.ps1`) → Task 5 (`setup.cmd`/`run.cmd` created; `setup.ps1` kept, gutted to shim). ✓
- Decision 6 (launcher unchanged) → confirmed: `launcher/run.py` is not modified; `launch.py` only sets the interpreter + env it inherits. ✓
- Detection design (probe, not trust) → Task 2 `try_make_venv` (probes after create; removes partial venv on failure). ✓
- Interpreter recording into `opencode.json` → no code change needed; the wizard already passes `sys.executable` and `build_opencode_config` already emits `python -m` (noted in Refinements + verified by the Task 6 smoke). ✓
- Testing section (mode-selection mocked, run-shim resolution, target smoke) → Tasks 1–4 unit tests + Task 6 Steps 2–3 smoke. ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to" — every code step shows complete code; the only doc-prose steps (Task 6 Step 4) enumerate exactly what to write.

**Type/contract consistency:** `bootstrap_env.python_runs`, `venv_python`, `pysite_dir`, `resolve_launch(repo, base=None) -> (str, dict)` are used identically in `install.py` and `launch.py` and the tests. `install.choose_mode(*, forced_target, venv_ok) -> str` and `forced_target(env) -> bool` match their tests. `setup_wizard.launch_command(install_root, *, windows) -> str` matches its test and its call site (`windows=(os.name == "nt")`). The `COS_LAUNCH_MODE=target` marker is set by `install.py` for target mode; the wizard's command is mode-agnostic (the run-shim works in both modes) so the marker is informational only — no consumer depends on it, avoiding a dangling contract.

**Out of scope (unchanged):** base-interpreter-also-blocked case; MSI/service installer; signing; zipapp.
