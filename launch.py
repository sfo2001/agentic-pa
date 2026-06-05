"""Resolve the right interpreter and start the app (stdlib only).

Invoked by run.cmd / run.sh under a base interpreter. Picks the venv
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
    from bootstrap_env import EnvSpec, preflight_env

    argv = list(sys.argv[1:] if argv is None else argv)
    # INSTALL_ROOT is surfaced here only for an early, friendly hint at this
    # entry point. The authoritative consumer/validator is `launcher/run.py`
    # (which this delegates to and which re-runs the preflight); launch.py
    # itself never reads INSTALL_ROOT — it forwards the whole os.environ to the
    # launcher subprocess below.
    preflight_env([
        EnvSpec(
            "INSTALL_ROOT",
            default=str(Path.home() / "cos-notes"),
            hint=(
                "install root created by setup.cmd/setup.sh; default "
                "$HOME/cos-notes if unset, but the launcher will error if "
                "workspace/ and notes.git/ are missing"
            ),
        ),
    ])
    interp, env_overrides = bootstrap_env.resolve_launch(REPO)
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [interp, "-m", "launcher.run", *argv], cwd=str(REPO), env=env
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
