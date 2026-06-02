import json
import sys

import pytest

from frontend import bootstrap, versioning
from frontend.config import PROVIDER_ID


def test_install_gitignores_lwt_caches(tmp_path):
    root = tmp_path / "cos-notes"
    bootstrap.init_install(
        root,
        model_endpoint="http://example:11434/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    gi = (root / "workspace" / ".gitignore").read_text(encoding="utf-8")
    assert ".lwt_cache/" in gi
    assert ".tmp/" in gi


def test_install_gitignore_appends_to_existing(tmp_path):
    """Re-install over a pre-existing .gitignore appends the lwt entries
    without clobbering existing content (idempotent, not create-only)."""
    root = tmp_path / "cos-notes"
    ws = root / "workspace"
    ws.mkdir(parents=True)
    (ws / ".gitignore").write_text("secrets.txt\n", encoding="utf-8")
    bootstrap.init_install(
        root,
        model_endpoint="http://example:11434/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    gi = (ws / ".gitignore").read_text(encoding="utf-8")
    assert "secrets.txt" in gi          # preserved
    assert ".lwt_cache/" in gi          # appended
    assert ".tmp/" in gi
    assert gi.count(".lwt_cache/") == 1  # not duplicated on the second pass


def test_no_auth_json_when_keyless(tmp_path):
    root = tmp_path / "cos-notes"
    layout = bootstrap.init_install(
        root,
        model_endpoint="http://example:11434/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    assert layout["auth_json"] is None
    assert not (root / "oc-home" / ".local" / "share" / "opencode" / "auth.json").exists()
    # Keyless keeps the inline "local" placeholder so the SDK has a key.
    cfg = json.loads((root / "opencode.json").read_text())
    assert cfg["provider"][PROVIDER_ID]["options"]["apiKey"] == "local"


def test_api_key_written_to_oc_home_auth_json_mode_600(tmp_path):
    root = tmp_path / "cos-notes"
    layout = bootstrap.init_install(
        root,
        model_endpoint="https://api.example.com/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
        api_key="sk-secret-123",
    )
    auth_path = root / "oc-home" / ".local" / "share" / "opencode" / "auth.json"
    # Lands at the path OpenCode reads under the isolated XDG_DATA_HOME.
    assert layout["auth_json"] == auth_path
    assert auth_path.is_file()
    # Native opencode format, keyed by the shared provider id.
    data = json.loads(auth_path.read_text())
    assert data[PROVIDER_ID] == {"type": "api", "key": "sk-secret-123"}
    # Secret must NOT leak into opencode.json, and apiKey is omitted there so
    # opencode falls through to auth.json.
    cfg_text = (root / "opencode.json").read_text()
    assert "sk-secret-123" not in cfg_text
    assert "apiKey" not in json.loads(cfg_text)["provider"][PROVIDER_ID]["options"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows chmod only toggles the read-only bit; POSIX mode bits aren't honored.",
)
def test_auth_json_is_owner_private_600(tmp_path):
    root = tmp_path / "cos-notes"
    layout = bootstrap.init_install(
        root,
        model_endpoint="https://api.example.com/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
        api_key="sk-secret-123",
    )
    # mode 600 like `opencode auth login` writes — owner read/write only.
    assert (layout["auth_json"].stat().st_mode & 0o777) == 0o600


def test_auth_json_merges_preexisting_credentials(tmp_path):
    root = tmp_path / "cos-notes"
    auth_path = root / "oc-home" / ".local" / "share" / "opencode" / "auth.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(json.dumps({"openrouter": {"type": "api", "key": "keep-me"}}))
    bootstrap.init_install(
        root,
        model_endpoint="https://api.example.com/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
        api_key="sk-new",
    )
    data = json.loads(auth_path.read_text())
    assert data["openrouter"] == {"type": "api", "key": "keep-me"}   # preserved
    assert data[PROVIDER_ID] == {"type": "api", "key": "sk-new"}     # added


def test_auth_json_recovers_from_corrupt_existing_file(tmp_path):
    # A pre-existing auth.json that is not valid JSON (or not a dict) must not
    # abort the install — the writer resets to {} and writes only our key.
    root = tmp_path / "cos-notes"
    auth_path = root / "oc-home" / ".local" / "share" / "opencode" / "auth.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text("}{ not json at all")  # corrupt on purpose
    bootstrap.init_install(
        root,
        model_endpoint="https://api.example.com/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
        api_key="sk-new",
    )
    data = json.loads(auth_path.read_text())
    assert data == {PROVIDER_ID: {"type": "api", "key": "sk-new"}}


def test_auth_json_resets_when_existing_is_not_a_dict(tmp_path):
    root = tmp_path / "cos-notes"
    auth_path = root / "oc-home" / ".local" / "share" / "opencode" / "auth.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(json.dumps(["unexpected", "array"]))  # valid JSON, wrong shape
    bootstrap.init_install(
        root,
        model_endpoint="https://api.example.com/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
        api_key="sk-new",
    )
    data = json.loads(auth_path.read_text())
    assert data == {PROVIDER_ID: {"type": "api", "key": "sk-new"}}


def test_bootstrap_builds_leaf_parent_layout(tmp_path):
    root = tmp_path / "cos-notes"
    layout = bootstrap.init_install(
        root,
        model_endpoint="http://example:11434/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    work = root / "workspace"
    assert work.is_dir()
    # config + secrets + prompt + git-dir live in the PARENT, not in workspace/
    assert (root / "opencode.json").is_file()
    assert (root / "notes-agent.md").is_file()
    assert not (work / "opencode.json").exists()
    assert not (work / ".git").exists()
    assert versioning.is_repo(work, git_dir=layout["git_dir"])
    # opencode.json points the agent at workspace/ and the prompt in the parent
    cfg = json.loads((root / "opencode.json").read_text())
    assert cfg["mcp"]["notes"]["environment"]["NOTES_ROOT"] == str(work)
    assert str(root / "notes-agent.md") in cfg["agent"]["workspace-assistant"]["prompt"]
    p = cfg["agent"]["workspace-assistant"]["permission"]
    assert p["bash"] == "deny" and p["external_directory"] == "deny"
    # idempotent
    bootstrap.init_install(root, model_endpoint="http://example:11434/v1",
                           model_id="test-model", agenda_server="/opt/.venv/bin/agenda-server")
    assert work.is_dir()


def test_bootstrap_refuses_install_inside_existing_git_repo(tmp_path):
    # A .git at/above the install-root would expand the agent's sandbox boundary
    # to the git work-tree root (ADR-0005), so bootstrap must refuse.
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(RuntimeError, match="git repo"):
        bootstrap.init_install(
            tmp_path / "cos-notes",
            model_endpoint="http://example:11434/v1",
            model_id="test-model",
            agenda_server="/opt/.venv/bin/agenda-server",
        )


def test_bootstrap_registers_present_mcp_server(tmp_path):
    root = tmp_path / "cos-notes"
    bootstrap.init_install(
        root, model_endpoint="http://example:11434/v1", model_id="m",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    import json
    cfg = json.loads((root / "opencode.json").read_text())
    assert "present" in cfg["mcp"]
    # derived next to agenda-server in the same venv bin dir (OS-native separators,
    # so compute the expected path the same way init_install does)
    from pathlib import Path
    expected = str(Path("/opt/.venv/bin/agenda-server").parent / "present-server")
    assert cfg["mcp"]["present"]["command"] == [expected]
    # present tool is allowed by the agent permission policy
    assert cfg["agent"]["workspace-assistant"]["permission"].get("present_*") == "allow"


def test_bootstrap_refreshes_prompt_on_reinstall(tmp_path):
    """notes-agent.md is rewritten on every install so a re-install picks up an
    updated canonical prompt (parity with opencode.json), not a stale copy."""
    root = tmp_path / "cos-notes"
    kw = dict(model_endpoint="http://example:11434/v1", model_id="test-model",
              agenda_server="/opt/.venv/bin/agenda-server")
    bootstrap.init_install(root, **kw)
    prompt = root / "notes-agent.md"
    canonical = prompt.read_text(encoding="utf-8")
    prompt.write_text("STALE — hand-edited", encoding="utf-8")

    bootstrap.init_install(root, **kw)
    assert prompt.read_text(encoding="utf-8") == canonical  # refreshed, not stale
