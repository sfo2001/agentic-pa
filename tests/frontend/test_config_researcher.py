from frontend.config import build_opencode_config

BASE = dict(
    model_endpoint="http://localhost:11434",
    model_id="llama3",
    notes_root="/tmp/notes",
    python_executable="/usr/bin/python3",
    prompt_path="/tmp/prompt.md",
)


def test_includes_research_mcp_when_url_given():
    cfg = build_opencode_config(**BASE, researcher_url="http://127.0.0.1:5100", researcher_secret="s3cr3t")
    assert "research" in cfg["mcp"]
    assert cfg["mcp"]["research"]["type"] == "local"
    env = cfg["mcp"]["research"]["environment"]
    assert env["RESEARCHER_URL"] == "http://127.0.0.1:5100"
    assert env["RESEARCHER_SECRET"] == "s3cr3t"


def test_omits_research_mcp_when_no_url():
    cfg = build_opencode_config(**BASE)
    assert "research" not in cfg["mcp"]


def test_includes_research_permission_when_url_given():
    cfg = build_opencode_config(**BASE, researcher_url="http://127.0.0.1:5100", researcher_secret="s3cr3t")
    assert cfg["permission"].get("research_*") == "allow"
    assert cfg["agent"]["workspace-assistant"]["permission"].get("research_*") == "allow"


def test_omits_research_permission_when_no_url():
    cfg = build_opencode_config(**BASE)
    assert "research_*" not in cfg["permission"]


def test_includes_research_mcp_without_secret():
    cfg = build_opencode_config(**BASE, researcher_url="http://127.0.0.1:5100")
    assert "research" in cfg["mcp"]
    env = cfg["mcp"]["research"]["environment"]
    assert env["RESEARCHER_URL"] == "http://127.0.0.1:5100"
    assert "RESEARCHER_SECRET" not in env
