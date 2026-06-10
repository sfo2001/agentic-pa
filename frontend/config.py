"""Canonical OpenCode config builder + the canonical system-prompt location.

This lives in the installable ``frontend`` package (not in ``notes-mvp/``, a loose
sample dir) so both the production installer (``frontend.bootstrap``) and the dev
generator (``notes-mvp/gen_opencode_config.py``) import the SAME builder — no
duplication, no importlib-from-a-hyphenated-dir hack.
"""
from __future__ import annotations

import json
from pathlib import Path

# The single canonical system prompt, shipped as package data (see pyproject
# [tool.setuptools.package-data]). Both bootstrap and the dev generator read it.
CANONICAL_PROMPT_PATH = Path(__file__).resolve().parent / "assets" / "notes-agent.md"

# OpenCode provider id for our custom OpenAI-compatible provider. This single
# constant must match the key under ``provider`` in opencode.json AND the key in
# OpenCode's auth.json — OpenCode matches a stored credential to a provider by
# this id (see opencode provider.ts: auth.get(providerID)).
PROVIDER_ID = "workspace-llm"

# The MCP servers are spawned as ``<python> -m <module>`` rather than via their
# console-script executables. This reuses the interpreter that bootstrapped the
# install (no dependence on a Scripts/bin dir being on PATH) and sidesteps
# Windows pitfalls: console scripts are ``.exe`` shims in a Scripts dir that, for
# base or ``pip install --user`` installs, isn't next to python.exe — and that
# ``.exe`` can be blocked by AppLocker/SRP execution policy. The modules below
# are the ``[project.scripts]`` entry-point targets (agenda/presenter pyproject)
# and both guard ``if __name__ == "__main__": main()`` so ``-m`` runs them.
AGENDA_SERVER_MODULE = "agenda.server"
PRESENT_SERVER_MODULE = "presenter.server"


def build_opencode_config(
    *,
    model_endpoint: str,
    model_id: str,
    notes_root: str,
    python_executable: str,
    prompt_path: str,
    api_key: str | None = None,
    mcp_pythonpath: str | None = None,
    restrict_write: bool = False,
    model_options: dict | None = None,
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
        python_executable: Absolute path to the Python interpreter used to spawn
            BOTH MCP servers as ``<python> -m <module>`` (``AGENDA_SERVER_MODULE``
            for notes, ``PRESENT_SERVER_MODULE`` for the presentation pane,
            ADR-0006). Use the venv interpreter that has agenda/presenter
            installed — normally ``sys.executable`` of the process running the
            wizard. Chosen over the console-script executables for cross-platform
            robustness (see the module constants above).
        prompt_path: Absolute path to the ``notes-agent.md`` system prompt,
            embedded as ``{file:<path>}`` in the agent config.
        mcp_pythonpath: When set (target/venv-less mode), the absolute path baked
            as ``PYTHONPATH`` into BOTH MCP servers' ``environment`` so OpenCode's
            ``<python> -m <module>`` MCP children are self-sufficient — they
            import the packages from ``.pysite`` directly rather than depending on
            ``PYTHONPATH`` being inherited down the launch chain. ``None`` (venv
            mode) leaves the config untouched: the venv interpreter already has
            the packages, and ``present`` keeps no ``environment`` block.
        restrict_write: When True, flip ``write`` and ``edit`` permissions to
            ``deny`` so the agent must route every mutation through the
            ``present_propose`` / ``present_task`` MCP tools (frontend is the
            sole writer). Default False.
        model_options: Optional extra keys merged into the provider's
            ``options`` block (alongside ``baseURL``/``apiKey``) so the canonical
            builder can pin known-good defaults for a weak local backbone (e.g. a
            fixed temperature or custom headers). The two invariants always win:
            ``baseURL`` is forced from ``model_endpoint``, and the ``apiKey``
            policy (inline ``"local"`` only when keyless; never inline when a real
            key is given, so it can't shadow the auth.json credential) is applied
            *after* the merge — so ``model_options`` can neither redirect the
            endpoint nor smuggle a key into the serialized config. ``None`` leaves
            the config byte-for-byte as before (pure plumbing).
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
    if restrict_write:
        permissions["write"] = "deny"
        permissions["edit"] = "deny"
    # Start from any caller-pinned defaults, then force the invariants on top so
    # model_options can neither redirect the endpoint (baseURL) nor smuggle a key
    # (apiKey) into the serialized config. Omit apiKey when a real key is provided
    # so OpenCode falls through to the auth.json credential; keep the "local"
    # placeholder only for keyless servers.
    options = {**(model_options or {}), "baseURL": model_endpoint}
    options.pop("apiKey", None)
    if not api_key:
        options["apiKey"] = "local"
    # Target mode bakes PYTHONPATH into each MCP server's environment so the
    # OpenCode-spawned `python -m <module>` children are self-sufficient; venv
    # mode leaves both untouched (present keeps no environment block).
    notes_env = {"NOTES_ROOT": notes_root}
    present_env = {"NOTES_ROOT": notes_root}
    if mcp_pythonpath:
        notes_env["PYTHONPATH"] = mcp_pythonpath
        present_env["PYTHONPATH"] = mcp_pythonpath
    present_server = {
        "type": "local",
        "command": [python_executable, "-m", PRESENT_SERVER_MODULE],
        "enabled": True,
    }
    if present_env:
        present_server["environment"] = present_env
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
                "command": [python_executable, "-m", AGENDA_SERVER_MODULE],
                "enabled": True,
                "environment": notes_env,
            },
            "present": present_server,
        },
    }


def parse_model_options(raw: str | None) -> dict | None:
    """Parse a ``MODEL_OPTIONS`` JSON string into a provider-options dict.

    Shared by the dev generator (``notes-mvp/gen_opencode_config.py``) and the
    install wizard (``frontend.setup_wizard``) so the validation lives in one
    tested place. Empty/``None`` → ``None`` (no-op). Raises ``ValueError`` on a
    non-JSON or non-object payload; callers map that to their own UX (the CLI
    generator hard-exits, the interactive wizard warns and continues unpinned).

    This validates *shape* only. Key safety is enforced downstream by
    :func:`build_opencode_config`, which forces ``baseURL`` and neutralizes any
    ``apiKey`` in the merged options — so a pinned dict can neither redirect the
    endpoint nor smuggle a credential into the serialized config.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"MODEL_OPTIONS is not valid JSON: {e}") from None
    if not isinstance(parsed, dict):
        raise ValueError("MODEL_OPTIONS must be a JSON object (e.g. '{\"temperature\": 0}')")
    return parsed
