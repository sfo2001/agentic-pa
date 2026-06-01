# notes-mvp — OpenCode wiring for the Chief-of-Staff Notes assistant

A sandboxed notes agent driven by a local OpenAI-compatible model, with the
read-only Agenda MCP server wired in. The N1 wiring slice — no web frontend yet.

The OpenCode config is **generated locally and gitignored**; no machine-specific
data (paths, host, model) is committed. Only the generator and an env example
are tracked.

## One-time setup

    # 1. Runtime venv for the Agenda MCP server
    python3 -m venv .venv
    .venv/bin/pip install -e ./agenda          # provides `agenda-server`

    # 2. Local config: copy the example, fill in YOUR endpoint + model
    cp notes-mvp/.env.example notes-mvp/.env    # .env is gitignored
    #   edit notes-mvp/.env -> MODEL_ENDPOINT, MODEL_ID (and optional NOTES_ROOT)

    # 3. Generate the local opencode.json (gitignored)
    set -a; . notes-mvp/.env; set +a
    .venv/bin/python notes-mvp/gen_opencode_config.py

## Run the server

**OpenCode 1.15.0 note:** `OPENCODE_CONFIG` is not honoured; config is discovered
by directory-walk from the current working directory. Run from `notes-mvp/` (or
any subdirectory) so OpenCode finds `notes-mvp/opencode.json` automatically.

    cd notes-mvp
    opencode serve --hostname 127.0.0.1 --port 4123

For serve, clients must target the `workspace-assistant` agent (pass `--agent workspace-assistant`
in any `opencode run --attach` invocation, or select the agent in the client UI).

Health: `curl http://127.0.0.1:4123/global/health`.

## One-shot prompt (headless)

    cd notes-mvp/sample-notes          # opencode walks up and finds notes-mvp/opencode.json
    opencode run --agent workspace-assistant "What should I focus on today?"

**Security note:** The sandbox binds to the `workspace-assistant` agent; a top-level
`permission` block denies `bash`/`webfetch`/`websearch`/`task` as defense-in-depth so
the default agent is also restricted.

## Notes

- The agent is sandboxed: `bash`/`webfetch`/`websearch`/`task` denied,
  `external_directory: deny`; native file tools + `notes_*` allowed.
- A top-level `permission` block mirrors the per-agent policy as defense-in-depth
  (the sandbox applies even if the default agent is used by mistake).
- The Agenda server reads its notes tree from `NOTES_ROOT` (set via `.env`,
  default `notes-mvp/sample-notes`).
- The agent sees the agenda tools as `notes_today`, `notes_review`, and
  `notes_topic` (OpenCode prefixes the MCP server key `notes` to the bare
  tool names `today`/`review`/`topic` advertised by the server).
- `notes-mvp/opencode.json` and `notes-mvp/.env` are gitignored — they hold the
  only machine-specific values. The future frontend (N3) will generate the
  config the same way, per install.
