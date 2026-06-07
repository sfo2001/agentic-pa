import json
import socket
import subprocess
import sys

from launcher.run import (
    _module_importable,
    _probe_module_import,
    _python_m_module,
    agenda_server_path,
    isolated_env,
    no_git_ancestor,
    notes_mcp_command,
    port_is_free,
    present_mcp_command,
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


# ── python -m command form (Windows-robust MCP spawn) ────────────────────────


def test_notes_mcp_command_returns_full_list(tmp_path):
    cmd = ["/opt/.venv/bin/python", "-m", "agenda.server"]
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"notes": {"command": cmd}}}), encoding="utf-8"
    )
    assert notes_mcp_command(tmp_path) == cmd


def test_notes_mcp_command_none_when_missing_or_empty(tmp_path):
    assert notes_mcp_command(tmp_path) is None  # no opencode.json
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"notes": {"command": []}}}), encoding="utf-8"
    )
    assert notes_mcp_command(tmp_path) is None  # empty command


def test_agenda_server_path_returns_interpreter_for_python_m_form(tmp_path):
    # With the python -m form, command[0] is the interpreter (still command[0]).
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"notes": {"command": ["/opt/.venv/bin/python", "-m", "agenda.server"]}}}),
        encoding="utf-8",
    )
    assert agenda_server_path(tmp_path) == "/opt/.venv/bin/python"


def test_python_m_module_detects_form():
    assert _python_m_module(["/venv/bin/python", "-m", "agenda.server"]) == "agenda.server"
    assert _python_m_module(["/usr/bin/agenda-server"]) is None        # legacy exe form
    assert _python_m_module(["/venv/bin/python", "-c", "x"]) is None    # not -m


def test_module_importable_true_for_stdlib():
    assert _module_importable(sys.executable, "json") is True


def test_module_importable_false_for_missing_module():
    assert _module_importable(sys.executable, "no_such_module_xyz_42") is False


def test_module_importable_false_for_bad_interpreter():
    assert _module_importable("/nonexistent/python", "json") is False


def test_module_importable_rejects_malformed_name_without_spawning():
    # A tampered module name must be rejected by the regex guard before any
    # subprocess runs — no code from the `-c` string is ever executed.
    assert _module_importable(sys.executable, "os; import subprocess") is False
    assert _module_importable(sys.executable, "a-b") is False
    assert _module_importable(sys.executable, "") is False


def test_module_importable_false_on_timeout(monkeypatch):
    # A hung import (TimeoutExpired, a SubprocessError) must fail closed, not raise.
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="python", timeout=10)

    monkeypatch.setattr("launcher.run.subprocess.run", boom)
    assert _module_importable(sys.executable, "json") is False


# ── present MCP soft-probe (surface a crashed optional server at launch) ─────


def test_present_mcp_command_reads_opencode_json(tmp_path):
    cmd = ["/opt/.venv/bin/python", "-m", "presenter.server"]
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"present": {"command": cmd}}}), encoding="utf-8"
    )
    assert present_mcp_command(tmp_path) == cmd


def test_present_mcp_command_none_when_missing_or_empty(tmp_path):
    assert present_mcp_command(tmp_path) is None  # no opencode.json
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"present": {"command": []}}}), encoding="utf-8"
    )
    assert present_mcp_command(tmp_path) is None  # empty command


def test_probe_module_import_ok_for_stdlib():
    ok, err = _probe_module_import(sys.executable, "json")
    assert ok is True
    assert err == ""


def test_probe_module_import_reports_reason_for_missing_module():
    ok, err = _probe_module_import(sys.executable, "no_such_module_xyz_42")
    assert ok is False
    assert "ModuleNotFoundError" in err or "No module named" in err


def test_probe_module_import_rejects_malformed_name_without_spawning():
    ok, err = _probe_module_import(sys.executable, "os; import subprocess")
    assert ok is False
    assert "invalid module name" in err


def test_probe_module_import_honours_cwd(tmp_path):
    # A module importable only because of a file in cwd must NOT import from a
    # different cwd — proving the probe runs where OpenCode spawns the server
    # (the exact dimension that hid the present-MCP crash).
    (tmp_path / "only_here_pkg.py").write_text("x = 1\n", encoding="utf-8")
    other = tmp_path / "sub"
    other.mkdir()
    ok_here, _ = _probe_module_import(sys.executable, "only_here_pkg", cwd=str(tmp_path))
    ok_else, _ = _probe_module_import(sys.executable, "only_here_pkg", cwd=str(other))
    assert ok_here is True
    assert ok_else is False
