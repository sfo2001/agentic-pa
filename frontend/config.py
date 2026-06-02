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

# OpenCode provider id for our custom OpenAI-compatible provider. This single
# constant must match the key under ``provider`` in opencode.json AND the key in
# OpenCode's auth.json — OpenCode matches a stored credential to a provider by
# this id (see opencode provider.ts: auth.get(providerID)).
PROVIDER_ID = "workspace-llm"


def build_opencode_config(
    *,
    model_endpoint: str,
    model_id: str,
    notes_root: str,
    agenda_server: str,
    prompt_path: str,
    present_server: str,
    api_key: str | None = None,
) -> dict:
    """Build and return the opencode.json config dict.

    Args:
        model_endpoint: Base URL of the OpenAI-compatible inference server.
        model_id: Model identifier as registered with the provider. Must not
            contain ``/`` — it is interpolated into the ``{PROVIDER_ID}/<id>``
            model reference, which a slash would make ambiguous.
        api_key: Bearer token for an authenticated endpoint, or ``None`` for a
            local/keyless server (e.g. Ollama).

            When ``None``: ``options.apiKey`` is written as the literal
            ``"local"`` the OpenAI-compatible SDK expects when no real key is
            needed.

            When a key is given: ``options.apiKey`` is OMITTED. OpenCode only
            falls back to the credential in auth.json when ``options.apiKey`` is
            *undefined* (provider.ts: ``if (options["apiKey"] === undefined &&
            provider.key) ...``). A literal value here — even ``"local"`` —
            would shadow the real key. The secret therefore lives only in
            OpenCode's auth.json (mode 600), written by ``bootstrap`` under the
            isolated oc-home; the key never enters opencode.json.
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
    # Omit apiKey when a real key is provided so OpenCode falls through to the
    # auth.json credential; keep the "local" placeholder only for keyless servers.
    options = {"baseURL": model_endpoint}
    if not api_key:
        options["apiKey"] = "local"
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Workspace LLM",
                "options": options,
                "models": {model_id: {"name": model_id}},
            }
        },
        "model": f"{PROVIDER_ID}/{model_id}",
        "permission": dict(permissions),
        "agent": {
            "workspace-assistant": {
                "mode": "primary",
                "description": "Chief-of-Staff notes assistant (local-only)",
                "model": f"{PROVIDER_ID}/{model_id}",
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
