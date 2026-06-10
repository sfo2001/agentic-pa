import json
import sys

import pytest

from frontend.config import (
    AGENDA_SERVER_MODULE,
    PRESENT_SERVER_MODULE,
    PROVIDER_ID,
    build_opencode_config,
    parse_model_options,
)

PY = "/opt/venv/bin/python"


def test_parse_model_options_none_for_empty():
    assert parse_model_options(None) is None
    assert parse_model_options("") is None


def test_parse_model_options_parses_object():
    assert parse_model_options('{"temperature": 0}') == {"temperature": 0}


def test_parse_model_options_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_model_options("{not json")


def test_parse_model_options_rejects_non_object():
    with pytest.raises(ValueError):
        parse_model_options("[1, 2, 3]")


def _cfg(**over):
    kw = dict(
        model_endpoint="http://x/v1",
        model_id="m",
        notes_root="/n",
        python_executable=PY,
        prompt_path="/p.md",
    )
    kw.update(over)
    return build_opencode_config(**kw)


def test_api_key_defaults_to_local_when_absent():
    # Keyless/local servers get the literal "local" placeholder inline.
    opts = _cfg()["provider"][PROVIDER_ID]["options"]
    assert opts["apiKey"] == "local"


def test_api_key_omitted_from_config_when_provided():
    # A real key must NOT appear in opencode.json: any inline apiKey shadows the
    # auth.json credential (provider.ts: apiKey===undefined gate). The secret
    # lives in auth.json instead — see bootstrap._write_auth_json.
    cfg = _cfg(api_key="sk-secret")
    opts = cfg["provider"][PROVIDER_ID]["options"]
    assert "apiKey" not in opts
    # And the secret is nowhere in the serialized config.
    assert "sk-secret" not in json.dumps(cfg)


def test_module_constants_have_expected_targets():
    # These must match the [project.scripts] entry-point targets so `python -m`
    # runs the same main() as the console scripts.
    assert AGENDA_SERVER_MODULE == "agenda.server"
    assert PRESENT_SERVER_MODULE == "presenter.server"


def test_notes_command_is_python_dash_m():
    # MCP notes server spawned via the interpreter, not a console-script exe
    # (Windows Scripts-dir / AppLocker robustness).
    assert _cfg()["mcp"]["notes"]["command"] == [PY, "-m", "agenda.server"]


def test_present_command_is_python_dash_m():
    assert _cfg()["mcp"]["present"]["command"] == [PY, "-m", "presenter.server"]


def test_notes_root_preserved_in_environment():
    cfg = _cfg(notes_root="/some/workspace")
    assert cfg["mcp"]["notes"]["environment"]["NOTES_ROOT"] == "/some/workspace"


def test_real_interpreter_modules_resolve():
    # Sanity: the very interpreter that would be written can run both modules.
    cfg = _cfg(python_executable=sys.executable)
    assert cfg["mcp"]["notes"]["command"][0] == sys.executable
    assert cfg["mcp"]["present"]["command"][0] == sys.executable


def test_mcp_key_is_notes():
    cfg = _cfg()
    assert "notes" in cfg["mcp"]
    assert "agenda" not in cfg["mcp"]


def test_permission_allows_notes_tools():
    perms = _cfg()["permission"]
    assert perms["notes_*"] == "allow"
    assert "agenda_*" not in perms
    assert perms["bash"] == "deny"  # sandbox unchanged


def test_mcp_pythonpath_baked_into_both_servers_when_given():
    # Target mode (venv-less): the MCP children are spawned by OpenCode, so they
    # must be self-sufficient — PYTHONPATH=.pysite baked into both servers'
    # environment rather than relying on ambient process inheritance.
    cfg = _cfg(mcp_pythonpath="/repo/.pysite")
    assert cfg["mcp"]["notes"]["environment"]["PYTHONPATH"] == "/repo/.pysite"
    assert cfg["mcp"]["notes"]["environment"]["NOTES_ROOT"] == "/n"
    assert cfg["mcp"]["present"]["environment"]["PYTHONPATH"] == "/repo/.pysite"


def test_mcp_pythonpath_absent_by_default():
    # venv mode: PYTHONPATH absent, but NOTES_ROOT always set on both servers.
    cfg = _cfg()
    assert "PYTHONPATH" not in cfg["mcp"]["notes"]["environment"]
    assert cfg["mcp"]["notes"]["environment"]["NOTES_ROOT"] == "/n"
    assert cfg["mcp"]["present"]["environment"]["NOTES_ROOT"] == "/n"
    assert "PYTHONPATH" not in cfg["mcp"]["present"]["environment"]


# ── P0-A: optional model_options threaded into provider options ──────────────


def test_model_options_none_is_backcompat():
    # The default (model_options omitted / None) must produce a config byte-for-byte
    # identical to one built without the new parameter — pure plumbing, no drift.
    assert _cfg() == _cfg(model_options=None)


def test_model_options_merged_into_provider_options():
    # Extra provider options (e.g. a pinned temperature or headers) flow into
    # provider[PROVIDER_ID].options so the canonical builder can pin known-good
    # defaults for a weak local backbone.
    opts = _cfg(model_options={"temperature": 0, "headers": {"x": "y"}})[
        "provider"
    ][PROVIDER_ID]["options"]
    assert opts["temperature"] == 0
    assert opts["headers"] == {"x": "y"}
    # baseURL still present alongside the merged options.
    assert opts["baseURL"] == "http://x/v1"


def test_model_options_cannot_override_baseurl():
    # baseURL is an invariant set from model_endpoint — a hostile/confused
    # model_options baseURL must NOT win, or the agent could be pointed elsewhere.
    opts = _cfg(
        model_endpoint="http://real/v1",
        model_options={"baseURL": "http://evil/v1"},
    )["provider"][PROVIDER_ID]["options"]
    assert opts["baseURL"] == "http://real/v1"


def test_model_options_does_not_break_apikey_local():
    # Keyless server: apiKey="local" must still be applied even with model_options.
    opts = _cfg(model_options={"temperature": 0})["provider"][PROVIDER_ID]["options"]
    assert opts["apiKey"] == "local"


def test_model_options_cannot_smuggle_apikey_when_key_provided():
    # When a real key is given, no apiKey may appear inline (it would shadow the
    # auth.json credential) — model_options must not be able to reintroduce one.
    cfg = _cfg(api_key="sk-secret", model_options={"apiKey": "local"})
    opts = cfg["provider"][PROVIDER_ID]["options"]
    assert "apiKey" not in opts
    assert "sk-secret" not in json.dumps(cfg)


# ── Phase 5: restrict_write flips write/edit to deny ───────────────────────


def test_restrict_write_denies_edit_and_write():
    cfg = _cfg(restrict_write=True)
    assert cfg["permission"]["write"] == "deny"
    assert cfg["permission"]["edit"] == "deny"
    assert cfg["agent"]["workspace-assistant"]["permission"]["write"] == "deny"
    assert cfg["permission"]["present_*"] == "allow"  # tools still allowed


def test_default_allows_write():
    cfg = _cfg()
    assert cfg["permission"]["write"] == "allow"
    assert cfg["permission"]["edit"] == "allow"
