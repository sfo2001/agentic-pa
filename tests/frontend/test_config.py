from frontend.config import build_opencode_config


def _cfg():
    return build_opencode_config(
        model_endpoint="http://x/v1",
        model_id="m",
        notes_root="/n",
        agenda_server="/bin/agenda-server",
        prompt_path="/p.md",
        present_server="/bin/present-server",
    )


def test_mcp_key_is_notes():
    cfg = _cfg()
    assert "notes" in cfg["mcp"]
    assert "agenda" not in cfg["mcp"]


def test_permission_allows_notes_tools():
    perms = _cfg()["permission"]
    assert perms["notes_*"] == "allow"
    assert "agenda_*" not in perms
    assert perms["bash"] == "deny"  # sandbox unchanged
