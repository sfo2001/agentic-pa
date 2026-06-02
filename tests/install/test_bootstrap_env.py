import os
import sys

import bootstrap_env


def test_python_runs_true_for_current_interpreter():
    assert bootstrap_env.python_runs(sys.executable) is True


def test_python_runs_false_for_missing_path(tmp_path):
    assert bootstrap_env.python_runs(tmp_path / "nope" / "python") is False


def test_resolve_launch_prefers_runnable_venv(tmp_path, monkeypatch):
    vpy = bootstrap_env.venv_python(tmp_path)
    vpy.parent.mkdir(parents=True)
    vpy.write_text("", encoding="utf-8")  # presence only; we stub the run-probe
    monkeypatch.setattr(bootstrap_env, "python_runs", lambda p: True)
    interp, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert interp == str(vpy)
    assert env == {}


def test_resolve_launch_falls_back_to_pysite_when_no_venv(tmp_path, monkeypatch):
    (tmp_path / ".pysite").mkdir()
    monkeypatch.delenv("PYTHONPATH", raising=False)
    interp, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert interp == "/usr/bin/python3"
    assert env["PYTHONPATH"] == str(tmp_path / ".pysite")


def test_resolve_launch_prepends_existing_pythonpath(tmp_path, monkeypatch):
    (tmp_path / ".pysite").mkdir()
    monkeypatch.setenv("PYTHONPATH", "/existing")
    _, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert env["PYTHONPATH"] == str(tmp_path / ".pysite") + os.pathsep + "/existing"


def test_resolve_launch_falls_back_when_venv_probe_fails(tmp_path, monkeypatch):
    # The core AppLocker scenario: the venv python exists on disk but can't run.
    vpy = bootstrap_env.venv_python(tmp_path)
    vpy.parent.mkdir(parents=True)
    vpy.write_text("", encoding="utf-8")
    (tmp_path / ".pysite").mkdir()
    monkeypatch.setattr(bootstrap_env, "python_runs", lambda p: False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    interp, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert interp == "/usr/bin/python3"
    assert env["PYTHONPATH"] == str(tmp_path / ".pysite")


def test_resolve_launch_neither_venv_nor_pysite(tmp_path):
    # No runnable venv and no .pysite → base interpreter, no env override.
    interp, env = bootstrap_env.resolve_launch(tmp_path, base="/usr/bin/python3")
    assert interp == "/usr/bin/python3"
    assert env == {}


def test_python_runs_false_for_nonzero_exit(monkeypatch):
    # Interpreter exists and runs but exits non-zero → not usable (fail closed).
    class _Completed:
        returncode = 1

    monkeypatch.setattr(bootstrap_env.subprocess, "run", lambda *a, **k: _Completed())
    assert bootstrap_env.python_runs("/usr/bin/python3") is False
