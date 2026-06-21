import json
import pytest
from researcher._airlock import AirlockError, validate_envelope


def _good() -> str:
    return json.dumps({
        "schema_version": "1.0",
        "query": "opencode security",
        "findings": [{
            "claim": "OpenCode sandboxes via cwd.",
            "source_url": "https://example.com/a",
            "source_title": "Example",
            "retrieved_at": "2026-06-20T10:00:00Z",
        }],
        "sources": [{"url": "https://example.com/a", "title": "Example", "fetched_at": "2026-06-20T10:00:00Z"}],
    })


def test_good_envelope_passes():
    result = validate_envelope(_good())
    assert result["query"] == "opencode security"
    assert len(result["findings"]) == 1


def test_rejects_invalid_json():
    with pytest.raises(AirlockError, match="Invalid JSON"):
        validate_envelope("{bad json}")


def test_rejects_wrong_schema_version():
    bad = json.loads(_good())
    bad["schema_version"] = "99.0"
    with pytest.raises(AirlockError):
        validate_envelope(json.dumps(bad))


def test_sanitizes_invisible_unicode():
    env = json.loads(_good())
    env["findings"][0]["claim"] = "safe​text"
    result = validate_envelope(json.dumps(env))
    assert "​" not in result["findings"][0]["claim"]
    assert result["findings"][0]["claim"] == "safetext"


def test_rejects_extra_fields():
    env = json.loads(_good())
    env["malicious"] = "payload"
    with pytest.raises(AirlockError):
        validate_envelope(json.dumps(env))
