import importlib.util
import json

from frontend import setup_wizard


def test_check_environment_clean_in_configured_venv():
    blocking, _warnings = setup_wizard.check_environment()
    # Everything is installed in the test venv → nothing blocking.
    assert blocking == []


def test_check_environment_flags_missing_runtime_package_as_warning(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name == "markitdown" else real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    blocking, warnings = setup_wizard.check_environment()
    assert blocking == []  # a missing runtime dep is a warning, not blocking
    assert any("markitdown" in w for w in warnings)


def test_check_environment_blocks_when_core_package_missing(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name == "frontend" else real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    blocking, _warnings = setup_wizard.check_environment()
    assert any("frontend" in b for b in blocking)


def test_fetch_models_parses_openai_list(monkeypatch):
    class _Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = {"object": "list", "data": [{"id": "m-a"}, {"id": "m-b"}, {"nope": 1}]}
    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert setup_wizard.fetch_models("http://x/v1") == ["m-a", "m-b"]


def test_fetch_models_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", boom)
    assert setup_wizard.fetch_models("http://x/v1") == []
