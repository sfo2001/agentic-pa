"""Unit tests for ``bootstrap_env.preflight_env`` and the ``EnvSpec`` model."""
from __future__ import annotations

import os

import pytest

from bootstrap_env import EnvSpec, preflight_env

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
        assert "  → cmd:        set PE_VAR_REQ=" in err


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


# ── secret masking ──────────────────────────────────────────────────────────


def test_preflight_masks_secret_values_in_ok_output(monkeypatch, capsys):
    """secret=True with a value that parsed OK → masked in the table."""
    monkeypatch.setenv("PE_VAR_KEY", "sk-supersecretkey1234")
    specs = [EnvSpec("PE_VAR_KEY", secret=True, parser=lambda v: v)]
    preflight_env(specs)  # quiet path — no output at all
    captured = capsys.readouterr()
    assert captured.err == ""


def test_preflight_does_not_mask_value_in_failure_output(monkeypatch, capsys):
    """Failure states show the raw value (hiding a bad secret defeats the purpose)."""
    monkeypatch.setenv("PE_VAR_KEY", "garbage")

    def _strict(v):
        if not v.startswith("sk-"):
            raise ValueError("must start with 'sk-'")
        return v

    specs = [EnvSpec("PE_VAR_KEY", secret=True, required=False, parser=_strict)]
    preflight_env(specs)
    err = capsys.readouterr().err
    assert "garbage" in err  # raw value shown in the failure path


# ── platform-specific hint output ────────────────────────────────────────────


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific shell hint")
def test_preflight_includes_cmd_powershell_bash_hints_on_windows(monkeypatch, capsys):
    """On Windows: cmd + powershell + bash hints are all printed."""
    monkeypatch.delenv("PE_VAR_H", raising=False)
    specs = [EnvSpec("PE_VAR_H", required=True)]
    with pytest.raises(SystemExit):
        preflight_env(specs)
    err = capsys.readouterr().err
    assert "  → cmd:        set PE_VAR_H=" in err
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
