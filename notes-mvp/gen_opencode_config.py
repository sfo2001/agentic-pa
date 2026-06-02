#!/usr/bin/env python3
"""Generate notes-mvp/opencode.json from local environment values (dev helper).

The config builder and the canonical system prompt now live in the installable
``frontend`` package (``frontend.config``); this script is a thin dev wrapper that
reads the model endpoint/id from the environment and writes notes-mvp/opencode.json
for local experimentation against notes-mvp/sample-notes. Committed and generic:
the GENERATED opencode.json is gitignored and may carry machine-specific values —
those never enter git.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from frontend.config import CANONICAL_PROMPT_PATH, build_opencode_config

HERE = Path(__file__).resolve().parent            # notes-mvp/


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"Missing required env var: {name} (see notes-mvp/.env.example)")
    return val


def main() -> None:
    model_endpoint = _required("MODEL_ENDPOINT")
    model_id = _required("MODEL_ID")
    # Treat empty values as unset so a blank env var falls back to the dev default.
    notes_root = os.environ.get("NOTES_ROOT") or str(HERE / "sample-notes")
    # The MCP servers run as `python -m <module>` (see frontend.config); use this
    # interpreter by default. PYTHON lets a dev point at a different venv.
    python_executable = os.environ.get("PYTHON") or sys.executable
    # Optional: authenticated dev endpoints. When API_KEY is set, apiKey is
    # omitted from the generated opencode.json (production stores it in opencode's
    # auth.json; this dev helper only needs to keep the config valid for an
    # authed endpoint). Treat empty as unset.
    api_key = os.environ.get("API_KEY") or None

    config = build_opencode_config(
        model_endpoint=model_endpoint,
        model_id=model_id,
        notes_root=notes_root,
        python_executable=python_executable,
        prompt_path=str(CANONICAL_PROMPT_PATH),
        api_key=api_key,
    )
    out = HERE / "opencode.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
