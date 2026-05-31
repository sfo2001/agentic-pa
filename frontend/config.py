"""Canonical OpenCode config builder + the canonical system-prompt location.

This lives in the installable ``frontend`` package (not in ``notes-mvp/``, a loose
sample dir) so both the production installer (``frontend.bootstrap``) and the dev
generator (``notes-mvp/gen_opencode_config.py``) import the SAME builder — no
duplication, no importlib-from-a-hyphenated-dir hack.
"""
from __future__ import annotations

from pathlib import Path

# The single canonical system prompt, shipped as package data (see pyproject
# [tool.setuptools.package-data]). Both bootstrap and the dev generator read it.
CANONICAL_PROMPT_PATH = Path(__file__).resolve().parent / "assets" / "notes-agent.md"


def build_opencode_config(
    *,
    model_endpoint: str,
    model_id: str,
    notes_root: str,
    agenda_server: str,
    prompt_path: str,
    present_server: str,
) -> dict:
    """Build and return the opencode.json config dict.

    Args:
        model_endpoint: Base URL of the OpenAI-compatible inference server.
        model_id: Model identifier as registered with the provider. Must not
            contain ``/`` — it is interpolated into the ``workspace-llm/<id>``
            model reference, which a slash would make ambiguous.
        notes_root: Absolute path set as NOTES_ROOT for the MCP agenda server
            (= the ``workspace/`` directory in production).
        agenda_server: Absolute path to the agenda-server executable.
        prompt_path: Absolute path to the ``notes-agent.md`` system prompt,
            embedded as ``{file:<path>}`` in the agent config.
        present_server: Absolute path to the present-server executable (MCP
            server for the presentation pane, ADR-0006). Must live in the same
            venv bin dir as agenda-server.
    """
    permissions = {
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
        "external_directory": "deny",
        "read": "allow",
        "write": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",
        "notes_*": "allow",
        "present_*": "allow",
    }
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "workspace-llm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Workspace LLM",
                "options": {"baseURL": model_endpoint, "apiKey": "local"},
                "models": {model_id: {"name": model_id}},
            }
        },
        "model": f"workspace-llm/{model_id}",
        "permission": dict(permissions),
        "agent": {
            "workspace-assistant": {
                "mode": "primary",
                "description": "Chief-of-Staff notes assistant (local-only)",
                "model": f"workspace-llm/{model_id}",
                "prompt": "{file:" + prompt_path + "}",
                "permission": dict(permissions),
            }
        },
        "mcp": {
            "notes": {
                "type": "local",
                "command": [agenda_server],
                "enabled": True,
                "environment": {"NOTES_ROOT": notes_root},
            },
            "present": {
                "type": "local",
                "command": [present_server],
                "enabled": True,
            },
        },
    }
