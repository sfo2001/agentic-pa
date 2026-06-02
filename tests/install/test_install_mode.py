import install


def test_choose_mode_venv_when_probe_ok():
    assert install.choose_mode(force_target=False, venv_ok=True) == "venv"


def test_choose_mode_target_when_probe_fails():
    assert install.choose_mode(force_target=False, venv_ok=False) == "target"


def test_choose_mode_target_when_forced_skips_venv():
    # forced wins even if a venv would have worked — operator override
    assert install.choose_mode(force_target=True, venv_ok=True) == "target"


def test_forced_target_reads_env():
    assert install.forced_target({"SETUP_MODE": "target"}) is True
    assert install.forced_target({"SETUP_MODE": "TARGET"}) is True
    assert install.forced_target({"SETUP_MODE": "venv"}) is False
    assert install.forced_target({}) is False
