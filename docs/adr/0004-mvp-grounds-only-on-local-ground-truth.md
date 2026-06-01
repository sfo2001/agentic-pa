# The MVP grounds only on the local Ground Truth

The MVP's sole knowledge source is the local **Ground Truth** — the notes the
agent maintains — read via native file tools. The external **Grounding Sources**
defined in *docs/design/workspace-assistant-spec.md* v0.6 (Confluence, Jira, behind MCP
adapters) are deliberately deferred to the future adapter track.

## Context

The spec's original MVP-0 included read-only Confluence grounding. This MVP
removes it from the critical path to focus the first milestone on the novel,
valuable core — the structured-notes loop — and to drop adapter, PAT
authentication, and storage↔Markdown conversion work.

## Consequences

"Grounding Source" is reserved for the external, adapter-backed meaning; the
local layer is the Ground Truth and is **not** a Grounding Source (see
`CONTEXT.md`). Adding Confluence/Jira later is additive — a new adapter — and
does not change the notes layer.
