import json
import sys

from frontend.config import (
    AGENDA_SERVER_MODULE,
    PRESENT_SERVER_MODULE,
    PROVIDER_ID,
    build_opencode_config,
)

PY = "/opt/venv/bin/python"


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
