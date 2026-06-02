import importlib.util
import json

from frontend import setup_wizard


class _Resp:
    """Minimal stand-in for urllib's response context manager (read + with)."""

    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


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
    payload = {"object": "list", "data": [{"id": "m-a"}, {"id": "m-b"}, {"nope": 1}]}
    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert setup_wizard.fetch_models("http://x/v1") == ["m-a", "m-b"]


def test_fetch_models_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", boom)
    assert setup_wizard.fetch_models("http://x/v1") == []


def test_probe_endpoint_ok_returns_models(monkeypatch):
    payload = {"object": "list", "data": [{"id": "m-a"}, {"id": "m-b"}]}
    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert setup_wizard.probe_endpoint("http://x/v1") == ("ok", ["m-a", "m-b"])


def test_probe_endpoint_auth_on_401(monkeypatch):
    def unauthorized(*a, **k):
        raise setup_wizard.urllib.error.HTTPError("http://x/v1/models", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", unauthorized)
    assert setup_wizard.probe_endpoint("http://x/v1") == ("auth", [])


def test_probe_endpoint_unreachable_on_connection_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", boom)
    assert setup_wizard.probe_endpoint("http://x/v1") == ("unreachable", [])


def test_probe_endpoint_sends_bearer_token(monkeypatch):
    seen = {}

    def capture(req, *a, **k):
        seen["auth"] = req.get_header("Authorization")
        return _Resp({"data": [{"id": "m"}]})

    monkeypatch.setattr(setup_wizard.urllib.request, "urlopen", capture)
    setup_wizard.probe_endpoint("http://x/v1", api_key="secret-key")
    assert seen["auth"] == "Bearer secret-key"


# --------------------------------------------------------------------------
# _collect_endpoint — the probe -> auth/unreachable loop (every branch).
# The endpoint is read via _prompt; the secret key via _secret (hidden input).
# --------------------------------------------------------------------------
def test_collect_endpoint_prompts_for_key_when_auth_required(monkeypatch):
    # First probe (no key) -> auth; second probe (with key) -> ok.
    calls = []

    def fake_probe(endpoint, api_key=None):
        calls.append(api_key)
        return ("ok", ["m"]) if api_key else ("auth", [])

    monkeypatch.setattr(setup_wizard, "probe_endpoint", fake_probe)
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "http://x/v1")
    monkeypatch.setattr(setup_wizard, "_secret", lambda *a, **k: "my-key")

    endpoint, api_key = setup_wizard._collect_endpoint("http://default/v1")
    assert (endpoint, api_key) == ("http://x/v1", "my-key")
    assert calls == [None, "my-key"]  # probed once without, once with the key


def test_collect_endpoint_auth_empty_key_bails_without_loop(monkeypatch):
    # Auth required but the user enters no key → return (endpoint, None), no hang.
    probes = []
    monkeypatch.setattr(
        setup_wizard, "probe_endpoint",
        lambda endpoint, api_key=None: (probes.append(api_key) or ("auth", [])),
    )
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "http://x/v1")
    monkeypatch.setattr(setup_wizard, "_secret", lambda *a, **k: "")  # user hits enter

    endpoint, api_key = setup_wizard._collect_endpoint("http://default/v1")
    assert (endpoint, api_key) == ("http://x/v1", None)
    assert probes == [None]  # probed once, then bailed — no infinite loop


def test_collect_endpoint_unreachable_then_reenter_succeeds(monkeypatch):
    # First endpoint unreachable; user re-enters a second endpoint that is ok.
    endpoints_seen = []

    def fake_probe(endpoint, api_key=None):
        endpoints_seen.append(endpoint)
        return ("ok", ["m"]) if endpoint == "http://good/v1" else ("unreachable", [])

    prompts = iter(["http://bad/v1", "http://good/v1"])
    monkeypatch.setattr(setup_wizard, "probe_endpoint", fake_probe)
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: next(prompts))
    monkeypatch.setattr(setup_wizard, "_yes", lambda *a, **k: True)  # yes, re-enter

    endpoint, api_key = setup_wizard._collect_endpoint("http://default/v1")
    assert (endpoint, api_key) == ("http://good/v1", None)
    assert endpoints_seen == ["http://bad/v1", "http://good/v1"]


def test_collect_endpoint_unreachable_give_up_returns_current(monkeypatch):
    # Unreachable and the user declines to re-enter → return (endpoint, None).
    monkeypatch.setattr(setup_wizard, "probe_endpoint", lambda *a, **k: ("unreachable", []))
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "http://x/v1")
    monkeypatch.setattr(setup_wizard, "_yes", lambda *a, **k: False)  # don't re-enter

    endpoint, api_key = setup_wizard._collect_endpoint("http://default/v1")
    assert (endpoint, api_key) == ("http://x/v1", None)


def test_collect_endpoint_warns_on_plaintext_remote_key(monkeypatch, capsys):
    # http:// to a non-loopback host with a key → user is warned about cleartext.
    monkeypatch.setattr(
        setup_wizard, "probe_endpoint",
        lambda endpoint, api_key=None: ("ok", ["m"]) if api_key else ("auth", []),
    )
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "http://remote-host/v1")
    monkeypatch.setattr(setup_wizard, "_secret", lambda *a, **k: "my-key")

    endpoint, api_key = setup_wizard._collect_endpoint("http://default/v1")
    assert api_key == "my-key"
    assert "unencrypted" in capsys.readouterr().out


def test_is_plaintext_remote_classifies_endpoints():
    assert setup_wizard._is_plaintext_remote("http://example.com/v1") is True
    assert setup_wizard._is_plaintext_remote("http://localhost:11434/v1") is False
    assert setup_wizard._is_plaintext_remote("http://127.0.0.1/v1") is False
    assert setup_wizard._is_plaintext_remote("https://example.com/v1") is False


# --------------------------------------------------------------------------
# _choose_model — pick-list vs manual entry (signature gained api_key).
# --------------------------------------------------------------------------
def test_choose_model_manual_entry_when_no_models(monkeypatch):
    monkeypatch.setattr(setup_wizard, "fetch_models", lambda *a, **k: [])
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "typed-id")
    assert setup_wizard._choose_model("http://x/v1", api_key="k") == "typed-id"


def test_choose_model_numeric_pick_from_list(monkeypatch):
    monkeypatch.setattr(setup_wizard, "fetch_models", lambda *a, **k: ["m-a", "m-b", "m-c"])
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "2")
    assert setup_wizard._choose_model("http://x/v1") == "m-b"


def test_choose_model_typed_id_overrides_list(monkeypatch):
    monkeypatch.setattr(setup_wizard, "fetch_models", lambda *a, **k: ["m-a", "m-b"])
    monkeypatch.setattr(setup_wizard, "_prompt", lambda *a, **k: "custom-id")
    assert setup_wizard._choose_model("http://x/v1") == "custom-id"
