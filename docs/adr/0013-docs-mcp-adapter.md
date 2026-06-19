# docdag "docs" MCP is an opt-in, own-venv HTTP service, not a stdio child

The optional document-intelligence capability is provided by **docdag-mcp**, a
standalone server consumed as a **pinned sibling checkout** (`../docdag-mcp`, like
`llm-wiki-tools`). Unlike the `notes` and `present` MCP servers — which OpenCode
spawns as **stdio children** (`python -m agenda.server` etc.) — docdag is a
**long-lived HTTP daemon** (server + background worker) that the **launcher**
starts, and OpenCode connects to it as a **`docs` remote MCP** (`{"type":
"remote", "url": …}`). It is **off by default**, enabled per-launch with
`ENABLE_DOCS=1`.

## Context

`docdag-mcp` turns PDF/DOCX/PPTX into a navigable resource DAG with BM25 +
semantic/hybrid search and figure OCR/captions. It carries heavy dependencies
(docling/Torch, onnxruntime) and runs a worker + an HTTP MCP server — a shape
that does not fit OpenCode's stdio-per-`python -m` MCP model, and whose deps we do
not want in agentic-pa's environment. Documents are also a **separate corpus** from
the notes Ground Truth; per the one-service-per-corpus rule (ADR-0007 / CONTEXT.md)
their search is its own service, never federated into `notes_search`.

## Decision

- **Own-venv separate service.** The launcher spawns docdag's **own** venv console
  scripts (`<docdag>/.venv/bin/docdag-server` + `docdag-worker`); agentic-pa never
  imports docdag or installs its deps. `docdag_commands()` resolves `DOCDAG_MCP`
  env or `../docdag-mcp` and returns None (warn, continue) when absent.
- **Opt-in.** `ENABLE_DOCS` (truthy) turns it on. When off/unresolved the launcher
  starts nothing and `_apply_docs_mcp(install_root, None)` removes any `docs` block
  from `opencode.json` — zero impact on existing installs.
- **Remote MCP.** `build_opencode_config(docs_url=…)` (and the launch-time
  `_apply_docs_mcp` patch) add `mcp.docs = {type: remote, url, enabled}` +
  `docs_*: allow`. OpenCode connects over HTTP (FastMCP streamable-http, `/mcp`).
- **Store outside the sandbox (ADR-0005).** `DOCDAG_STORE=<install_root>/docdag-store`
  — never inside `workspace/`. `DOCDAG_ALLOWED_DIRS=<workspace>` so the agent can
  ingest workspace documents but the daemon won't read arbitrary paths. The agent
  reaches documents only through the `docs_*` MCP tools, never the raw store.
- **Endpoint reuse.** docdag's embeddings/vision endpoints reuse the agent's own
  OpenAI-compatible model endpoint (`DOCDAG_EMBED_ENDPOINT`/`DOCDAG_VISION_ENDPOINT`
  = the provider `baseURL` from `opencode.json`). No frontier models.

## Consequences / open items

- The exact OpenCode **remote-MCP config key shape** is assumed (`type: remote`,
  `url`); verify against the installed OpenCode before relying on the end-to-end
  path. The launcher's start/health/connect path is **integration-verified
  manually** (needs a live docdag + model endpoint); the adapter helpers (resolve,
  enable flag, config patch, soft-probe) are unit-tested.
- docdag's HTTP port is set via `FASTMCP_PORT`/`DOCS_PORT` (default 4097); confirm
  docdag-server honors it (FastMCP reads `FASTMCP_*`). `DOCS_URL` overrides the URL.
- *Rejected:* installing docdag editable into agentic-pa's venv (pulls Torch/docling
  in); running docdag as an OpenCode stdio child (wrong lifecycle for a worker +
  HTTP daemon).
