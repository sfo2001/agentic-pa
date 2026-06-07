"""Unit tests for ``bootstrap_env.preflight_env`` and the ``EnvSpec`` model."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from bootstrap_env import EnvSpec, _mask_secret, preflight_env

# ── quiet paths ──────────────────────────────────────────────────────────────


def test_preflight_quiet_when_all_set_and_valid(monkeypatch, capsys):
    """All env vars set, all parsers pass → no output, no exit."""
    monkeypatch.setenv("PE_VAR_OK", "/tmp/cos")
    specs = [EnvSpec("PE_VAR_OK", parser=lambda v: v or (_ for _ in ()).throw(ValueError("empty")))]
    preflight_env(specs)  # must not raise
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_preflight_quiet_when_using_defaults(monkeypatch, capsys):
    """Unset vars with valid defaults → no output, no exit."""
    monkeypatch.delenv("PE_VAR_UNSET", raising=False)
    specs = [EnvSpec("PE_VAR_UNSET", default="/default/path", parser=lambda v: v)]
    preflight_env(specs)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_preflight_treats_empty_string_as_unset(monkeypatch, capsys):
    """``set X=`` (empty) is treated like unset; default is used silently."""
    monkeypatch.setenv("PE_VAR_EMPTY", "")
    seen = []

    def _parser(v):
        seen.append(v)
        return v

    specs = [EnvSpec("PE_VAR_EMPTY", default="/from-default", parser=_parser)]
    preflight_env(specs)
    # Parser should have been called with the default, not "".
    assert seen == ["/from-default"]
    captured = capsys.readouterr()
    assert captured.err == ""


# ── required paths (exit 2) ──────────────────────────────────────────────────


def test_preflight_exits_2_on_required_unset(monkeypatch, capsys):
    """required=True + unset + no default → sys.exit(2) and a clear error."""
    monkeypatch.delenv("PE_VAR_REQ", raising=False)
    specs = [EnvSpec("PE_VAR_REQ", required=True, hint="set PE_VAR_REQ to the install root")]
    with pytest.raises(SystemExit) as exc_info:
        preflight_env(specs)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "PE_VAR_REQ" in err
    assert "REQUIRED" in err
    assert "set PE_VAR_REQ to the install root" in err
    # bash hint is always present (Windows + POSIX both include it).
    assert "export PE_VAR_REQ=" in err
    # cmd hint is only present on Windows; on POSIX, only bash + powershell.
    if os.name == "nt":
        assert '  → cmd:        set "PE_VAR_REQ=' in err


def test_preflight_exits_2_on_required_parse_fail(monkeypatch, capsys):
    """required=True + value set but parser rejects → sys.exit(2)."""
    monkeypatch.setenv("PE_VAR_PORT", "not-a-number")

    def _int_parser(v):
        return int(v)  # raises ValueError on bad input

    specs = [EnvSpec("PE_VAR_PORT", required=True, parser=_int_parser)]
    with pytest.raises(SystemExit) as exc_info:
        preflight_env(specs)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "PE_VAR_PORT" in err
    assert "PARSE FAILED" in err
    assert "not-a-number" in err


# ── optional paths (warn, continue) ─────────────────────────────────────────


def test_preflight_warns_on_optional_unset(monkeypatch, capsys):
    """required=False + unset + no default → warn, no exit, return normally."""
    monkeypatch.delenv("PE_VAR_OPT", raising=False)
    specs = [EnvSpec("PE_VAR_OPT", required=False, hint="optional thing")]
    preflight_env(specs)  # must not raise
    err = capsys.readouterr().err
    assert "PE_VAR_OPT" in err
    assert "optional, not set" in err
    assert "optional thing" in err


def test_preflight_warns_on_optional_parse_fail(monkeypatch, capsys):
    """required=False + value set + parser rejects → warn, no exit."""
    monkeypatch.setenv("PE_VAR_OPT", "bad")

    def _strict(v):
        if v != "ok":
            raise ValueError("must be 'ok'")
        return v

    specs = [EnvSpec("PE_VAR_OPT", required=False, parser=_strict)]
    preflight_env(specs)  # must not raise
    err = capsys.readouterr().err
    assert "PARSE FAILED" in err
    assert "must be 'ok'" in err


# ── _mask_secret unit tests (3 branches) ───────────────────────────────────


def test_mask_secret_empty():
    assert _mask_secret("") == ""


def test_mask_secret_short():
    assert _mask_secret("ab") == "****"
    assert _mask_secret("abcd") == "****"


def test_mask_secret_long():
    result = _mask_secret("sk-supersecretkey1234")
    assert result == "sk****34"


# ── secret masking ──────────────────────────────────────────────────────────


def test_preflight_quiet_when_secret_is_ok(monkeypatch, capsys):
    """secret=True with a value that parsed OK → quiet path (no output)."""
    monkeypatch.setenv("PE_VAR_KEY", "sk-supersecretkey1234")
    specs = [EnvSpec("PE_VAR_KEY", secret=True, parser=lambda v: v)]
    preflight_env(specs)  # quiet path — no output at all
    captured = capsys.readouterr()
    assert captured.err == ""


def test_preflight_masks_secret_value_in_failure_output(monkeypatch, capsys):
    """A secret that fails its parser must NOT leak its raw value — neither in
    the table row nor via the parser's exception text (which can echo it).
    Non-secret parse failures still show the value (see the required-parse-fail
    test); secrets are the deliberate exception."""
    monkeypatch.setenv("PE_VAR_KEY", "garbage-secret-value")

    def _strict(v):
        if not v.startswith("sk-"):
            raise ValueError(f"must start with 'sk-', got {v!r}")  # echoes value

    specs = [EnvSpec("PE_VAR_KEY", secret=True, required=False, parser=_strict)]
    preflight_env(specs)
    err = capsys.readouterr().err
    assert "garbage-secret-value" not in err  # raw secret must not leak
    assert "PARSE FAILED" in err              # failure is still reported
    assert "ga****ue" in err                  # masked form is shown instead


def test_preflight_masks_ok_secret_in_mixed_loud_path(monkeypatch, capsys):
    """When one spec fails and another has a secret=OK value, the OK value
    must be masked in the table output even on the loud path."""
    monkeypatch.setenv("PE_VAR_KEY", "sk-supersecretkey1234")
    monkeypatch.delenv("PE_VAR_REQ", raising=False)
    specs = [
        EnvSpec("PE_VAR_KEY", secret=True, parser=lambda v: v),
        EnvSpec("PE_VAR_REQ", required=True),
    ]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    err = capsys.readouterr().err
    # The OK secret value must NOT appear in plain text
    assert "supersecretkey" not in err, "OK secret leaked in plain text on loud path"
    # The masked form should appear
    assert "sk****34" in err, "masked form not found in loud-path table"


# ── _mask_secret boundary ───────────────────────────────────────────────────


def test_mask_secret_five_chars():
    """Exactly 5 chars: triggers the masking branch, not the short-circuit."""
    assert _mask_secret("12345") == "12****45"


# ── _shell_hints unit tests ─────────────────────────────────────────────────


def test_shell_hints_cmd_quoted(monkeypatch):
    """The cmd hint must wrap name=value in double quotes for spaces/atoms."""
    monkeypatch.setattr(os, "name", "nt")
    from bootstrap_env import _shell_hints

    hints = _shell_hints("MY_VAR", "C:/Program Files/app")
    cmd_line = [h for h in hints if "→ cmd:" in h]
    assert cmd_line, "expected a cmd hint"
    assert '"MY_VAR=C:/Program Files/app"' in cmd_line[0]


def test_shell_hints_powershell_quotes_correctly():
    """PowerShell hint must use single quotes, not shlex POSIX escapes."""
    from bootstrap_env import _shell_hints

    hints = _shell_hints("MY_VAR", "it's a value")
    ps_line = [h for h in hints if "→ powershell:" in h]
    assert ps_line, "expected a powershell hint"
    assert "$env:MY_VAR = 'it''s a value'" in ps_line[0]


def test_shell_hints_bash_uses_shlex():
    """Bash hint must use shlex.quote for proper shell escaping."""
    from bootstrap_env import _shell_hints

    hints = _shell_hints("MY_VAR", "value with spaces")
    bash_line = [h for h in hints if "→ bash:" in h]
    assert bash_line, "expected a bash hint"
    assert "'value with spaces'" in bash_line[0]


# ── empty-spec edge case ────────────────────────────────────────────────────


def test_preflight_empty_specs(capsys):
    """Empty spec list is a no-op — no output, no exit."""
    preflight_env([])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ── non-fatal label test ────────────────────────────────────────────────────


def test_preflight_non_fatal_label(monkeypatch, capsys):
    """When only optional failures exist, the label must say 'issue', not 'fatal issue'."""
    monkeypatch.delenv("PE_VAR_OPT", raising=False)
    specs = [EnvSpec("PE_VAR_OPT", required=False, hint="optional thing")]
    preflight_env(specs)  # no exit
    err = capsys.readouterr().err
    assert "Environment (issue):" in err
    assert "fatal issue" not in err


# ── TypeError parse-fail ────────────────────────────────────────────────────


def test_preflight_typeerror_on_parse(monkeypatch, capsys):
    """Parser raising TypeError (not ValueError) must still be caught."""
    monkeypatch.setenv("PE_VAR_T", "bad")

    def _typeerror_parser(v):
        if v != "ok":
            raise TypeError("must be 'ok'")
        return v

    specs = [EnvSpec("PE_VAR_T", required=True, parser=_typeerror_parser)]
    with pytest.raises(SystemExit) as exc_info:
        preflight_env(specs)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "PARSE FAILED" in err
    assert "must be 'ok'" in err


# ── _port_parser unit tests ─────────────────────────────────────────────────


def test_port_parser_valid():
    """Valid ports (1–65535) must pass."""
    from launcher.run import _port_parser

    for port in (1, 80, 443, 4096, 65535):
        assert _port_parser(str(port)) == port, f"port {port} should be valid"


def test_port_parser_zero_invalid():
    """Port 0 is not in the valid range 1–65535."""
    from launcher.run import _port_parser

    with pytest.raises(ValueError, match="port must be 1–65535"):
        _port_parser("0")


def test_port_parser_overflow_invalid():
    """Port 65536 exceeds the maximum."""
    from launcher.run import _port_parser

    with pytest.raises(ValueError, match="port must be 1–65535"):
        _port_parser("65536")


def test_port_parser_negative_invalid():
    """Negative port is outside the valid range."""
    from launcher.run import _port_parser

    with pytest.raises(ValueError, match="port must be 1–65535"):
        _port_parser("-1")


def test_port_parser_non_numeric_invalid():
    """Non-numeric input must raise ValueError."""
    from launcher.run import _port_parser

    with pytest.raises(ValueError, match="invalid literal for int"):
        _port_parser("not-a-number")


def test_port_parser_empty_invalid():
    """Empty string must raise ValueError (not silently coerce to 0)."""
    from launcher.run import _port_parser

    with pytest.raises(ValueError, match="invalid literal for int"):
        _port_parser("")


# ── platform-specific hint output ────────────────────────────────────────────


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific shell hint")
def test_preflight_includes_cmd_powershell_bash_hints_on_windows(monkeypatch, capsys):
    """On Windows: cmd + powershell + bash hints are all printed."""
    monkeypatch.delenv("PE_VAR_H", raising=False)
    specs = [EnvSpec("PE_VAR_H", required=True)]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    err = capsys.readouterr().err
    assert '  → cmd:        set "PE_VAR_H=' in err
    assert "  → powershell: $env:PE_VAR_H = " in err
    assert "  → bash:       export PE_VAR_H=" in err


@pytest.mark.skipif(os.name == "nt", reason="POSIX-specific shell hint")
def test_preflight_includes_bash_and_powershell_hints_on_posix(monkeypatch, capsys):
    """On POSIX: bash + powershell (Core) hints; no cmd hint."""
    monkeypatch.delenv("PE_VAR_H", raising=False)
    specs = [EnvSpec("PE_VAR_H", required=True)]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    err = capsys.readouterr().err
    assert "  → bash:       export PE_VAR_H=" in err
    assert "  → powershell: $env:PE_VAR_H = " in err
    assert "  → cmd:" not in err


# ── output routing ───────────────────────────────────────────────────────────


def test_preflight_writes_loud_output_to_stderr_only(monkeypatch, capsys):
    """Loud-path output is on stderr, never stdout (stdout stays clean for pipes)."""
    monkeypatch.delenv("PE_VAR_R", raising=False)
    specs = [EnvSpec("PE_VAR_R", required=True)]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays empty
    assert "PE_VAR_R" in captured.err  # stderr has the table + hint


# ── mixed: some ok, some not ─────────────────────────────────────────────────


def test_preflight_mixed_ok_and_failing_prints_full_table(monkeypatch, capsys):
    """When at least one spec fails, the table shows ALL rows so the user can
    spot other issues at the same time (fix one, see if another is also broken)."""
    monkeypatch.setenv("PE_VAR_A", "ok-value")
    monkeypatch.setenv("PE_VAR_B", "bad-int")
    monkeypatch.delenv("PE_VAR_C", raising=False)
    specs = [
        EnvSpec("PE_VAR_A", parser=lambda v: v),
        EnvSpec("PE_VAR_B", required=True, parser=int),  # parse-fail
        EnvSpec("PE_VAR_C", required=True),  # required-unset
    ]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    err = capsys.readouterr().err
    # All three rows present
    assert "PE_VAR_A" in err
    assert "PE_VAR_B" in err
    assert "PE_VAR_C" in err
    # And their failure sources
    assert "PARSE FAILED" in err
    assert "REQUIRED" in err


# ── shim structural checks (Windows .cmd files) ─────────────────────────────


@pytest.mark.parametrize("shim_name", ["setup.cmd", "run.cmd"])
def test_windows_shims_probe_for_py_launcher(shim_name):
    """The Windows cmd shims must fail loud if the ``py`` launcher is missing,
    rather than letting the user's shell emit a generic "'py' is not recognized"
    that doesn't mention the fix.

    This is a structural test — we read the file and assert the probe exists.
    The actual behavior (exit 1 on missing py) is only verifiable on Windows,
    but the static check catches the regression where someone removes the probe
    while refactoring the shim."""
    repo_root = Path(__file__).resolve().parents[2]
    shim = repo_root / shim_name
    assert shim.is_file(), f"shim {shim_name} not found at {shim}"
    text = shim.read_text(encoding="utf-8")
    assert "where py" in text, (
        f"{shim_name} is missing the `where py` probe; users on a Windows box "
        "without the Python launcher will see a generic 'not recognized' error "
        "instead of a fix-it hint."
    )
    # The remediation message text is a stable substring; allow for the shim
    # echoing it with or without literal quotes around 'py'.
    assert "launcher not found" in text, (
        f"{shim_name} is missing the remediation message; users won't know to "
        "install Python from python.org or set PYTHON=…"
    )
    # Both shims share the same probe block; assert both forms appear.
    assert "PYTHON=full-path-to-python.exe" in text, (
        f"{shim_name} is missing the PYTHON=... override hint"
    )
    # The probe must be gated behind `if not defined PYTHON` (not unconditional).
    assert "if defined PYTHON" in text or "if not defined PYTHON" in text, (
        f"{shim_name} runs `where py` unconditionally; it should only probe "
        "when PYTHON is unset"
    )


@pytest.mark.parametrize("shim_name", ["setup.sh", "run.sh"])
def test_posix_shims_probe_for_python_command(shim_name):
    """The POSIX shims must fail loud if the configured ``$PY`` interpreter
    is missing, rather than letting the shell emit a cryptic ``not found``."""
    repo_root = Path(__file__).resolve().parents[2]
    shim = repo_root / shim_name
    assert shim.is_file(), f"shim {shim_name} not found at {shim}"
    text = shim.read_text(encoding="utf-8")
    assert "command -v" in text, (
        f"{shim_name} is missing the `command -v` probe"
    )
    assert "not found" in text, (
        f"{shim_name} is missing the remediation message"
    )
    assert "PYTHON:" in text or "PYTHON=" in text, (
        f"{shim_name} is missing the PYTHON= override hint"
    )


# ── dual-default coupling guard ─────────────────────────────────────────────


def _assert_defaults_match(src_path_relative: str) -> None:
    """Assert every compile-time constant EnvSpec default matches the
    corresponding ``os.environ.get()`` default in the same source file."""
    src = (Path(__file__).resolve().parents[2] / src_path_relative).read_text(encoding="utf-8")
    envspec_defaults = _extract_envspec_defaults(src)
    osget_defaults = _extract_osget_defaults(src)

    for var_name, spec_default in envspec_defaults.items():
        assert var_name in osget_defaults, (
            f"EnvSpec declares default for {var_name} but no downstream "
            f"os.environ.get() default found"
        )
        assert osget_defaults[var_name] == spec_default, (
            f"Default mismatch for {var_name}: EnvSpec has {spec_default!r}, "
            f"downstream os.environ.get() has {osget_defaults[var_name]!r}"
        )


def test_launcher_run_defaults_match_envspec():
    """Every env-var default declared in ``launcher/run.py``'s preflight
    must match the downstream ``os.environ.get()`` default. If they diverge,
    the preflight may pass but the runtime uses a stale value (or vice versa).
    This structural test locks them together."""
    _assert_defaults_match("launcher/run.py")


def test_frontend_build_default_app_defaults_match_envspec():
    """Same dual-default coupling guard for frontend/app.py."""
    _assert_defaults_match("frontend/app.py")


# ── entry-point spec list integration tests ─────────────────────────────────


def _is_envspec_call(node):
    return (
        isinstance(node.func, ast.Name) and node.func.id == "EnvSpec"
    ) or (
        isinstance(node.func, ast.Attribute) and node.func.attr == "EnvSpec"
    )


def _envspec_name(node):
    if node.args and isinstance(node.args[0], ast.Constant):
        return node.args[0].value
    for kw in node.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def _envspec_default(node):
    for kw in node.keywords:
        if kw.arg == "default" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def _extract_envspec_defaults(src: str) -> dict[str, str]:
    """Return EnvSpec defaults that are compile-time constants, keyed by var name."""
    import ast
    tree = ast.parse(src)
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_envspec_call(node):
            name = _envspec_name(node)
            default = _envspec_default(node)
            if name and default is not None:
                result[name] = default
    return result


def _extract_osget_defaults(src: str) -> dict[str, str]:
    """Return ``os.environ.get()`` defaults that are compile-time constants.

    Handles both ``.get("X", default)`` and ``.get("X") or default`` patterns.
    The ``or`` pattern is used when the code needs to reject empty strings that
    ``.get("X", default)`` would return as-is."""
    import ast
    tree = ast.parse(src)
    result: dict[str, str] = {}

    def _env_name(call_node):
        if call_node.args and isinstance(call_node.args[0], ast.Constant):
            return call_node.args[0].value
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            name = _env_name(node)
            if name is None:
                continue
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                result[name] = node.args[1].value
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            left, right = node.values[0], node.values[1]
            if (isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute)
                    and left.func.attr == "get" and len(left.args) == 1):
                name = _env_name(left)
                if name and isinstance(right, ast.Constant):
                    result[name] = right.value
    return result


def _extract_envspec_names(src: str) -> list[str]:
    """Return the list of env-var names declared in ``preflight_env([...])`` calls."""
    import ast
    tree = ast.parse(src)
    names: list[str] = []
    for node in ast.walk(tree):
        is_envspec = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "EnvSpec"
        )
        if not is_envspec:
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            names.append(node.args[0].value)
        else:
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    names.append(kw.value.value)
                    break
    return names


def test_entry_point_install_has_expected_specs():
    """install.py preflight_env declares SETUP_MODE and LLM_WIKI_TOOLS."""
    src = (Path(__file__).resolve().parents[2] / "install.py").read_text(encoding="utf-8")
    names = _extract_envspec_names(src)
    assert "SETUP_MODE" in names
    assert "LLM_WIKI_TOOLS" in names


def test_entry_point_launch_has_expected_specs():
    """launch.py preflight_env declares INSTALL_ROOT."""
    src = (Path(__file__).resolve().parents[2] / "launch.py").read_text(encoding="utf-8")
    names = _extract_envspec_names(src)
    assert "INSTALL_ROOT" in names


def test_entry_point_launcher_run_has_expected_specs():
    """launcher/run.py preflight_env declares INSTALL_ROOT, OPENCODE_PORT, WEB_PORT."""
    src = (Path(__file__).resolve().parents[2] / "launcher" / "run.py").read_text(encoding="utf-8")
    names = _extract_envspec_names(src)
    assert "INSTALL_ROOT" in names
    assert "OPENCODE_PORT" in names
    assert "WEB_PORT" in names


def test_entry_point_setup_wizard_has_expected_specs():
    """frontend/setup_wizard.py preflight_env declares COS_PYSITE."""
    src = (Path(__file__).resolve().parents[2] / "frontend" / "setup_wizard.py").read_text(encoding="utf-8")
    names = _extract_envspec_names(src)
    assert "COS_PYSITE" in names


def test_entry_point_frontend_app_has_expected_specs():
    """frontend/app.py build_default_app preflight_env declares OPENCODE_BASE_URL,
    NOTES_ROOT, NOTES_GIT_DIR."""
    src = (Path(__file__).resolve().parents[2] / "frontend" / "app.py").read_text(encoding="utf-8")
    names = _extract_envspec_names(src)
    assert "OPENCODE_BASE_URL" in names
    assert "NOTES_ROOT" in names
    assert "NOTES_GIT_DIR" in names


# ── _powershell_quote direct unit tests ─────────────────────────────────────


def test_powershell_quote_empty_plain_and_embedded_quote():
    """Direct contract test for _powershell_quote: empty → '', plain wraps in
    single quotes, embedded single quotes are doubled (PowerShell escaping)."""
    from bootstrap_env import _powershell_quote

    assert _powershell_quote("") == "''"
    assert _powershell_quote("plain") == "'plain'"
    assert _powershell_quote("a'b'c") == "'a''b''c'"


# ── secret masked when sourced from a default (loud path) ────────────────────


def test_preflight_masks_secret_default_in_loud_path(monkeypatch, capsys):
    """A secret whose value comes from its ``default`` (not the env) must still
    be masked in the loud-path table when another spec forces the loud path."""
    monkeypatch.delenv("PE_VAR_KEY", raising=False)
    monkeypatch.delenv("PE_VAR_REQ", raising=False)
    specs = [
        EnvSpec("PE_VAR_KEY", default="sk-defaultsecretvalue", secret=True, parser=lambda v: v),
        EnvSpec("PE_VAR_REQ", required=True),
    ]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    err = capsys.readouterr().err
    assert "defaultsecret" not in err  # raw default secret must not leak
    assert "sk****ue" in err           # masked form of "sk-defaultsecretvalue"


# ── entry-point preflight INVOCATION (behavioral, not AST) ───────────────────
#
# The _extract_envspec_names tests above prove the specs are *declared* in
# source. These prove each main() actually *calls* preflight_env first, before
# any real work — by injecting a sentinel into bootstrap_env.preflight_env (the
# entry points do ``from bootstrap_env import preflight_env`` inside main(), so
# the attribute is resolved at call time and the sentinel is picked up). The
# sentinel raises immediately, so no real install/launch side effects run.


def _preflight_sentinel(captured: dict):
    def _sentinel(specs):
        captured["names"] = [s.name for s in specs]
        raise SystemExit(99)

    return _sentinel


def test_install_main_invokes_preflight_first(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("bootstrap_env.preflight_env", _preflight_sentinel(captured))
    import install

    with pytest.raises(SystemExit) as exc:
        install.main()
    assert exc.value.code == 99  # sentinel fired before any real work
    assert "SETUP_MODE" in captured["names"]
    assert "LLM_WIKI_TOOLS" in captured["names"]


def test_launch_main_invokes_preflight_first(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("bootstrap_env.preflight_env", _preflight_sentinel(captured))
    import launch

    with pytest.raises(SystemExit) as exc:
        launch.main([])
    assert exc.value.code == 99
    assert "INSTALL_ROOT" in captured["names"]


def test_launcher_run_main_invokes_preflight_first(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("bootstrap_env.preflight_env", _preflight_sentinel(captured))
    from launcher import run

    with pytest.raises(SystemExit) as exc:
        run.main()
    assert exc.value.code == 99
    assert {"INSTALL_ROOT", "OPENCODE_PORT", "WEB_PORT"} <= set(captured["names"])


def test_setup_wizard_main_invokes_preflight_first(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("bootstrap_env.preflight_env", _preflight_sentinel(captured))
    from frontend import setup_wizard

    with pytest.raises(SystemExit) as exc:
        setup_wizard.main()
    assert exc.value.code == 99
    assert "COS_PYSITE" in captured["names"]


# ── _restrict_write_env unit tests ──────────────────────────────────────────


def test_restrict_write_env_true_variants(monkeypatch):
    from launcher.run import _restrict_write_env
    for val in ("1", "true", "TRUE", "True", "yes", "YES", "on", "ON"):
        monkeypatch.setenv("RESTRICT_WRITE", val)
        assert _restrict_write_env() is True, f"{val!r} should be True"


def test_restrict_write_env_false_variants(monkeypatch):
    from launcher.run import _restrict_write_env
    for val in ("0", "false", "FALSE", "False", "no", "NO", "off", "OFF"):
        monkeypatch.setenv("RESTRICT_WRITE", val)
        assert _restrict_write_env() is False, f"{val!r} should be False"


def test_restrict_write_env_none_variants(monkeypatch):
    from launcher.run import _restrict_write_env
    monkeypatch.delenv("RESTRICT_WRITE", raising=False)
    assert _restrict_write_env() is None
    monkeypatch.setenv("RESTRICT_WRITE", "")
    assert _restrict_write_env() is None
    monkeypatch.setenv("RESTRICT_WRITE", "garbage")
    assert _restrict_write_env() is None
    monkeypatch.setenv("RESTRICT_WRITE", "2")
    assert _restrict_write_env() is None


# ── Phase 5: launcher _apply_restrict_write ─────────────────────────────────


def _write_cfg(p, write="allow"):
    p.write_text(json.dumps({
        "permission": {"write": write, "edit": write, "present_*": "allow"},
        "agent": {"workspace-assistant": {"permission": {"write": write, "edit": write}}},
    }), encoding="utf-8")


def test_apply_restrict_write_denies_when_env_true(tmp_path, monkeypatch):
    from launcher.run import _apply_restrict_write
    cfg = tmp_path / "opencode.json"
    _write_cfg(cfg, "allow")
    monkeypatch.setenv("RESTRICT_WRITE", "1")
    _apply_restrict_write(tmp_path)
    c = json.loads(cfg.read_text())
    assert c["permission"]["write"] == "deny"
    assert c["agent"]["workspace-assistant"]["permission"]["edit"] == "deny"


def test_apply_restrict_write_allows_when_env_false(tmp_path, monkeypatch):
    from launcher.run import _apply_restrict_write
    cfg = tmp_path / "opencode.json"
    _write_cfg(cfg, "deny")
    monkeypatch.setenv("RESTRICT_WRITE", "0")
    _apply_restrict_write(tmp_path)
    assert json.loads(cfg.read_text())["permission"]["write"] == "allow"


def test_apply_restrict_write_unset_leaves_baked(tmp_path, monkeypatch):
    from launcher.run import _apply_restrict_write
    cfg = tmp_path / "opencode.json"
    _write_cfg(cfg, "deny")
    monkeypatch.delenv("RESTRICT_WRITE", raising=False)
    _apply_restrict_write(tmp_path)
    assert json.loads(cfg.read_text())["permission"]["write"] == "deny"  # baked default kept
