# Contributing

## Environment

- **Python 3.12+. Always use a virtualenv** — never `pip install --break-system-packages`.
  ```bash
  python3 -m venv .venv && . .venv/bin/activate
  pip install -e ../llm-wiki-tools -e ./agenda -e ./frontend
  pip install -r agenda/requirements-dev.txt -r frontend/requirements-dev.txt ruff
  ```
- `agenda/` and `frontend/` are separate installable packages; install both editable.
- `llm-wiki-tools` is a **sibling checkout** (`../llm-wiki-tools`), not on PyPI —
  install it editable **first** so the `llm-wiki-tools` dependency of `agenda`/`frontend`
  resolves locally (it backs `notes_search` and the `lwt`-based upload converter).

## Quality gates (must pass before merge)

```bash
ruff check agenda frontend launcher notes-mvp tests
pytest tests/ -q
```
CI runs both on every push and PR (`.github/workflows/ci.yml`). The end-to-end
smoke (`tests/smoke/notes-mvp/run_smoke.py`) needs a live model and is **not** part
of CI — run it locally when touching the launcher/proxy/agent loop.

- **Lint:** `ruff.toml` selects `E,F,I,UP,B` (ignores `E501`, and `B008` for the
  FastAPI `param = File(...)` idiom). Keep new code clean.
- **Tests:** TDD / regression-test-first — when fixing a bug, add the test that
  evidences it first. Don't weaken assertions to make tests pass.

## Git conventions

- **Branch before committing** — never commit directly to `main`. Use a
  `feat/…`, `fix/…`, `docs/…`, `refactor/…`, or `test/…` branch and fast-forward
  (or PR) into `main`.
- **Conventional commit subjects:** `type(scope): summary` (e.g.
  `feat(frontend): …`, `fix(launcher): …`, `docs: …`, `test(smoke): …`).
- **Author identity:** commit with your **GitHub noreply email**, never a personal
  address. Note that `git worktree` shares the main repo's `.git/config` — verify
  the author after each commit (`git log -1 --format=%ae`).
- **No machine-specific local info in the repo:** hostnames, absolute paths, model
  ids, endpoints, and secrets must not be committed. Config is *generated* locally
  (`frontend.config` / `notes-mvp/gen_opencode_config.py`) and the generated
  `opencode.json` / `.env` are gitignored. Commit only generic generators/templates.

## Architecture invariants (don't break these)

- The agent is **sandboxed** to the `workspace/` leaf. There must be **no `.git`
  at or above `workspace/`**; the notes audit repo is a split git-dir named
  `notes.git` (see ADR-0005 / `docs/decisions/D-opencode-sandbox.md`).
- The `agenda` package is **read-only** by construction — it never writes notes.
- The `frontend` package is self-contained: it must not depend on `notes-mvp/`
  (the dependency goes the other way — `notes-mvp` imports `frontend.config`).
- The OpenCode wire event schema is documented in `docs/decisions/D-opencode-http.md`;
  read SSE with `httpx` (raw `http.client` truncates chunked streams).

## AI assistance

This project is developed with AI assistance (Claude Code). Disclose AI-assisted
changes in PR descriptions where material.
