# agentic-pa M4 — docdag "docs" MCP adapter — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (or executing-plans). Steps use `- [ ]`.

**Goal:** Wire the standalone **docdag-mcp** document-intelligence server into agentic-pa as an **opt-in** `docs` MCP, so the sandboxed chief-of-staff agent can ingest/search/read documents. docdag runs as its **own-venv service** (launcher-managed); OpenCode connects over **HTTP (remote) MCP**.

**Branch:** `feat/m4-docs-adapter` off agentic-pa `main`.

## Decisions (confirmed)
- **Own-venv separate service.** Launcher spawns `docdag-server` + `docdag-worker` from the docdag-mcp sibling checkout's venv; agentic-pa does NOT install docling/torch. docdag-mcp resolved like llm-wiki-tools: `DOCDAG_MCP` env or `../docdag-mcp` sibling.
- **Opt-in, default off.** `ENABLE_DOCS` (truthy) turns it on; otherwise the launcher starts nothing and the `docs` MCP is absent from `opencode.json` (zero impact on existing installs).
- **Store outside the sandbox** (`<install_root>/docdag-store`, never inside `workspace/`; ADR-0005). docdag's embeddings/vision endpoints **reuse agentic-pa's model endpoint**. Agent reaches docs only via `docs_*` MCP tools.

## Architecture note
Existing `notes`/`present` MCPs are **stdio children OpenCode spawns**. docdag is a **long-lived HTTP daemon** the launcher starts; OpenCode connects via a remote MCP URL. ⚠️ The exact OpenCode remote-MCP config key shape (`{"type":"remote","url":…}` assumed) must be verified against the installed OpenCode at integration (spike) — the repo doesn't pin it.

## Files
```
frontend/config.py   # build_opencode_config: optional docs_url -> mcp.docs (remote) + docs_* perm
launcher/run.py      # docdag resolution, ENABLE_DOCS, opencode.json docs-MCP patch, HTTP soft-probe, spawn+health+shutdown
docs/adr/0013-docs-mcp-adapter.md   # NEW
README.md / CONTRIBUTING.md          # docs adapter usage + sibling checkout
tests/frontend/test_config.py, tests/launcher/test_preflight.py  # unit tests
```

## Tasks

### Task M4.1 — config: optional docs remote MCP
**Files:** `frontend/config.py`; test `tests/frontend/test_config.py`
- [ ] Add `docs_url: str | None = None` to `build_opencode_config`. When set: add `cfg["mcp"]["docs"] = {"type": "remote", "url": docs_url, "enabled": True}` and `permission["docs_*"] = "allow"` (both top-level and agent permission blocks). When None: config byte-identical to before.
- [ ] Tests (TDD): docs block present + `docs_*` allow iff `docs_url`; absent when None (backcompat `_cfg() == _cfg(docs_url=None)`); url echoed. Commit: `feat(config): optional docs remote MCP block`

### Task M4.2 — launcher: docdag resolution + flag + helpers
**Files:** `launcher/run.py`; test `tests/launcher/test_preflight.py`
- [ ] `docs_enabled() -> bool`: parse `ENABLE_DOCS` (1/true/yes/on). Test.
- [ ] `docdag_commands(install_root) -> tuple[list,list] | None`: resolve `DOCDAG_MCP` env or `<repo-parent>/docdag-mcp`; require `<docdag>/.venv/bin/docdag-server` and `docdag-worker` exist (or `<venv>/bin/python -m docdag.server/.worker`); return `(server_argv, worker_argv)` or None if unresolved. Tests: resolves when present (tmp fixture dirs), None when missing.
- [ ] `_soft_probe_docs(url, *, opener=_http_get) -> str | None`: HTTP GET the docs health/MCP URL; warn-only reason or None. Mirror `_soft_probe_model` (injectable opener; fail-closed to a warn). Tests: ok / unreachable.
- [ ] `_apply_docs_mcp(install_root, docs_url | None)`: atomic patch `opencode.json` (mirror `_apply_restrict_write`): add the docs remote MCP + `docs_*` perm when url given, remove when None. Tests: adds/removes; idempotent; atomic.
Commit: `feat(launcher): docdag resolution, ENABLE_DOCS, docs-MCP patch + soft-probe`

### Task M4.3 — launcher main(): start docdag when enabled
**Files:** `launcher/run.py` (main)
- [ ] When `docs_enabled()` and `docdag_commands` resolves: set env (`DOCDAG_STORE=<install_root>/docdag-store`, `DOCDAG_EMBED_ENDPOINT`/`DOCDAG_VISION_ENDPOINT`=the model endpoint from opencode.json, `DOCDAG_ALLOWED_DIRS=<workspace>`); spawn worker + server (server on `DOCS_PORT`, default 4097); `_wait_health` the docs URL; `_apply_docs_mcp(install_root, docs_url)` BEFORE opencode starts; add both procs to the shutdown list; warn-only soft-probe. When disabled or unresolved: `_apply_docs_mcp(install_root, None)` and start nothing (warn if `ENABLE_DOCS` set but unresolved).
- [ ] This is integration wiring (not unit-tested, like the existing opencode/frontend spawn). Manual verify with a live docdag + model endpoint.
Commit: `feat(launcher): start docdag service + wire docs MCP when ENABLE_DOCS`

### Task M4.4 — ADR + docs + gate
- [ ] `docs/adr/0013-docs-mcp-adapter.md`: HTTP-MCP daemon (vs stdio children), store-outside-sandbox, one-service-per-corpus (docs is its own corpus, not federated with notes_search), opt-in, own-venv. 
- [ ] README/CONTRIBUTING: docs adapter (ENABLE_DOCS, DOCDAG_MCP sibling, endpoint reuse). Run `ruff check …` + `pytest tests/ -q`. Commit: `docs: M4 docs-adapter ADR + usage; M4 complete`. Then PR review vs main.

## Notes
- Unit-test the helpers + config (offline, injected opener); the process spawn/health/HTTP-MCP handshake is integration (manual). Honors ADR-0005 sandbox + one-service-per-corpus.
- Verify the OpenCode remote-MCP config shape against the installed OpenCode before relying on the end-to-end path (spike in M4.1).
