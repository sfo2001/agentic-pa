"""Cross-platform launcher: pre-flight, start OpenCode + the frontend, health-wait, shutdown."""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# A valid dotted Python module name (e.g. "agenda.server"). The MCP module is
# read from a machine-local opencode.json we generate, but validating it before
# interpolating into `python -c "import <module>"` keeps a hand-edited config
# from turning the preflight into an arbitrary-code-execution vector.
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def require_tools(names: list[str]) -> list[str]:
    return [n for n in names if shutil.which(n) is None]


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def no_git_ancestor(path: Path | str) -> bool:
    """True iff there is no `.git` at `path` or any ancestor — so OpenCode won't
    anchor the sandbox boundary to a git work-tree root (ADR-0005)."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return False
    return True


def isolated_env(install_root: Path | str, base: dict | None = None) -> dict:
    """Clean HOME/XDG (and Windows %APPDATA%/%LOCALAPPDATA%/%USERPROFILE%) pointed
    at <install_root>/oc-home, so the user's global ~/.config/opencode config and
    skill dirs do not merge into the agent. PATH is preserved.

    Also **strips every OPENCODE_* variable** from the inherited environment: the
    env is a *second* OpenCode config channel (notably `OPENCODE_CONFIG`, which
    OpenCode merges, not replaces). If the user has such a var set in their shell
    it would leak into — and could loosen — the sandboxed agent's permission
    policy. The HOME/XDG isolation closes the file channel; this closes the env
    channel (ADR-0005 / docs/decisions/D-opencode-sandbox.md §8). The caller adds
    back only the specific vars the agent needs (e.g. OPENCODE_SERVER_PASSWORD).

    Also **strips dynamic-linker injection variables** (``LD_PRELOAD``,
    ``LD_LIBRARY_PATH``, ``LD_AUDIT``, ``DYLD_INSERT_LIBRARIES``,
    ``DYLD_LIBRARY_PATH``) so a user with these set in their shell cannot inject
    native libraries into the sandboxed OpenCode process (Pattern Q — supply-chain
    risk, ADR-0005).
    """
    env = dict(os.environ if base is None else base)
    for key in [k for k in env if k.startswith("OPENCODE_")]:
        del env[key]
    for k in ("LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH"):
        env.pop(k, None)
    oc_home = str(Path(install_root) / "oc-home")
    env["HOME"] = oc_home
    env["USERPROFILE"] = oc_home
    env["XDG_CONFIG_HOME"] = str(Path(oc_home) / ".config")
    env["XDG_DATA_HOME"] = str(Path(oc_home) / ".local" / "share")
    env["XDG_STATE_HOME"] = str(Path(oc_home) / ".local" / "state")
    env["XDG_CACHE_HOME"] = str(Path(oc_home) / ".cache")
    env["APPDATA"] = str(Path(oc_home) / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(Path(oc_home) / "AppData" / "Local")
    return env


def notes_mcp_command(install_root: Path | str) -> list[str] | None:
    """Read the full ``mcp.notes.command`` argv from <install_root>/opencode.json.

    Returns the command list (e.g. ``[python, "-m", "agenda.server"]``), or None
    if the config is missing/malformed or the command is empty."""
    try:
        cfg = json.loads((Path(install_root) / "opencode.json").read_text(encoding="utf-8"))
        cmd = cfg["mcp"]["notes"]["command"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return cmd if isinstance(cmd, list) and cmd else None


def agenda_server_path(install_root: Path | str) -> str | None:
    """First token of the notes MCP command — the interpreter for the
    ``python -m`` form, or a bare exe path for the legacy form. None if the
    config is missing/malformed. Kept as the stable command[0] accessor."""
    cmd = notes_mcp_command(install_root)
    return cmd[0] if cmd else None


def _python_m_module(cmd: list[str]) -> str | None:
    """Module name if *cmd* is a ``<python> -m <module>`` invocation, else None.

    Localizes the one place that knows the ``-m`` argv shape, so the preflight
    reads as intent ("is this a python -m command?") rather than index math."""
    if len(cmd) >= 3 and cmd[1] == "-m":
        return cmd[2]
    return None


def _module_importable(interpreter: str, module: str) -> bool:
    """True iff *interpreter* can ``import <module>`` — validates a ``python -m``
    MCP command will actually start (catches a broken/missing install early).

    Rejects a malformed module name before spawning, so a tampered opencode.json
    can't smuggle code into the ``-c`` string (fail closed)."""
    # fullmatch (NOT re.match) is load-bearing: match() anchors only the start, so
    # ``$`` would accept "agenda.server\nimport os" — fullmatch rejects any
    # trailing payload. Do not weaken this to match().
    if not _MODULE_NAME_RE.fullmatch(module):
        return False
    try:
        return subprocess.run(
            [interpreter, "-c", f"import {module}"],
            capture_output=True, timeout=10,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        # SubprocessError covers TimeoutExpired (a hung import) — fail closed.
        return False


def _wait_health(url: str, timeout: float = 30.0, password: str | None = None) -> bool:
    headers = {}
    if password:
        token = base64.b64encode(f"opencode:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _port_parser(v: str) -> int:
    """Validate *v* is an integer in the valid port range 1–65535."""
    p = int(v)
    if not 1 <= p <= 65535:
        raise ValueError(f"port must be 1–65535, got {p}")
    return p


def _restrict_write_env() -> bool | None:
    """Parse RESTRICT_WRITE: 1/true/yes → True, 0/false/no → False, unset/'' → None."""
    raw = os.environ.get("RESTRICT_WRITE", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _apply_restrict_write(install_root: Path | str) -> None:
    """Patch opencode.json's write/edit permission from RESTRICT_WRITE when set;
    leave the setup-baked value when unset.

    Fail-closed: when ``RESTRICT_WRITE=1`` is explicitly requested but the config
    cannot be read, ``RuntimeError`` is raised so the launch aborts loudly rather
    than silently leaving the agent unrestricted (audit finding C-3).
    """
    want = _restrict_write_env()
    if want is None:
        return
    cfg_path = Path(install_root) / "opencode.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if want:
            raise RuntimeError(
                "RESTRICT_WRITE=1 but opencode.json is missing or malformed"
            ) from None
        return
    val = "deny" if want else "allow"
    for block in (cfg.get("permission"),
                  cfg.get("agent", {}).get("workspace-assistant", {}).get("permission")):
        if isinstance(block, dict):
            block["write"] = val
            block["edit"] = val
    # Atomic write via sibling .tmp + os.replace so a crash mid-write never
    # leaves a truncated opencode.json (which OpenCode would silently accept
    # as valid and start with an empty config, defeating RESTRICT_WRITE).
    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cfg_path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _ensure_present_notes_root(install_root: Path | str) -> None:
    """Patch ``opencode.json`` so the present MCP server always gets ``NOTES_ROOT``.

    Migration for pre-propose-mcp-tool configs that lack the environment block.
    Uses atomic write via ``.tmp`` + ``os.replace`` (same pattern as
    ``_apply_restrict_write``) so a crash never leaves a truncated config.
    """
    cfg_path = Path(install_root) / "opencode.json"
    if not cfg_path.is_file():
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    present = cfg.get("mcp", {}).get("present")
    if not isinstance(present, dict):
        return
    env = present.setdefault("environment", {})
    if "NOTES_ROOT" in env:
        return  # already migrated
    env["NOTES_ROOT"] = str(install_root)
    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cfg_path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def main() -> int:
    from bootstrap_env import EnvSpec, preflight_env

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
        EnvSpec(
            "OPENCODE_PORT", default="4096", parser=_port_parser,
            hint="port the opencode server listens on (must be an integer, 1–65535)",
        ),
        EnvSpec(
            "WEB_PORT", default="8000", parser=_port_parser,
            hint="port the FastAPI frontend listens on (must be an integer, 1–65535)",
        ),
        EnvSpec(
            "RESTRICT_WRITE", default="",
            hint="restrict the agent to tool-based edits (deny write/edit): "
                 "1/0; empty keeps the setup-baked default",
        ),
    ])
    install_root = Path(os.environ.get("INSTALL_ROOT") or str(Path.home() / "cos-notes")).resolve()
    workspace = install_root / "workspace"
    git_dir = install_root / "notes.git"
    oc_port = int(os.environ.get("OPENCODE_PORT") or "4096")
    web_port = int(os.environ.get("WEB_PORT") or "8000")

    # ---- pre-flight -------------------------------------------------------
    missing = require_tools(["opencode"])
    if missing:
        print(f"ERROR: missing required tools on PATH: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not workspace.is_dir():
        print(f"ERROR: {workspace} not found — run bootstrap first.", file=sys.stderr)
        return 2
    if not git_dir.is_dir():
        print(f"ERROR: notes git-dir {git_dir} not found — run bootstrap first.", file=sys.stderr)
        return 2
    if not no_git_ancestor(workspace):
        print(f"ERROR: a .git exists at or above {workspace}; this would expand the agent's "
              "sandbox boundary to the git work-tree root (ADR-0005). Install outside any git repo.",
              file=sys.stderr)
        return 2
    notes_cmd = notes_mcp_command(install_root)
    if notes_cmd is None:
        print(f"ERROR: could not read mcp.notes.command from {install_root/'opencode.json'} "
              "— run bootstrap first.", file=sys.stderr)
        return 2
    interpreter = notes_cmd[0]
    if not (Path(interpreter).is_file() or shutil.which(interpreter)):
        print(f"ERROR: MCP notes command interpreter '{interpreter}' not found "
              "(configured in opencode.json). Re-run bootstrap.", file=sys.stderr)
        return 2
    # For the `python -m <module>` form, confirm the module imports under that
    # interpreter — otherwise a broken/missing agenda install would only surface
    # later when OpenCode spawns the MCP server.
    module = _python_m_module(notes_cmd)
    if module and not _module_importable(interpreter, module):
        print(f"ERROR: MCP notes module '{module}' is not importable by "
              f"'{interpreter}'; the agent's deterministic agenda tools would fail. "
              "Reinstall the agenda package and re-run bootstrap.", file=sys.stderr)
        return 2
    # Deliberately NOT hard-gating the `present` MCP module here. Notes is
    # load-bearing (the agent's deterministic agenda tools) so a broken install
    # must abort; the presentation pane is optional and degrades gracefully
    # (ADR-0006) — OpenCode runs without it, and the wizard's check_environment
    # already warns at install time if `presenter` isn't importable. Adding a
    # second per-launch subprocess probe for an optional component isn't worth it.
    # NOTE: ports are checked then bound below — a benign check-then-bind (TOCTOU)
    # race exists, acceptable for a single-user localhost deployment.
    for p in (oc_port, web_port):
        if not port_is_free(p):
            print(f"ERROR: port {p} is in use; free it or set OPENCODE_PORT/WEB_PORT.", file=sys.stderr)
            return 2

    # Patch write/edit perms from RESTRICT_WRITE (1/0). When unset, the
    # setup-baked default in opencode.json is left in place. Done here so the
    # patch lands before OpenCode reads the file at startup.
    _apply_restrict_write(install_root)

    # Migration: ensure the present MCP server's environment block always has
    # NOTES_ROOT (PR #propose-mcp-tool added it to the config builder; existing
    # opencode.json files generated before that change lack it). Without this,
    # the present server would raise a RuntimeError on startup.
    _ensure_present_notes_root(install_root)

    # A per-run random password authenticates the localhost OpenCode server so
    # other local processes/users cannot drive the sandboxed agent (design §8).
    oc_password = secrets.token_urlsafe(32)

    procs: list[subprocess.Popen[bytes]] = []
    oc_log = None
    try:
        oc_env = isolated_env(install_root)
        oc_env["OPENCODE_SERVER_PASSWORD"] = oc_password
        Path(oc_env["HOME"]).mkdir(parents=True, exist_ok=True)
        # Capture OpenCode's output to a log file (instead of interleaving it with
        # the launcher's stdout).
        oc_log = open(install_root / "opencode.log", "ab")
        procs.append(subprocess.Popen(
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(oc_port)],
            cwd=str(workspace), env=oc_env, stdout=oc_log, stderr=oc_log))
        if not _wait_health(f"http://127.0.0.1:{oc_port}/global/health", password=oc_password):
            print("ERROR: OpenCode server did not become healthy.", file=sys.stderr)
            return 3
        # Frontend env: explicit overrides win over any inherited values. The
        # frontend (our trusted code) authenticates to OpenCode with the password.
        env = {**os.environ,
               "OPENCODE_BASE_URL": f"http://127.0.0.1:{oc_port}",
               "OPENCODE_SERVER_PASSWORD": oc_password,
               "NOTES_ROOT": str(workspace),
               "NOTES_GIT_DIR": str(git_dir)}
        # uvicorn runs from the active interpreter's venv; `frontend` must be
        # importable there (the install does `pip install -e ./frontend`).
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "--factory", "frontend.app:build_default_app",
             "--host", "127.0.0.1", "--port", str(web_port)], env=env))
        if not _wait_health(f"http://127.0.0.1:{web_port}/health"):
            print("ERROR: frontend did not become healthy.", file=sys.stderr)
            return 3
        print(f"Ready — open http://127.0.0.1:{web_port}/  (Ctrl+C to stop)")

        def _stop(*_):
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _stop)
        # SIGTERM (docker stop / systemd stop / kill) must also run the finally
        # block so both child processes are terminated, not orphaned.
        with contextlib.suppress(ValueError, AttributeError):
            signal.signal(signal.SIGTERM, _stop)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        for proc in reversed(procs):
            proc.terminate()
        for proc in reversed(procs):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if oc_log is not None:
            oc_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
