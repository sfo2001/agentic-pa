"""Tests for the dev config generator's MODEL_OPTIONS parsing (P0-A wiring).

``notes-mvp`` is a hyphenated dir (not an importable package), so the module is
loaded by file path via importlib — the same shape OpenCode-adjacent dev tooling
runs it.
"""
import importlib.util
from pathlib import Path

import pytest

_GEN_PATH = Path(__file__).resolve().parents[2] / "notes-mvp" / "gen_opencode_config.py"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_opencode_config", _GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_gen()


def test_model_options_none_when_unset():
    # Empty/unset → None so the builder stays byte-for-byte unchanged (no-op).
    assert gen._model_options(None) is None
    assert gen._model_options("") is None


def test_model_options_parses_json_object():
    assert gen._model_options('{"temperature": 0}') == {"temperature": 0}


def test_model_options_rejects_invalid_json():
    # A typo must fail loud, not silently ship an unpinned config.
    with pytest.raises(SystemExit):
        gen._model_options("{not json")


def test_model_options_rejects_non_object():
    # A JSON array/scalar is not a valid provider-options block.
    with pytest.raises(SystemExit):
        gen._model_options("[1, 2, 3]")
