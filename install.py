"""One-command setup with venv→target fallback (cross-platform, stdlib only).

Invoked by the thin shims (setup.cmd / setup.sh) under a *base* interpreter.
Tries to create and USE a venv; if the venv's python can't run (AppLocker/SRP)
or ``SETUP_MODE=target`` is set, falls back to a venv-less ``pip install --target
<repo>/.pysite`` and launches the wizard under the base interpreter with
PYTHONPATH set. See docs/adr/0008-venv-fallback-target-mode.md for the rationale.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import bootstrap_env

REPO = Path(__file__).resolve().parent
# Absolute, REPO-anchored so main() neither depends on nor mutates the cwd.
LOCAL_PKGS = [str(REPO / "agenda"), str(REPO / "frontend"), str(REPO / "presenter")]


def forced_target(env: dict) -> bool:
    """True iff the operator forced target mode via ``SETUP_MODE=target``."""
    return env.get("SETUP_MODE", "").strip().lower() == "target"


def choose_mode(*, force_target: bool, venv_ok: bool) -> str:
    """Pure mode decision. Forced target wins; else venv if the probe passed.

    ``force_target`` is named distinctly from the ``forced_target`` predicate so
    the two don't shadow each other (the predicate reads os.environ; this takes
    its result as a plain bool)."""
    if force_target:
        return "target"
    return "venv" if venv_ok else "target"


def _run(cmd: list[str], **kw) -> None:
    """Run *cmd*, echoing it; raise on non-zero so setup fails loudly."""
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def _lwt_path() -> str:
    """Resolve the required llm-wiki-tools sibling checkout (or exit with help)."""
    lwt = os.environ.get("LLM_WIKI_TOOLS") or str(REPO.parent / "llm-wiki-tools")
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
    from bootstrap_env import EnvSpec, preflight_env

    preflight_env([
        EnvSpec(
            "SETUP_MODE", default="",
            hint=(
                "force install mode: 'target' for AppLocker-restricted Windows "
                "boxes, empty to auto-detect (venv-or-target probe)"
            ),
        ),
        EnvSpec(
            "LLM_WIKI_TOOLS", default=str(REPO.parent / "llm-wiki-tools"),
            hint="absolute path to the llm-wiki-tools sibling checkout (required)",
        ),
    ])
    lwt = _lwt_path()
    forced = forced_target(os.environ)
    venv_ok = False if forced else try_make_venv()
    mode = choose_mode(force_target=forced, venv_ok=venv_ok)
    print(f"Install mode: {mode}")

    dev_reqs = [str(REPO / "agenda" / "requirements-dev.txt"),
                str(REPO / "frontend" / "requirements-dev.txt")]
    if mode == "venv":
        py = str(bootstrap_env.venv_python(REPO))
        _run([py, "-m", "pip", "install", "--upgrade", "pip"])
        _run([py, "-m", "pip", "install", "-e", lwt, *sum((["-e", p] for p in LOCAL_PKGS), [])])
        _run([py, "-m", "pip", "install", "-r", dev_reqs[0], "-r", dev_reqs[1]])
        wiz_env = dict(os.environ)
    else:  # target
        # Dev requirements are intentionally omitted here: target mode is for
        # locked-down end-user boxes, not the dev/test loop (use venv mode for that).
        site = bootstrap_env.pysite_dir(REPO)
        site.mkdir(parents=True, exist_ok=True)
        py = sys.executable
        _run([py, "-m", "pip", "install", "--upgrade", "--target", str(site),
              lwt, *LOCAL_PKGS])
        wiz_env = dict(os.environ)
        existing = wiz_env.get("PYTHONPATH", "")
        wiz_env["PYTHONPATH"] = str(site) + (os.pathsep + existing if existing else "")
        # COS_PYSITE tells the wizard to bake PYTHONPATH=.pysite into the
        # generated opencode.json MCP environments, so OpenCode's `python -m`
        # MCP children are self-sufficient (not reliant on inherited env).
        wiz_env["COS_PYSITE"] = str(site)

    print()
    # cwd=REPO so the wizard resolves `frontend`/`launcher` imports; all paths
    # above are REPO-anchored so main() no longer depends on (or mutates) the cwd.
    return subprocess.run(
        [py, "-m", "frontend.setup_wizard"], env=wiz_env, cwd=str(REPO)
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
