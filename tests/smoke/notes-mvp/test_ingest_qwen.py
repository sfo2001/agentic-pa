"""Integration canary: verify an Ollama-hosted model works with the updated system prompt.

Run with: RUN_QWEN_TEST=1 pytest tests/smoke/notes-mvp/test_ingest_qwen.py
Optionally override the model/URL via OLLAMA_MODEL and OLLAMA_URL env vars.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_MODEL = os.environ.get("OLLAMA_MODEL") or "qwen3.6:35b"

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _system_prompt() -> str:
    return (_REPO_ROOT / "frontend" / "assets" / "notes-agent.md").read_text(encoding="utf-8")

_TEST_USER_MSG = (
    "there are some notes I took today: I need an org chart for a presentation "
    "on tuesday from the assistant. Also I need to get in contact to my "
    "colleague in the Review Department and ask him to join the next Review."
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_QWEN_TEST"),
    reason="set RUN_QWEN_TEST=1 to run (requires Ollama at OLLAMA_URL)",
)


def test_model_responds_to_ingest_prompt():
    """Model produces a non-empty response for the regression conversation."""
    # Quick availability check
    tags = httpx.get(f"{_OLLAMA_URL}/api/tags", timeout=5)
    assert tags.status_code == 200, "Ollama not reachable"
    models = [m.get("name") for m in tags.json().get("models", [])]
    assert _MODEL in models, f"{_MODEL} not found in Ollama"

    response = httpx.post(
        f"{_OLLAMA_URL}/api/chat",
        json={
            "model": _MODEL,
            "stream": False,
            "options": {"temperature": 0.7},
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _TEST_USER_MSG},
            ],
        },
        timeout=120,
    )
    assert response.status_code == 200
    msg = response.json().get("message", {})
    text = (msg.get("content") or "") + "\n" + (msg.get("thinking") or "")
    assert text.strip(), "model returned empty response"