"""Stdlib-only helpers shared by install.py and launch.py.

Two roots, kept distinct: the *package site* lives with the repo checkout
(``<repo>/.venv`` in venv mode, ``<repo>/.pysite`` in target mode); the *install
root* (``~/cos-notes``) holds runtime data and is not this module's concern.

The target mode exists for locked-down Windows where AppLocker/SRP blocks
executing the venv's ``python.exe`` — we never run a venv exe, only a base
interpreter + ``PYTHONPATH`` pointed at ``.pysite`` (see
docs/adr/0008-venv-fallback-target-mode.md).

The ``EnvSpec`` / ``preflight_env`` pair is a quiet-by-default configuration
preflight: each entry point declares the env vars it cares about, and on any
unset / unparseable value a unified table + per-shell ``how to set`` hint is
printed to stderr. See ``docs/adr/0010-env-var-preflight-layer.md``.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
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


# ── env-var preflight layer (ADR-0010) ────────────────────────────────────────


@dataclass(frozen=True)
class EnvSpec:
    """One env-var entry in the preflight table.

    Attributes:
        name: Environment variable name (e.g. ``"INSTALL_ROOT"``).
        default: Value used when the var is unset/empty. ``None`` means the
            var is required when unset. Required+unset → exit 2.
        parser: Optional ``str -> object`` validator. Called on the resolved
            value (env value or default). Raises ``ValueError``/``TypeError``
            on bad input; required+bad → exit 2, optional+bad → warn.
        required: ``True`` ⇒ an unset/empty value is fatal (exit 2). ``False``
            ⇒ the value is missing-but-tolerable (warn and continue).
        hint: Optional one-line context appended to the ``! VAR:`` warning
            (e.g. "set INSTALL_ROOT to the install root created by setup").
        secret: If ``True``, a value that parsed OK is masked in the table
            output (e.g. an API key). Failure states still show the raw value
            because hiding a bad secret would defeat the purpose.
    """
    name: str
    default: str | None = None
    parser: Callable[[str], object] | None = None
    required: bool = False
    hint: str = ""
    secret: bool = False


def _mask_secret(value: str) -> str:
    """Return a masked representation suitable for stderr / log output.

    Empty values render as ``""``; very short ones as ``"****"``; longer
    values as first-2 + ``****`` + last-2. This is presentation, not crypto."""
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


def _shell_hints(name: str, value: str) -> list[str]:
    """Return per-shell ``set VAR=...`` lines, in the order most users read.

    On Windows: cmd, then PowerShell, then bash (covers WSL / git-bash users).
    On POSIX: bash first, then PowerShell (Core) as the secondary. Each line
    is quoted via ``shlex.quote`` so values with spaces / metacharacters round-trip."""
    quoted = shlex.quote(value)
    if os.name == "nt":
        return [
            f"  → cmd:        set {name}={value}",
            f"  → powershell: $env:{name} = {quoted}",
            f"  → bash:       export {name}={quoted}",
        ]
    return [
        f"  → bash:       export {name}={quoted}",
        f"  → powershell: $env:{name} = {quoted}",
    ]


def preflight_env(specs: list[EnvSpec]) -> None:
    """Validate each spec against ``os.environ``. Quiet on success.

    For each spec, in order:
      1. Read the raw env value. Treat empty string as unset.
      2. If unset and ``default`` is ``None``: required → fatal,
         optional → warn-and-continue.
      3. Otherwise resolve to env value (preferred) or ``default``.
      4. Run ``parser`` if present. ``ValueError``/``TypeError`` ⇒
         required → fatal, optional → warn-and-continue.

    Fatal cases ``sys.exit(2)``; warn cases print the table + hints and return.
    No output at all when every spec passes — keep the happy path silent.
    """
    # Each row: (spec, status, value, source)
    #   status ∈ {"ok", "required-unset", "optional-unset", "parse-fail"}
    rows: list[tuple[EnvSpec, str, str, str]] = []
    has_issue = False
    has_fatal = False

    for spec in specs:
        raw = os.environ.get(spec.name)
        is_unset = raw is None or raw == ""

        if is_unset and spec.default is None:
            if spec.required:
                has_issue = True
                has_fatal = True
                rows.append((spec, "required-unset", "(unset)", "REQUIRED — must be set"))
            else:
                has_issue = True
                rows.append((spec, "optional-unset", "(unset)", "optional, not set"))
            continue

        if is_unset:
            # spec.default is not None here — the (unset, default=None) case
            # was already filtered out via `continue` above.
            value = spec.default or ""
            source = "(default)"
        else:
            # !is_unset means raw is a non-empty string; pin the type for mypy.
            assert raw is not None
            value = raw
            shell_marker = f"%{spec.name}%" if os.name == "nt" else f"${spec.name}"
            source = f"from {shell_marker}"

        if spec.parser is not None:
            try:
                spec.parser(value)
            except (ValueError, TypeError) as exc:
                has_issue = True
                if spec.required:
                    has_fatal = True
                rows.append((spec, "parse-fail", value, f"PARSE FAILED: {exc}"))
                continue

        rows.append((spec, "ok", value, source))

    if not has_issue:
        return  # quiet on success

    # Loud path: one table for context, then per-issue hints.
    label = "issue" if has_issue and not has_fatal else "fatal issue"
    print(f"Environment ({label}):", file=sys.stderr)
    for spec, status, value, source in rows:
        display = value
        if status == "ok" and spec.secret:
            display = _mask_secret(value)
        print(f"  {spec.name:<18}= {display:<48} ({source})", file=sys.stderr)
    print(file=sys.stderr)

    for spec, status, _value, source in rows:
        if status == "ok":
            continue
        print(f"! {spec.name}: {source}", file=sys.stderr)
        if spec.hint:
            print(f"  {spec.hint}", file=sys.stderr)
        suggested = spec.default if spec.default is not None else "<value>"
        for line in _shell_hints(spec.name, suggested):
            print(line, file=sys.stderr)
        print(file=sys.stderr)

    if has_fatal:
        sys.exit(2)
