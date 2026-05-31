# llm-wiki-tools is consumed as a library to add wiki conventions over the Ground Truth, and the read-only Agenda server broadens into a Ground Truth service

The notes assistant gains document **ingest** (with traceability frontmatter),
BM25 **search**, and structural **lint** by depending on the sibling
`llm-wiki-tools` (`lwt`) package **as a library**. These land as a *conventions
layer* over the existing topic/meeting/task **Ground Truth** — not a new
substrate — and the read-only Agenda MCP server broadens to host search,
becoming the **Ground Truth service**.

## Context

The Ground Truth had no content search, no structural integrity check, and only
a `markitdown`-based upload converter (no traceability, no sectioning, no
web/Confluence sources). `lwt` provides all three as a clean, importable Python
API (`llm_wiki.ingest / .search / .lint`).

Two constraints shape *where* each capability can live:

- The agent is sandboxed with **no shell** (ADR-0005, `config.py` `bash: deny`),
  so it cannot run `lwt`. Agent-facing capabilities must be MCP tools; everything
  else runs in the frontend (which has Python and owns the notes git, ADR-0003).
- The Agenda server is defined as **read-only / deterministic** (ADR-0001,
  CONTEXT.md). ADR-0006 deliberately kept the side-effecting `present()` tool
  *out* of it to preserve that purity.

## Decision

1. **Adopt conventions; do not merge substrates.** The model stays topics +
   meetings + `tasks.todo.txt` (the Task list remains the sole action authority,
   ADR-0002). `lwt`'s `[[link]]`s, traceability frontmatter, and a code-owned
   `index.md` are layered *on top*. *Ruled out:* making the notes an `lwt` wiki
   (would rewrite the model and threaten the deterministic agenda contract).

2. **Consume `lwt` as a library**, not a subprocess or a vendored copy. Same
   venv, direct imports, fully unit-testable, and we stay on `lwt`'s upstream
   roadmap (qmd, manifest). *Ruled out:* shelling out to the `lwt` binary
   (stdout-parsing fragility, PATH dependence) and vendoring (hard fork).

3. **Broaden the Agenda server into the Ground Truth service.** It now hosts the
   `notes_*` family (the date tools, renamed from `agenda_*`) **and** `notes_search`.
   This is consistent with ADR-0006, not
   a reversal: `notes_search` is **read-only and deterministic** (so it belongs in
   the pure read server), whereas `present()` is a side-effecting signal (so it
   correctly stayed out). The unifying rule is *one read service per corpus* —
   not one tool family per server. *Ruled out:* a separate `wiki` MCP server
   (invents a process boundary that maps to no real concept; same corpus, same
   read-only contract).

4. **`index.md` is code-owned; `log.md` is not adopted.** The frontend
   regenerates and validates `index.md` deterministically from page frontmatter
   after a structural turn — code guarantees it never drifts, rather than relying
   on the agent to maintain it. `log.md` is dropped: the per-turn `CHANGELOG:` →
   git commit (ADR-0003) already is the operation log. *Ruled out:* `lwt`'s
   LLM-owned index/log (reintroduces structural bookkeeping the project gives to
   code).

5. **Lint is frontend-push, not an agent tool.** The frontend runs lint after
   structural turns, **auto-fixes mechanical issues** (trailing newlines) silently
   and surfaces only the **judgment** findings (orphans, broken/ambiguous links).
   The agent never has to remember to lint — mirroring how the agenda engine
   guarantees dates never slip. Lint is therefore a library call, not an MCP tool.

6. **One read service per corpus; cite provenance.** `notes_search` answers over
   the Ground Truth only. A future Confluence/Jira **Grounding Source** (M2) is a
   *separate* tool over a *separate*, external, read-only corpus — never federated
   into one ranked list. The agent cites which corpus an answer came from.

## Consequences

- The agent gains a capability (`notes_search`) while **losing** bookkeeping
  (index/log) — fewer ways for structure to silently drift.
- ADR-0005's sandbox is untouched: every `lwt` capability is either a read-only
  MCP tool or a frontend library call; the agent never gets a shell.
- New runtime artifacts written *into* the notes tree — the BM25 cache
  (`.lwt_cache/`) and ingest temp (`.tmp/`) — must be gitignored (the frontend
  owns notes git).
- The corpus model makes the M2 Grounding Source a clean addition, not a retrofit;
  `lwt`'s Confluence **ingest** (snapshot into the Ground Truth) stays distinct
  from M2's live grounding-search.
- **Could age badly:** OpenCode namespaces MCP tools by server key, so the unified
  service uses a single tool prefix — resolved by renaming the server key to
  `notes` (tools `notes_today/review/topic/search`; the `agenda_*` names were
  retired, package/entry-point `agenda` unchanged). A version coupling to `lwt` is
  introduced; a breaking change
  in its `ingest/search/lint` API would require a coordinated bump.

## References

- Design spec: `docs/superpowers/specs/2026-05-31-llm-wiki-integration-design.md`
- Builds on ADR-0001 (deterministic engine), ADR-0002 (task authority),
  ADR-0003 (frontend owns git), ADR-0005 (sandbox), ADR-0006 (read-server purity).
