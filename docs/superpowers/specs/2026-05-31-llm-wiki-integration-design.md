# Integrating llm-wiki-tools into the Chief-of-Staff Notes Assistant

**Status:** Implemented and merged to `main` (2026-05-31). Build plan:
`docs/superpowers/plans/2026-05-31-llm-wiki-integration.md`.
**Session goal:** scope + design + ADR + build plan only; write no production code.
**Companion ADR:** `docs/adr/0007-wiki-conventions-and-ground-truth-service.md`.

## Summary

`llm-wiki-tools` (`lwt`) is a sibling Python package (`../llm-wiki-tools/`) that
provides exactly the three capabilities the notes assistant currently lacks over
its **Ground Truth**: document → markdown **ingest** (pdf/docx/pptx/web/Confluence
with traceability frontmatter), BM25 **search**, and structural **lint** (broken
`[[links]]`, orphans, missing index entries). This design wires those in **as a
library**, while keeping the existing topic/meeting/task model and every existing
ADR boundary intact.

The integration adds a *wiki-conventions layer* (`[[links]]`, traceability
frontmatter, a code-owned `index.md`) over the existing Ground Truth, broadens the
read-only Agenda MCP server into a **Ground Truth service** that also answers
`notes_search`, and gives the frontend a deterministic post-turn housekeeping pass
(index regeneration + lint). The agent gains one new tool (`notes_search`) and a
thinner bookkeeping burden, not a new paradigm.

## Approved decisions

1. **Adopt conventions, don't merge substrates.** The Ground Truth stays
   topics + meetings + `tasks.todo.txt`; the Task list stays the sole action
   authority (ADR-0002). `lwt`'s wiki conventions (`[[links]]`, traceability
   frontmatter, `index.md`) are layered *on top*, not substituted for the model.
2. **Consume `lwt` as a library.** Add `llm-wiki-tools` as a pip dependency in
   the same venv; `import llm_wiki.ingest / .search / .lint` directly. No
   subprocess, no PATH dependence, fully unit-testable.
3. **`index.md` is code-owned; drop `log.md`.** `index.md` is deterministically
   regenerated/validated from topic + meeting frontmatter by the frontend — code
   guarantees it never drifts. `log.md` is **not adopted**: the frontend already
   commits per turn using the `CHANGELOG:` line (ADR-0003), which supersedes it.
4. **One read service per corpus; cite provenance.** `notes_search` answers over
   the **Ground Truth** only. A future Confluence/Jira **Grounding Source** (M2)
   is a *separate* tool over a *separate*, external, read-only corpus — never
   federated into one ranked list. The agent cites which corpus an answer came
   from.
5. **Unify the read-only deterministic tools.** Broaden today's read-only Agenda
   MCP server into a **Ground Truth service** hosting the **Agenda** date tools
   **and** `notes_search`. They are the same kind of thing — deterministic, read-only,
   over one corpus, one `NOTES_ROOT`. (CONTEXT.md term "Agenda service" broadens
   accordingly.)
6. **Lint is frontend-push, not an agent tool.** The frontend runs lint
   deterministically after structural turns (like it auto-commits git),
   auto-fixes mechanical issues (trailing newlines/whitespace) silently, and
   surfaces only the *judgment* findings to the agent/user. The agent never has
   to remember to lint.

## The deterministic / language split

The project's founding principle (ADR-0001): code guarantees structure, the LLM
handles language. Applied to the wiki layer:

| Wiki concern | Deterministic (code) | Surfaces to the LLM |
|---|---|---|
| Traceability frontmatter (source-sha, backend, version, ingested-at) | Generated at ingest. The LLM never hand-writes a SHA. | — |
| `[[links]]` | *Validation* — does the target exist? (lint) | *Authoring* — which topics relate? (filing) |
| Lint findings | *Detection* of broken links / orphans / missing-index entries; **mechanical** fixes (newlines) applied silently | Only **judgment** cases: "orphan topic X — link where?", "broken `[[link]]` — typo or page to create?" |
| `index.md` | Regenerated + validated from frontmatter | — |
| Search | BM25 index + ranking → candidate paths | Query formulation, relevance judgment, synthesis, citation |

Two principles fall out: **lint is a detector, not a fixer** (the agent sees only
the judgment subset, exactly as the agenda engine surfaces only what needs a
decision), and **search is pull, not push** (an MCP tool the agent calls when it
judges retrieval helps — not auto-RAG that stuffs every turn's context).

## Architecture

```
                         ┌─ frontend (Python, owns notes git) ───────────────┐
 upload (pdf/docx/pptx) ─►│ upload.py ── lwt ingest handler (library) ──► .md │
                         │ post-turn housekeeping:                            │
                         │   • regenerate index.md (deterministic)            │
                         │   • lint (llm_wiki.lint): auto-fix mechanical,     │
                         │     surface judgment findings to agent/user        │
                         │   • commit (existing CHANGELOG → git)              │
                         └────────────────────────────────────────────────────┘
 sandboxed agent ── MCP ─► Ground Truth service  (read-only, deterministic)
                            • notes_today / review / topic   (existing, renamed from agenda_*)
                            • notes_search                    (NEW: llm_wiki.search)
 agent prompt + CONTEXT.md + templates ── teach [[links]] + frontmatter; index is code-owned
 (separate)   ── MCP ─► present server  (Presentation-pane signal, ADR-0006 — unrelated)
 (M2, deferred) ── MCP ─► Grounding Source adapter (external Confluence/Jira, read-only)
```

> As-built note: the server key is `notes` (so the agent sees `notes_*`), and this
> service coexists with the separate read-only `present` MCP server (ADR-0006).
> `present` stays out of the Ground Truth service because it is a side-effecting
> signal, not a deterministic read — consistent with this design's purity rule.

The sandbox boundary (ADR-0005) is unchanged: the agent still has no shell.
Everything `lwt` does is either an MCP read tool (`notes_search`) or a frontend
library call (ingest, index, lint) — never a shell-out from the agent.

## Components & file-level changes

| File | Change | Detail |
|---|---|---|
| `pyproject` (frontend/agenda) | dependency | Add `llm-wiki-tools` (sibling path / wheel) to the relevant package deps. |
| `frontend/upload.py` | modify | Replace `markitdown_convert` with an `lwt`-backed converter behind the existing `convert(bytes, suffix) -> str` seam. Thin adapter: temp-file → `llm_wiki.ingest` handler → markdown body (+ traceability frontmatter). Pure swap; `store_upload` unchanged. |
| `agenda/server.py` → Ground Truth service | modify | Register `notes_search(query, n)` alongside the renamed `notes_*` date tools, backed by `llm_wiki.search.search(NOTES_ROOT, query, n)`. Read-only contract preserved. |
| `frontend/config.py` | modify | Rename the MCP server key `agenda`→`notes` and the permission `agenda_*`→`notes_*`; the allow-list gains the search tool under that one key. |
| `frontend/` housekeeping (new module) | add | Post-turn deterministic pass: regenerate `index.md` from frontmatter; run `llm_wiki.lint.lint_structural` + mechanical auto-fix; surface judgment findings. Invoked where the per-turn git commit already happens. |
| `frontend/assets/notes-agent.md` | modify | Teach `[[links]]` authoring + traceability-frontmatter expectations + `notes_search` usage + "index.md is generated, never hand-edit". Fold in language from `lwt`'s `query.md`. Remove any implication the agent maintains an index/log. |
| notes-tree `.gitignore` | modify | Ignore `.lwt_cache/` and `.tmp/` (BM25 cache + ingest temp; written into the notes tree, must not be committed). |
| `CONTEXT.md` | modify | Broaden "Agenda service" → "Ground Truth service"; add terms: **wiki conventions**, **`[[link]]`**, **index** (code-owned), **traceability frontmatter**; sharpen Ground Truth vs Grounding Source as the search-corpus boundary. |
| `docs/adr/0007-*.md` | add | "Wiki conventions over the Ground Truth + the read-only Agenda server broadens into a Ground Truth service." |
| tests | add | See Testing. |

## Data flows

- **Ingest:** upload → `upload.py` writes raw + `<name>.md` (now via `lwt`
  handler, gaining sectioning + traceability frontmatter; web/Confluence sources
  become reachable later) → agent reads it, files into topics/meetings, links it
  from `## Documents`. *Agent behavior unchanged; better markdown.*
- **Search:** agent calls `notes_search("atlas migration")` → ranked Ground-Truth
  paths + snippets (index scoped to the Ground Truth, **excluding** `archive/`
  and `briefs/`) → agent reads top hits → grounded, cited answer.
- **Housekeeping (post-turn, frontend):** on any turn that changed structure →
  regenerate `index.md`; run lint; silently fix mechanical issues; surface
  judgment findings; commit via the existing CHANGELOG→git path.

## Provenance & corpus model

The unifying rule is **one read service per corpus**:

- **Ground Truth** (local, owned, writable) → the broadened read service
  (`notes_today/review/topic`, `notes_search`). Answers are authoritative.
- **Grounding Source** (M2; external Confluence/Jira, read-only, behind an MCP
  adapter) → its own separate tool. Answers are external and cited as such.

Corpora are never federated into one ranked list — that would erase the
provenance distinction CONTEXT.md exists to enforce. Note also that `lwt`'s
Confluence **ingest** (snapshot a page *into* the Ground Truth as a local copy)
is a *different* operation from M2's live **grounding-search** (query Confluence
read-only, never copied); both may reuse `lwt`'s Confluence client, but they are
distinct features. `notes_search` shares only the *tool interface* with M2, so M2
slots in cleanly later.

## M1 scope & non-goals

**In:** ingest swap, `notes_search` (Ground Truth service), frontend lint +
index regeneration, conventions layer, CONTEXT.md + ADR-0007.

**Deferred (explicit non-goals, with triggers):**
- `lwt deploy` (mkdocs/docker/confluence) — the notes are private/local and the
  Presentation pane (ADR-0006) already renders them. *Trigger:* a need to publish
  the notes externally.
- `lwt update` / manifest / three-way merge — `lwt`'s own distribution story,
  irrelevant while we vendor via dependency. *Trigger:* we ship `lwt`-scaffolded
  wikis to others.
- **qmd semantic search** — `lwt`'s own ROADMAP gates this at ~200–300 pages.
  *Trigger:* missed-search complaints once the Ground Truth is large.
- **Confluence Grounding Source (M2)** — the north-star external grounding track;
  out of this integration's scope but kept forward-compatible by the corpus model.

## Testing

- **Unit:** ingest adapter (bytes+suffix → markdown with frontmatter);
  `notes_search` MCP tool over a fixture notes tree (known query → expected
  topic/meeting path); index regeneration (frontmatter set → expected
  `index.md`); lint judgment-surfacing vs mechanical auto-fix; config/permission
  builder includes the search tool.
- **Regression canary:** a seeded notes tree where (a) a known query returns the
  expected topic and (b) a deliberately-broken `[[link]]` is caught by lint and
  surfaced — guards against silent-fallback regressions the mocked unit tests
  can't see.

## Implementation questions — resolved during the build

1. **MCP tool prefix** → **resolved: rename to `notes_*`.** One server, server key
   `notes`; the agent sees `notes_today / review / topic / search`. The `agenda_*`
   names were retired (prompt + permissions + launcher + tests updated). The
   Python package stays `agenda/` and the `agenda-server` entry point is unchanged
   — only the agent-visible server key changed.
2. **Ingest frontmatter shape** → **resolved: full `lwt` traceability frontmatter.**
   `upload.py::lwt_convert` captures it via `ingest_source(output="-")` stdout mode.
3. **Search scoping** → **resolved: post-filter in the `notes_search` tool.** It
   over-fetches then drops `archive/` and `briefs/` paths — no upstream `lwt`
   change needed (`agenda/server.py`).

## Why this design ages well

- The agent gains capability while *losing* bookkeeping (index/log) — fewer ways
  for structure to silently drift.
- Every `lwt` capability lands on the correct side of the sandbox boundary
  without weakening it (ADR-0005 untouched).
- The corpus model makes the M2 Grounding Source a clean addition, not a
  retrofit.
- Consuming `lwt` as a library keeps us on its upstream roadmap (qmd, manifest)
  for free, rather than forking.
