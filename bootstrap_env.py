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
