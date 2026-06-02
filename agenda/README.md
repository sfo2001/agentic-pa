# Ground Truth Service

Deterministic, read-only service over the local notes Ground Truth (the
broadened Agenda service). Exposes bare MCP tool names `today`, `review`,
`topic`, `search` (read-only); OpenCode registers them as `notes_today`,
`notes_review`, `notes_topic`, `notes_search` (server key `notes`). It never
writes. `search` is BM25 keyword retrieval over the Ground Truth, backed by
`llm-wiki-tools`.

## Install

    python3 -m venv .venv
    .venv/bin/pip install -e ./agenda

## Test

    .venv/bin/pip install -r agenda/requirements-dev.txt   # pytest + pytest-cov
    .venv/bin/pytest tests/agenda/ -v

Coverage (pytest-cov is declared in `agenda/requirements-dev.txt`):

    .venv/bin/pytest tests/agenda/ --cov=agenda --cov-report=term-missing

## Run as an MCP server

The server reads the notes directory from the `NOTES_ROOT` environment variable
and speaks MCP over stdio (it is launched by OpenCode, not run standalone).
OpenCode spawns it via the interpreter — `python -m agenda.server` — which is the
canonical form; the `agenda-server` console script runs the same `main()`:

    NOTES_ROOT=/path/to/notes python -m agenda.server      # canonical (how OpenCode launches it)
    NOTES_ROOT=/path/to/notes .venv/bin/agenda-server      # equivalent console-script form

The server advertises bare tool names `today`, `review`, `topic`, `search`;
OpenCode registers them as `notes_today`, `notes_review`, `notes_topic`,
`notes_search` under the server key `notes` (config delivered by the OpenCode
integration plan).
If `NOTES_ROOT` is unset it defaults to the current working directory; OpenCode always sets it explicitly.

## Thresholds (config constants, agenda/engine.py)

- `STALE_ITEM_DAYS = 7` — an incomplete A/B action whose `upd:` date is older
  than this is reported in `stale_important`.
- `STALE_TOPIC_DAYS = 21` — a topic with no meeting newer than this (or none at
  all) is reported as stale in the weekly review.
