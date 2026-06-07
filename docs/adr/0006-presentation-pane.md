# The presentation pane shows agent-pushed Artifacts via a dedicated `present` MCP server (which also hosts the `propose` tool), rendered server-side as sanitized HTML

The web UI gains a second pane (right) — the **Presentation pane** — that renders an
**Artifact** (a Ground-Truth file or generated draft: a Meeting/MoM, Brief, Topic,
report draft, or uploaded reference) read-only, beside the conversation. Artifacts
get there two ways: the **agent pushes** one by calling a `present(path)` tool, and
the **user opens** one by clicking a workspace path referenced in the chat.

## Context

The current UI is a single conversation column that renders model output with
`textContent` (no HTML) — a deliberate XSS-safe stance, since model output and
markitdown-converted uploads are untrusted. A pane that shows *rendered* MoMs/briefs
needs (a) a way for the **sandboxed** agent (no `bash`, only native file tools + the
read-only `agenda_*` tools) to signal *what* to present, and (b) a way to fetch and
render workspace markdown **safely**. Both touch security boundaries the project
otherwise guards tightly (ADR-0005, the sandbox).

## Decision

1. **Agent push = a dedicated `present(path)` MCP tool**, registered by a **new,
   separate MCP server** (not the Agenda service, which `CONTEXT.md` defines as
   read-only/deterministic and must stay pure). `present()` is a thin signal that
   returns ok; the **relay surfaces the tool-call's input path** (extending today's
   name+status extraction) and emits a new **`present` SSE event**, post-idle (same
   timing as tool chips). *Ruled out:* a `PRESENT:` text-marker convention (simpler,
   but not a structured/auditable tool-call) and inferring from file writes (noisy).

   The same MCP server also exposes a **`propose(proposal)` tool** (see ADR-0009)
   for the propose-confirm ingest flow. The agent calls it as `present_propose`
   (OpenCode namespaces tools as `<server-key>_<toolname>`).

2. **Content is served + rendered server-side.** A read-only `GET /api/file`
   resolves the path within `workspace/` with the same resolve-and-reject-traversal
   guard as `upload.py`, renders markdown→HTML **on the server**, and runs it through
   a server-side HTML sanitizer (e.g. `nh3` — strips `<script>`, event handlers,
   `javascript:` URLs, raw embedded HTML). It returns **safe HTML**; the pane injects
   it. *Ruled out:* client-side rendering (would add JS deps to the dependency-free
   vanilla UI and move the XSS-critical sanitizer into the browser) and raw-text-only
   (no rendered MoMs — defeats the purpose).

3. **User open = clickable workspace paths in the chat**, routed through the same
   `GET /api/file` endpoint. *Deferred:* a file-tree browser.

## Consequences

- This **deliberately relaxes the chat's `textContent`-only stance for the pane**:
  the pane shows server-rendered, sanitized HTML. XSS safety now hinges on the
  server-side sanitizer being correct and kept current — a single trusted choke
  point, by design. The conversation pane stays `textContent`-only.
- A **new MCP server** (dual-tool: `present` + `propose`) + a **new `present` SSE event**
  + relay tool-input extraction + a new read endpoint are added; the Agenda service
  stays read-only/deterministic.
- New Python deps: a markdown renderer + an HTML sanitizer (`nh3`).
- **Could age badly:** if a markitdown-converted upload (or a malicious notes file)
  carries hostile markup, correctness rests entirely on the sanitizer; raw HTML in
  markdown must be stripped, not passed through. Live mid-turn presentation is
  deferred (v1 presents post-idle).
