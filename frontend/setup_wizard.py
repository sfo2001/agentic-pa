"""Interactive setup wizard for the Chief-of-Staff Notes assistant.

Run via the cross-platform wrappers (`./setup.sh` or `setup.cmd`), which create a
venv and install the packages first, or directly with `python -m frontend.setup_wizard`.

It (1) checks the Python environment and external tools and gives actionable advice
for anything missing, (2) collects the model endpoint + model (offering a pick-list
fetched from the endpoint), the install location, and ports, validating each, then
(3) writes the install directory via ``frontend.bootstrap.init_install`` and prints
the command to start it.
"""
from __future__ import annotations

import getpass
import importlib.util
import json
import os
import shutil
import sys
import urllib.error
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

    if sys.version_info < (3, 10):  # noqa: UP036 — runtime guard; the wizard may be run by an older interpreter
        have = ".".join(map(str, sys.version_info[:3]))
        blocking.append(f"Python 3.10+ is required — this interpreter is {have}.")

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
    # The MCP servers run as `python -m agenda.server` / `python -m presenter.server`
    # (not via console-script exes), so what matters is that the modules import —
    # not that an `agenda-server` exe is on PATH. `agenda` is already covered by the
    # blocking import check above; warn if `presenter` (the presentation pane) is
    # missing so the present MCP server doesn't fail at runtime.
    if importlib.util.find_spec("presenter") is None:
        warnings.append(
            "`presenter` isn't importable — the presentation-pane MCP server "
            "(`python -m presenter.server`) will fail to start. Run "
            "`pip install -e ./presenter` in your active venv."
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


def _secret(label: str) -> str:
    """Prompt for a secret WITHOUT echoing it to the terminal or scrollback."""
    try:
        return getpass.getpass(f"{label}: ").strip()
    except (EOFError, getpass.GetPassWarning):
        return ""


def probe_endpoint(endpoint: str, api_key: str | None = None) -> tuple[str, list[str]]:
    """Probe an OpenAI-compatible ``/models`` endpoint.

    Returns ``(status, models)`` where status is:
      * ``"ok"``          — reachable and authorized; ``models`` is the id list.
      * ``"auth"``        — reachable but the endpoint demands a key (HTTP 401/403).
      * ``"unreachable"`` — no response, a connection error, or another HTTP error.

    ``api_key``, when given, is sent as a ``Bearer`` token so a key supplied by
    the user can be validated before the install is written.
    """
    url = endpoint.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return ("auth", []) if e.code in (401, 403) else ("unreachable", [])
    except Exception:
        return ("unreachable", [])
    models = (
        [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        if isinstance(data, dict)
        else []
    )
    return ("ok", models)


def fetch_models(endpoint: str, api_key: str | None = None) -> list[str]:
    """List model ids from an OpenAI-compatible ``/models`` endpoint ([] on failure)."""
    return probe_endpoint(endpoint, api_key)[1]


def _is_plaintext_remote(endpoint: str) -> bool:
    """True if *endpoint* sends a key in the clear: http:// to a non-loopback host."""
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").lower()
    return host not in ("localhost", "127.0.0.1", "::1", "")


def _collect_endpoint(default: str) -> tuple[str, str | None]:
    """Prompt for the endpoint, probe it, and obtain a key if one is required.

    Loops until the endpoint answers (``ok``) or the user chooses to proceed
    without resolving it. Returns ``(endpoint, api_key)``; ``api_key`` is
    ``None`` for keyless/local servers.
    """
    endpoint = _prompt("Model endpoint (OpenAI-compatible)", default)
    api_key: str | None = None
    while True:
        status, _models = probe_endpoint(endpoint, api_key)
        if status == "ok":
            if api_key and _is_plaintext_remote(endpoint):
                print(
                    "  ! Warning: the key will be sent unencrypted over http:// to a\n"
                    "    non-local host. Prefer an https:// endpoint."
                )
            return endpoint, api_key
        if status == "auth":
            print("  This endpoint requires authentication (HTTP 401/403).")
            entered = _secret("API key (input hidden)")
            if not entered:
                print("  (no key entered — continuing; the model list may be unavailable)")
                return endpoint, api_key
            api_key = entered
            continue
        # unreachable
        print(f"  ! Couldn't reach {endpoint} (no response, timeout, or error).")
        if _yes("Re-enter the endpoint?", default=True):
            endpoint = _prompt("Model endpoint (OpenAI-compatible)", endpoint)
            api_key = None
            continue
        return endpoint, api_key


def _choose_model(endpoint: str, api_key: str | None = None) -> str:
    models = fetch_models(endpoint, api_key)
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


def launch_command(install_root: str, *, windows: bool) -> str:
    """The recommended start command, using the run-shim so the right interpreter
    and PYTHONPATH are resolved (works in both venv and target mode)."""
    if windows:
        return f"set INSTALL_ROOT={install_root}\n  run.cmd"
    return f"INSTALL_ROOT={install_root} ./run.sh"


def main() -> int:
    from bootstrap_env import EnvSpec, preflight_env

    preflight_env([
        EnvSpec(
            "COS_PYSITE", default="",
            hint=(
                "internal handoff from install.py in target mode: absolute path "
                "to <repo>/.pysite, baked into MCP servers' PYTHONPATH"
            ),
        ),
    ])
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
        print("Environment looks good (Python 3.10+, packages, opencode, agenda/presenter).\n")

    # Safe to import now that `frontend`/`agenda` are confirmed importable.
    from frontend.bootstrap import init_install
    from launcher.run import no_git_ancestor

    endpoint, api_key = _collect_endpoint("http://localhost:11434/v1")
    model_id = _choose_model(endpoint, api_key)

    restrict_write = _yes(
        "Restrict the assistant to tool-based edits? "
        "(recommended for smaller/local models)", default=True)

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

    print(f"\nWriting install to {install_root} …")
    # Spawn the MCP servers with THIS interpreter via `python -m` (see
    # frontend.config). Using sys.executable avoids resolving a console-script
    # path — robust on Windows where the .exe lives in a Scripts dir that may be
    # off PATH (base/`--user` installs) or blocked by AppLocker/SRP.
    # In target/venv-less mode install.py exports COS_PYSITE (the absolute
    # .pysite path); pass it through so the generated opencode.json bakes
    # PYTHONPATH into the MCP servers, making OpenCode's `python -m` children
    # self-sufficient instead of relying on inherited env. Unset in venv mode.
    # COS_PYSITE is an internal handoff from install.py (the absolute .pysite
    # path). Ignore a malformed/relative value rather than baking an arbitrary
    # PYTHONPATH into the generated opencode.json.
    cos_pysite = os.environ.get("COS_PYSITE") or None
    if cos_pysite and not Path(cos_pysite).is_absolute():
        cos_pysite = None
    layout = init_install(
        install_root,
        model_endpoint=endpoint,
        model_id=model_id,
        python_executable=sys.executable,
        api_key=api_key,
        mcp_pythonpath=cos_pysite,
        restrict_write=restrict_write,
    )
    print(f"  ✓ workspace:    {layout['workspace']}")
    print(f"  ✓ config:       {layout['opencode_json']}  (machine-specific, not committed)")
    print(f"  ✓ notes git:    {layout['git_dir']}")
    if layout.get("auth_json"):
        print(f"  ✓ api key:      {layout['auth_json']}  (OpenCode auth.json, mode 600)")

    # Recommend the run-shim: it resolves the interpreter (venv python if it runs,
    # else a base interpreter + PYTHONPATH=.pysite for AppLocker-restricted boxes),
    # so the same instruction works regardless of install mode.
    run_cmd = launch_command(str(install_root), windows=(os.name == "nt"))
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
