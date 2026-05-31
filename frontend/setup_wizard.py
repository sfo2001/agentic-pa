"""Interactive setup wizard for the Chief-of-Staff Notes assistant.

Run via the cross-platform wrappers (`./setup.sh` or `setup.ps1`), which create a
venv and install the packages first, or directly with `python -m frontend.setup_wizard`.

It (1) checks the Python environment and external tools and gives actionable advice
for anything missing, (2) collects the model endpoint + model (offering a pick-list
fetched from the endpoint), the install location, and ports, validating each, then
(3) writes the install directory via ``frontend.bootstrap.init_install`` and prints
the command to start it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

# Runtime import-name -> the thing to install if it's missing.
_REQUIRED_RUNTIME = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "multipart": "python-multipart",
    "markitdown": "markitdown",
    "mcp": "mcp",
    "yaml": "pyyaml",
}

_INSTALL_HINT = (
    "      pip install -e ./agenda -e ./frontend\n"
    "      pip install -r agenda/requirements-dev.txt -r frontend/requirements-dev.txt"
)


def check_environment() -> tuple[list[str], list[str]]:
    """Inspect the runtime. Returns ``(blocking, warnings)`` lists of messages.

    Blocking = setup cannot proceed (wrong Python, packages not importable).
    Warnings = setup can write the install, but running it will fail until fixed
    (e.g. missing runtime deps, no `opencode` on PATH).
    """
    blocking: list[str] = []
    warnings: list[str] = []

    if sys.version_info < (3, 12):  # noqa: UP036 — runtime guard; the wizard may be run by an older interpreter
        have = ".".join(map(str, sys.version_info[:3]))
        blocking.append(f"Python 3.12+ is required — this interpreter is {have}.")

    # The wizard's own packages must be importable to bootstrap an install.
    for pkg in ("frontend", "agenda"):
        if importlib.util.find_spec(pkg) is None:
            blocking.append(
                f"The `{pkg}` package isn't importable. Activate your venv and run:\n"
                f"      pip install -e ./{pkg}"
            )

    missing = sorted(
        pip for mod, pip in _REQUIRED_RUNTIME.items() if importlib.util.find_spec(mod) is None
    )
    if missing:
        warnings.append(
            "Missing Python packages needed to RUN: " + ", ".join(missing) + "\n"
            "   Install everything with:\n" + _INSTALL_HINT
        )

    if shutil.which("opencode") is None:
        warnings.append(
            "`opencode` is not on PATH — it's needed to run the assistant (not to set "
            "it up). Install it from https://opencode.ai and re-check."
        )
    if importlib.util.find_spec("agenda") is not None and shutil.which("agenda-server") is None:
        warnings.append(
            "`agenda-server` is not on PATH — it should appear after `pip install -e "
            "./agenda` in your active venv. Re-install the agenda package."
        )
    return blocking, warnings


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or (default or "")


def _yes(label: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    ans = _prompt(f"{label} ({d})").lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def fetch_models(endpoint: str) -> list[str]:
    """List model ids from an OpenAI-compatible ``/models`` endpoint ([] on failure)."""
    url = endpoint.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.load(r)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    return [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]


def _choose_model(endpoint: str) -> str:
    models = fetch_models(endpoint)
    if not models:
        print("  (couldn't list models from the endpoint — enter the id manually)")
        return _prompt("Model id")
    print("  Available models:")
    for i, m in enumerate(models, 1):
        print(f"    {i:2}. {m}")
    while True:
        sel = _prompt("Pick a model (number, or type an id)")
        if sel.isdigit() and 1 <= int(sel) <= len(models):
            return models[int(sel) - 1]
        if sel:
            return sel


def main() -> int:
    print("=== Chief-of-Staff Notes — setup ===\n")

    blocking, warnings = check_environment()
    if blocking:
        print("Cannot continue — fix these first:\n")
        for b in blocking:
            print("  ✗ " + b)
        return 2
    if warnings:
        print("Heads-up (you can still write the install now):\n")
        for w in warnings:
            print("  ! " + w)
        print()
        if not _yes("Continue with setup anyway?", default=True):
            return 1
    else:
        print("Environment looks good (Python 3.12+, packages, opencode, agenda-server).\n")

    # Safe to import now that `frontend`/`agenda` are confirmed importable.
    from frontend.bootstrap import init_install
    from launcher.run import no_git_ancestor

    endpoint = _prompt("Model endpoint (OpenAI-compatible)", "http://localhost:11434/v1")
    model_id = _choose_model(endpoint)

    default_root = str(Path.home() / "cos-notes")
    while True:
        install_root = Path(_prompt("Install location", default_root)).expanduser()
        if no_git_ancestor(install_root):
            break
        print(
            f"  ! {install_root} is inside a git repository — the agent's sandbox boundary\n"
            "    would expand to that repo's root (ADR-0005). Choose a location outside any\n"
            "    git repo, e.g. ~/cos-notes."
        )

    agenda_server = shutil.which("agenda-server") or str(Path(sys.executable).parent / "agenda-server")

    print(f"\nWriting install to {install_root} …")
    layout = init_install(
        install_root,
        model_endpoint=endpoint,
        model_id=model_id,
        agenda_server=agenda_server,
    )
    print(f"  ✓ workspace:    {layout['workspace']}")
    print(f"  ✓ config:       {layout['opencode_json']}  (machine-specific, not committed)")
    print(f"  ✓ notes git:    {layout['git_dir']}")

    # Use THIS interpreter (the venv's python that ran the wizard) — a bare
    # `python`/`python3` would pick the system interpreter, which doesn't have the
    # packages we just installed into the venv.
    run_cmd = f"INSTALL_ROOT={install_root} {sys.executable} -m launcher.run"
    print("\nDone. Start the assistant with:\n")
    print(f"  {run_cmd}")
    print("\nthen open http://127.0.0.1:8000/  — see docs/FIRST-RUN.md for daily use.")
    if shutil.which("opencode") is None:
        print("\n(Reminder: install `opencode` before starting — https://opencode.ai)")

    if _yes("\nStart the assistant now?", default=False):
        os.environ["INSTALL_ROOT"] = str(install_root)
        from launcher.run import main as launcher_main
        return launcher_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
