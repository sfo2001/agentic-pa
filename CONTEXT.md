# Chief-of-Staff Notes Assistant

The local, sandboxed agentic assistant that triages a leader's day/week and
maintains a topic-centric body of knowledge from meeting notes. This glossary
defines the language of the notes layer and its boundary with the inherited
*docs/design/workspace-assistant-spec.md* (v0.6) vocabulary.

## Language

**Ground Truth**:
The local, topic-centric body of knowledge the agent maintains and reads from —
the `topics/` files plus the meeting records and tasks that feed them.
_Avoid_: "grounding", "the knowledge base" (ambiguous), "grounding source".

**Grounding Source**:
Reserved for the spec's meaning — an *external*, read-only knowledge backend
behind an MCP adapter (Confluence, Jira). Not present in the MVP; future work.
The local Ground Truth is **not** a Grounding Source and is read via native file
tools, not a grounding adapter.
_Avoid_: using this for anything local.

**Ground Truth service**:
The deterministic, read-only MCP server that computes views and retrieval *over*
the Ground Truth — the **Agenda** tool family (date/surfacing logic) and **wiki
search** (BM25 over the corpus). It serves computed results, **never the corpus
itself**, and never writes. It is **not** a Grounding Source.
_Avoid_: "the Ground Truth" for the service (that is the corpus it reads);
"Agenda service" (agenda is now one tool family, not the whole service);
"grounding server".

**Agenda**:
The date/surfacing tool family of the **Ground Truth service**
(`notes_today / review / topic`): what is due, resurfacing, stale. One family
within the service, not the service itself.
_Avoid_: "Agenda service" for the whole read service (it now also searches).

**Wiki search**:
BM25 keyword retrieval over the **Ground Truth**, exposed as a read tool of the
**Ground Truth service**. The agent *pulls* it when it judges retrieval helps
(not auto-injected); it returns ranked page candidates the agent then reads and
cites. Distinct from a future Grounding Source search (a different, external
corpus — never federated into one ranked list).
_Avoid_: "RAG" (this is pull retrieval, not context-stuffing), "grounding search".

**Action**:
A committed next step with an Eisenhower quadrant (priority letter), optional
`due:` and `t:` (tickler) dates, and a `+topic` link. Its authoritative
existence and status live **only** in the **Task list**.
_Avoid_: "task" (reserve for the list), "todo", "item".

**Task list**:
The single `tasks.todo.txt` file — the sole authority for every Action's
existence and status. A meeting's `## Actions` is frozen provenance; a topic's
`## Open actions` is a view regenerated from the Task list, never hand-edited.
_Avoid_: calling per-topic or per-meeting action copies "the task list".

**Tickler**:
A `t:YYYY-MM-DD` resurface-on date carried by an Action. Untickled `(B)`
(important-not-urgent) Actions auto-get `t:` = +1 week so they cannot rot.
_Avoid_: "reminder", "snooze".

**Topic**:
A long-lived strand of work, with a **stable slug** (immutable identity, used in
filenames, `+topic` tags, and links) and a mutable **title** (human label).
Flat namespace + tags; agent-seeded, user-approved. A Meeting may link several.
_Avoid_: "project" (a Topic may or may not be a project), "category", "folder".

**Meeting**:
A dated record of one gathering — frozen provenance of what was discussed,
decided, and committed. Feeds Topics and the Task list; never retro-edited once
filed.
_Avoid_: "note" (raw input is a note; the filed record is a Meeting), "event".

**Inbox**:
The `workspace/inbox/` drop folder. A file there is an **opaque raw capture** that
may contain 0..N Meetings plus loose items; on ingest the agent segments it,
files the results, and moves the raw file to `archive/`.
_Avoid_: treating one inbox file as exactly one Meeting.

**Brief**:
An agent-generated daily or weekly digest written to `workspace/briefs/`, built from
the Ground Truth service output. The daily Brief shows do-now / schedule / resurfacing;
the weekly Brief drives the review.
_Avoid_: "report" (a report draft is a separate, user-facing deliverable).

**Presentation pane**:
The right-hand pane of the web UI that renders an **Artifact** read-only, beside
the conversation. The agent surfaces Artifacts there; the user can also open one by
selecting a workspace file referenced in the conversation.
_Avoid_: "preview", "viewer", "presentation".

**Artifact**:
A Ground-Truth file or generated draft shown in the **Presentation pane** — a
Meeting (MoM), a Brief, a Topic, a report draft, or an uploaded reference file,
rendered from its markdown. "Artifact" is the *role a file plays when presented*,
not a new kind of entity (the underlying file keeps its own term).
_Avoid_: "presentation"; note a report draft is one *kind* of Artifact, not a synonym.

**Wiki conventions**:
The lightweight wiki layer adopted over the Ground Truth — `[[link]]`
cross-references, **traceability frontmatter** on ingested documents, and a
code-owned **Index**. Layered *onto* the topic/meeting model; it does not replace
it, and there is no separate wiki.
_Avoid_: "the wiki" (these are conventions on the Ground Truth, not a new store).

**`[[link]]`**:
A cross-reference between **topic and meeting pages**, by the target's bare slug
(e.g. `[[atlas-migration-sync]]`). The agent *authors* links (judgment); structural
lint *validates* them (code). Uploaded **documents** are referenced by a plain
markdown link (`[title](documents/<file>)`), **not** a `[[link]]` — they are files,
not slug-pages, and orphan/broken-link lint covers only the curated topic+meeting graph.
_Avoid_: "wikilink", "backlink"; using `[[…]]` for a document or a path-style target.

**Index**:
The code-owned `index.md` — one line per Ground-Truth page, regenerated and
validated deterministically from page frontmatter by the frontend. The agent
never hand-edits it. (No `log.md`: per-turn git history is the operation log.)
_Avoid_: "table of contents"; treating it as agent-maintained.

**Traceability frontmatter**:
The provenance fields a document carries from ingest (source-sha, ingest-backend,
lwt-version, ingested-at). Generated by code at ingest time; never hand-written.
_Avoid_: "metadata" (too broad).

## Relationships

- The agent maintains the **Ground Truth** and reads it via native file tools.
- An **Action**'s state lives only in the **Task list**; meeting `## Actions`
  is provenance, topic `## Open actions` is a generated view.
- The **Ground Truth service** computes over the Ground Truth read-only (Agenda
  views + Wiki search); it never writes.
- The frontend is the sole writer of derived structure — it regenerates the
  **Index** and validates **`[[link]]`**s after a turn changes the Ground Truth.
- **Wiki search** retrieves over the Ground Truth; a future **Grounding Source**
  search would retrieve over a *separate* external corpus — one read service per
  corpus, never federated.
- A **Grounding Source** (future) would be external and read via an MCP adapter,
  distinct from both of the above.

## Flagged ambiguities

- "grounding" was used for (a) the local notes, (b) the topic KB, and (c) the
  agenda server's MCP pattern — resolved: local layer is the **Ground Truth**
  (read natively); "Grounding Source" is external-only; the read layer is the
  **Ground Truth service**.
- "Ground Truth" (the corpus) vs "**Ground Truth service**" (the read-only server
  that computes *over* the corpus) — resolved: the service serves computed
  results, never the corpus, and never writes. The former "Agenda service" is now
  the **Agenda** tool family within that service.
