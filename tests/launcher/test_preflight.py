import json
import socket
import subprocess

from launcher.run import (
    agenda_server_path,
    isolated_env,
    no_git_ancestor,
    port_is_free,
    require_tools,
)


def test_port_is_free_detects_bound_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    bound = s.getsockname()[1]
    try:
        assert port_is_free(bound) is False
    finally:
        s.close()
    # the just-closed port is now free
    assert port_is_free(bound) is True


def test_require_tools_reports_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    missing = require_tools(["opencode", "bun"])
    assert set(missing) == {"opencode", "bun"}


def test_no_git_ancestor_true_when_clean(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    assert no_git_ancestor(work) is True


def test_no_git_ancestor_false_when_parent_is_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    work = tmp_path / "workspace"
    work.mkdir()
    assert no_git_ancestor(work) is False


def test_isolated_env_overrides_home_and_xdg(tmp_path):
    env = isolated_env(tmp_path, base={"PATH": "/usr/bin", "HOME": "/home/real"})
    oc_home = str(tmp_path / "oc-home")
    assert env["HOME"] == oc_home
    assert env["XDG_CONFIG_HOME"].startswith(oc_home)
    assert env["XDG_DATA_HOME"].startswith(oc_home)
    assert env["APPDATA"].startswith(oc_home)
    assert env["LOCALAPPDATA"].startswith(oc_home)
    assert env["XDG_STATE_HOME"].startswith(oc_home)
    assert env["XDG_CACHE_HOME"].startswith(oc_home)
    assert env["USERPROFILE"] == oc_home
    assert env["PATH"] == "/usr/bin"


# ── BH-24: Pattern I — isolated_env() must strip LD_PRELOAD ─────────────────


def test_bh24_isolated_env_strips_ld_preload(tmp_path):
    """BH-24: isolated_env() strips ``OPENCODE_*`` vars but does NOT strip
    ``LD_PRELOAD``, ``LD_LIBRARY_PATH``, or other dynamic-linker env vars that
    could inject code into the sandboxed OpenCode process (Pattern Q —
    supply-chain risk).

    A user with ``LD_PRELOAD=/home/user/hack.so`` in their shell would have
    that library loaded into the sandboxed process, breaking confinement."""
    env = isolated_env(
        tmp_path,
        base={
            "PATH": "/usr/bin",
            "LD_PRELOAD": "/home/user/hack.so",
            "LD_LIBRARY_PATH": "/home/user/lib",
        },
    )
    # LD_PRELOAD should be stripped (security boundary)
    assert "LD_PRELOAD" not in env, (
        "LD_PRELOAD bleeds into sandboxed OpenCode process"
    )


def test_isolated_env_strips_opencode_vars(tmp_path):
    # The env is a second OpenCode config channel (OPENCODE_CONFIG merges); it
    # must not leak from the user's shell into the sandboxed agent (ADR-0005).
    env = isolated_env(
        tmp_path,
        base={
            "PATH": "/usr/bin",
            "OPENCODE_CONFIG": "/home/u/.config/opencode/opencode.json",
            "OPENCODE_DISABLE_PERMISSIONS": "1",
            "OPENCODE_SERVER_PASSWORD": "leaked",
        },
    )
    assert "OPENCODE_CONFIG" not in env
    assert "OPENCODE_DISABLE_PERMISSIONS" not in env
    assert "OPENCODE_SERVER_PASSWORD" not in env  # caller re-adds only what's needed
    assert env["PATH"] == "/usr/bin"


def test_agenda_server_path_reads_opencode_json(tmp_path):
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"notes": {"command": ["/opt/app/.venv/bin/agenda-server"]}}}),
        encoding="utf-8",
    )
    assert agenda_server_path(tmp_path) == "/opt/app/.venv/bin/agenda-server"


def test_agenda_server_path_none_when_missing_or_malformed(tmp_path):
    assert agenda_server_path(tmp_path) is None  # no opencode.json
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    assert agenda_server_path(tmp_path) is None  # no mcp.notes.command


# ── BH-26: Pattern I — malformed mcp command is silently swallowed ───────────


def test_bh26_agenda_server_path_handles_list_out_of_range(tmp_path):
    """BH-26: agenda_server_path() returns None for an empty ``command: []``.

    This is intentional: None is the "malformed config" signal. The launcher's
    main() surfaces the problem ("could not read mcp.notes.command — run
    bootstrap first") and exits non-zero. Returning None for missing OR
    malformed config keeps the contract simple — by design, not a bug."""
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"notes": {"command": []}}}),
        encoding="utf-8",
    )
    assert agenda_server_path(tmp_path) is None
