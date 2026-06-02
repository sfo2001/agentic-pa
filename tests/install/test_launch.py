import launch


def test_main_delegates_to_launcher_run_with_resolved_interp(monkeypatch, tmp_path):
    calls = {}

    def fake_resolve(repo, base=None):
        return "/usr/bin/python3", {"PYTHONPATH": "/site"}

    class FakeCompleted:
        returncode = 0

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["env"] = kw.get("env")
        calls["cwd"] = kw.get("cwd")
        return FakeCompleted()

    monkeypatch.setattr(launch.bootstrap_env, "resolve_launch", fake_resolve)
    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    rc = launch.main(["--flag"])
    assert rc == 0
    assert calls["cmd"] == ["/usr/bin/python3", "-m", "launcher.run", "--flag"]
    assert calls["env"]["PYTHONPATH"] == "/site"
    assert calls["cwd"] == str(launch.REPO)
