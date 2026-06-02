import json

from frontend.config import PROVIDER_ID, build_opencode_config


def _cfg():
    return build_opencode_config(
        model_endpoint="http://x/v1",
        model_id="m",
        notes_root="/n",
        agenda_server="/bin/agenda-server",
        prompt_path="/p.md",
        present_server="/bin/present-server",
    )


def test_api_key_defaults_to_local_when_absent():
    # Keyless/local servers get the literal "local" placeholder inline.
    opts = _cfg()["provider"][PROVIDER_ID]["options"]
    assert opts["apiKey"] == "local"


def test_api_key_omitted_from_config_when_provided():
    # A real key must NOT appear in opencode.json: any inline apiKey shadows the
    # auth.json credential (provider.ts: apiKey===undefined gate). The secret
    # lives in auth.json instead — see bootstrap._write_auth_json.
    cfg = build_opencode_config(
        model_endpoint="http://x/v1",
        model_id="m",
        notes_root="/n",
        agenda_server="/bin/agenda-server",
        prompt_path="/p.md",
        present_server="/bin/present-server",
        api_key="sk-secret",
    )
    opts = cfg["provider"][PROVIDER_ID]["options"]
    assert "apiKey" not in opts
    # And the secret is nowhere in the serialized config.
    assert "sk-secret" not in json.dumps(cfg)


def test_mcp_key_is_notes():
    cfg = _cfg()
    assert "notes" in cfg["mcp"]
    assert "agenda" not in cfg["mcp"]


def test_permission_allows_notes_tools():
    perms = _cfg()["permission"]
    assert perms["notes_*"] == "allow"
    assert "agenda_*" not in perms
    assert perms["bash"] == "deny"  # sandbox unchanged
