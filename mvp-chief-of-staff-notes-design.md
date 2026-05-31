# MVP — Chief-of-Staff Notes Assistant — Design

**Status:** Approved design (brainstorm + docs-grilling output)
**Date:** 2026-05-30
**Glossary:** see `CONTEXT.md` · **Decisions:** see `docs/adr/0001`–`0004`
**Relationship to existing docs:** This is the authoritative spec for **Milestone
1** of *workspace-assistant-implementation-plan.md* (v0.3). The north-star
*workspace-assistant-spec.md* (v0.8) is now the **Milestone 2** external-adapter
architecture; its two-role model, OpenCode integration, and security model are
retained and extended here with the structured-notes layer it did not specify.

---

## 1. Purpose

A locally-run, fully-sandboxed agentic assistant that acts as a **chief of staff
for notes and day/week organisation** for a senior leader who runs 8+ meetings a
day across deeply diverse domains (technical, organisational, governance,
programmatic, cross-domain).

It must:

1. **Triage** the day/week — urgent vs. important (Eisenhower).
2. **Capture** meeting notes (raw → structured).
3. **Resurface** important-but-not-urgent and follow-up topics before they rot
   (tickler / review discipline) — *the core pain it solves.*
4. **Maintain a topic-centric ground truth**: topic → meeting → documentation,
   kept coherent and updated by the agentic loop.
5. **Answer questions / draft reports** grounded in that local ground truth.

The agent is the curator of two intertwined layers: a **temporal/task layer**
(daily/weekly triage + follow-ups) and a **persistent topic layer** (the ground
truth knowledge base).

---

## 2. Scope

### 2.1 In scope (MVP)

- Sandboxed OpenCode server (localhost-bound, restricted config).
- **Native-filesystem workspace** = the local `workspace/` tree (no remote workspace).
- **Knowledge source = the local Ground Truth only.** The agent answers and
  drafts from the structured notes it maintains, read via native file tools. No
  external systems. ("Grounding Source" is reserved for the spec's external,
  adapter-backed meaning — future; see `CONTEXT.md` and ADR-0004.)
- **Structured-notes data model** (plain markdown / `todo.txt` — §4).
- A **deterministic agenda engine** (read-only date/surfacing logic — §5).
- An **agenda MCP server** exposing the engine read-only to the agent (§5.3).
- The **agentic loop**: ingest, capture, daily brief, weekly review, query,
  report draft (§6).
- A **Python web frontend** (Open-WebUI-style chat) with notes affordances:
  inbox status, Process-inbox / Daily-brief / Weekly-review buttons, upload (§7).
- Document **upload** with office→Markdown conversion into `workspace/documents/`.
- A launcher (simplified from spec §8).

### 2.2 Out of scope — deferred to future tracks

1. **Architecture C** — a schema-enforcing local notes *write* MCP server
   (this MVP uses architecture **B**; see §3).
2. **External grounding adapters** — Confluence / Jira (spec §11.3/§11.6,
   plan WP6–WP9).
3. **Remote Workspace** + the `ask` write-confirmation flow (spec §11.2/§4.5,
   plan WP8).
4. **Profile mechanism** (spec §6, plan WP3/WP10) — the MVP ships one hardcoded
   configuration.
5. **Calendar integration** (a future "scheduled" store, per the plaintext-
   productivity model).
6. **Rich report / document filling** at high fidelity.
7. **Auto folder-watch** — MVP triggers ingest by button/command.
8. **Visual triage dashboard** — the brief in chat covers it first.

---

## 3. Architecture choice

**Decision: architecture B — plaintext + a deterministic agenda engine.**

The discipline lives where each part is strongest:

- **Code (deterministic):** all date math and surfacing — what is due, what
  resurfaces today, what is stale. The one thing an LLM is unreliable at
  (never silently dropping a date-based follow-up) is guaranteed by code.
- **Agent (language):** parsing raw notes, extracting actions, filing to topics,
  keeping the ground truth coherent, writing briefs, answering questions.

Everything on disk stays plain markdown/text — hand-editable in Notepad++,
greppable, portable, and usable later as a queryable knowledge source.

Rejected for the MVP (recorded as future): **A** (pure prompt-driven — leaves
resurfacing to LLM recall) and **C** (full schema-enforcing write-MCP — strongest
guarantees but most work, and loses the "it's just markdown" property). **C** is
the natural future hardening of **B**.

---

## 4. Data model (on disk)

The agent's **sandbox** (the OpenCode launch directory, confined by
`external_directory: deny`) is the notes tree below — it is a **leaf**. The
install-root that *contains* it holds the config, secrets, prompt, and git
metadata, none of which the agent can reach (§8, ADR-0005). The tree below is the
contents of the sandbox directory (`workspace/` in the install layout):

```
workspace/   (the sandbox — agent-writable)
  inbox/                     raw drop folder; Notepad++ files land here
      2026-05-30-atlas.md
  meetings/                  structured meeting records, dated
      2026-05-30/atlas-sync.md
  topics/                    THE ground truth — one living file per topic
      project-atlas.md
      governance.md
  documents/                 LOCAL readable copies of presentations/docs
      atlas-design.pptx
      atlas-design.pptx.md   (auto-converted sibling)
  briefs/                    agent-generated daily/weekly briefs
      2026-05-30-daily.md
      2026-W22-weekly.md
  tasks.todo.txt             single action list (todo.txt + extensions)
  index.md                   topic map the agent maintains
  archive/                   processed inbox files, closed topics, done tasks
```

**Install layout — the sandbox is a leaf (ADR-0005).** The `workspace/` tree
above lives inside an install-root whose other entries are *outside* the agent's
reach. **Critically, the install-root is NOT a git repository and there is no
`.git` at or above `workspace/`** — OpenCode resolves the agent's reachable scope
as the launch cwd OR the enclosing git work-tree root (§8), so a `.git` in the
parent would expand the boundary to the whole install-root. The notes audit repo
therefore uses a split git-dir named `notes.git/` (not `.git`), which OpenCode's
git detection ignores:

```
<install-root>/        # NOT a git repo; agent cannot reach it
  opencode.json        # generated config (gitignored from the code repo)
  .env                 # secrets (model endpoint, etc.)
  notes-agent.md       # system prompt
  notes.git/           # notes version control (split git-dir; work-tree = workspace/)
  workspace/           # THE sandbox (OpenCode launch dir = NOTES_ROOT) — the tree above
```

Because `workspace/` has no `.git` at or above it, OpenCode sees no git
work-tree and confines the agent to exactly `workspace/` (the launch cwd). The
mechanism is source-verified — see §8.

### 4.1 `tasks.todo.txt`

`todo.txt` syntax plus a thin extension set. The **Eisenhower quadrant maps onto
the priority letter**:

| Letter | Quadrant | Meaning |
|--------|----------|---------|
| `(A)` | urgent + important | do now |
| `(B)` | important, not urgent | schedule — **auto-gets a `t:` tickler** |
| `(C)` | urgent, not important | delegate / quick |
| `(D)` | neither | someday / drop |

Tags: `due:YYYY-MM-DD` (deadline) · `t:YYYY-MM-DD` (resurface-on / tickler) ·
`upd:YYYY-MM-DD` (last-touched — set on create and on every edit; drives the
deterministic staleness check) · `+topic` (links to a topic file) · `@context`
(free tag) · leading `x` = done (moved to `archive/` on review).

```
(A) Sign off Atlas security design +project-atlas @decision due:2026-06-02
(B) Draft Q3 governance proposal +governance t:2026-06-09
(C) Reply to vendor on licensing +procurement due:2026-06-01
```

**Auto-tickler rule:** when the agent files a `(B)` action with no `t:`, it sets
`t:` to **+1 week** by default (user-overridable per item), so it always
resurfaces.

**Action authority (ADR-0002):** `tasks.todo.txt` is the **single source of
truth** for an Action's existence and status. The copies elsewhere are derived:
a meeting's `## Actions` is frozen provenance, a topic's `## Open actions` is a
generated snapshot. They are intentionally not re-synced back into authority.

### 4.2 Meeting record — `meetings/YYYY-MM-DD/<slug>.md`

```markdown
---
date: 2026-05-30
title: Atlas Sync
topics: [project-atlas, governance]      # topic SLUGS (stable identity)
attendees: [optional]
---
## Summary
## Decisions
## Actions          (provenance: what was agreed here — frozen, not the authority)
## Raw notes        (cleaned/preserved original)
```

On filing, each action also enters `tasks.todo.txt` (the authority) with a
`+topic` backlink. The meeting's `## Actions` is never updated afterward.

### 4.3 Topic file — `topics/<slug>.md` (the living ground truth)

```markdown
---
slug: project-atlas          # IMMUTABLE identity — used in filenames, +topic, links
title: Atlas Programme        # mutable human label; renaming this breaks nothing
tags: [technical, delivery]
status: active
---
## Overview
## Current state     (agent keeps this fresh)
## Open questions
## Key decisions
## Meetings          (links, reverse-chronological)
## Documents         (links — local or URL, see §4.4)
## Open actions (as of YYYY-MM-DD)   (generated snapshot; authority = tasks.todo.txt)
```

**Topic identity (slug rule):** the `slug` is the immutable identity set at
creation; the `title` is the mutable human label. `+topic` tags and all links
use the slug, so renaming the title never breaks anything. Merging two topics is
an explicit slug-rewrite operation, never an accidental side-effect of a rename.
The `## Open actions` section is a **stamped snapshot** the agent regenerates
(with an `as of` date) whenever it edits that topic file; the authoritative
answer always comes from the Agenda service / Task list.

**Topics are flat + tags, agent-seeded.** On first run the agent proposes a
topic list derived from existing notes; the user approves/renames. A meeting can
link to several topics. Cross-cutting concerns use tags, not hierarchy.
`index.md` is the rolled-up map across all topics.

### 4.4 Documents and the sandbox boundary

A topic's `## Documents` section mixes two link kinds:

- **Local (readable):** `[Atlas design](../documents/atlas-design.pptx.md)` —
  the agent can `read` it. Files arrive by **chat upload** (frontend stores the
  original and auto-converts PPTX/DOCX/PDF → a `.md` sibling) or by the user
  **dropping** them into `workspace/documents/`.
- **External (pointer only):** `[Confluence page](https://…)` — flagged
  *not-locally-accessible*. The agent is fully sandboxed (`webfetch` denied) and
  **cannot fetch URLs**; they are references for the human. To have the agent use
  a document's content, a local copy must exist in `documents/`.

---

## 5. The agenda engine

A small, deterministic, **read-only** Python module. It parses
`tasks.todo.txt` plus meeting/topic frontmatter and computes the surfacing the
user must never have to remember. It **never writes** — the agent does all
writing.

### 5.1 Computations

- **`today`** →
  - `do_now`: `(A)` items + anything with `due:` ≤ today
  - `schedule`: `(B)` items
  - `resurfacing`: items with `t:` ≤ today
  - `overdue`: items with `due:` < today
  - `stale_important`: `(A)`/`(B)` items untouched > **7 days**
- **`review`** (weekly) → per-topic last-touched; topics with no meeting in
  > **3 weeks** (flagged "still active? archive or resurface?"); open actions per
  topic; ticklers landing this week; suggested promotions.
- **`topic(slug)`** → that topic's open actions, ticklers, recent meetings.

(Thresholds — 7-day stale item, 3-week stale topic — are configuration
constants, tunable later.)

### 5.2 Determinism contract

The engine's output is a pure function of the on-disk files at call time. No LLM
involvement. This is what makes "nothing date-based ever slips" a guarantee
rather than a hope.

### 5.3 Exposure — read-only MCP "agenda" server

The engine is exposed to the agent as a **read-only MCP server** (the agent
cannot shell out — `bash` is denied), with tools:

- `agenda_today()` · `agenda_review()` · `agenda_topic(slug)`

It is **read-only by construction** (the server advertises no write tools — the
same safety property the spec gives its Grounding adapters, though the Agenda
service is *not* a Grounding Source: it serves a computed agenda, not a corpus).
This lets the agent pull a trustworthy agenda in **any** chat turn ("what should
I focus on right now?"), not only during scheduled briefs. The server reads the
sandbox `workspace/` tree directly.

---

## 6. The agentic loop — six verbs

1. **Ingest** — the frontend shows "N new notes" in `inbox/`; on the user's
   **Process inbox** click/command the agent reads each raw file as an **opaque
   capture** and **segments** it into 0..N meetings plus loose items (a fragment
   that is not a meeting becomes a note/action on a topic, not a fake meeting).
   For each meeting it writes a structured record, updates/creates linked topic
   files (by slug), extracts actions into `tasks.todo.txt` (auto-tickler rule),
   and moves the raw file to `archive/`. It **auto-files** the clear cases and
   **asks only when the segmentation or topic is ambiguous**. After filing it
   prints a compact **per-ingest changelog** (e.g. "3 meetings filed, 7 actions
   added, 1 new topic `vendor-x` created — reply 'undo' or correct any"),
   highlighting any new-topic creation. The frontend then commits the `workspace/`
   git repo, so **undo = revert** (§8, ADR-0003).
   *Cold start: if a markdown backlog is dropped in `inbox/`, a one-time seed pass
   proposes a topic taxonomy for approval; otherwise the Ground Truth grows
   forward from day one.*
2. **Capture** — a quick note typed in chat runs the same pipeline, lighter
   (may produce a single action or a mini-meeting record).
3. **Daily brief** — agent calls `agenda_today`, writes `briefs/DATE-daily.md`,
   and presents do-now / schedule / resurfacing.
4. **Weekly review** — agent calls `agenda_review`, proposes re-prioritisation
   and resurfaces stale topics; on user approval it updates tasks/topics.
5. **Query** — answers grounded in local topics/meetings/tasks.
6. **Report draft** — uses the ground truth to draft a document (kept simple in
   the MVP; richer fill is future).

---

## 7. Frontend

Python web app, the spec's Open-WebUI-style chat, chat-first, plus four notes
affordances:

- **Chat** — streaming responses; tool-call events surfaced as readable items
  (e.g. "filed meeting → project-atlas", "3 actions added", "agenda computed").
  **Implementation note (OpenCode 1.15.0 — verified live 2026-05-31):** the
  `/event` SSE stream carries text deltas as `message.part.delta`
  (`properties.field=="text"`, `properties.delta`); the turn ends on
  `session.idle`; tool-call progress is NOT streamed — tool-call events are
  produced by fetching the finished message (`GET /session/{id}/message`) after
  `session.idle`, from the `type:"tool"` parts. The relay (`frontend/events.py`,
  `opencode_client.iter_events`, `proxy.relay`) matches this and is confirmed
  correct against the running server. **The stream must be read with an HTTP
  client that handles chunked `text/event-stream` (the relay uses `httpx`); a raw
  `http.client` reader truncates it.** Full wire schema + evidence:
  `docs/decisions/D-opencode-http.md` (§3, §8).
- **Inbox status** — "N new notes" indicator + **Process inbox** button.
- **Daily brief** and **Weekly review** buttons — send the canned loop prompts.
- **Upload** — PPTX/DOCX/PDF → `.md` into `workspace/documents/`.

The frontend is the sole OpenCode HTTP client and proxies all browser↔OpenCode
traffic (spec §3.2). A visual triage dashboard is a future stretch.

---

## 8. Security model

Inherited from the spec, and **simpler** because there are no remote writes:

- OpenCode bound to `127.0.0.1` only; the browser talks only to the Python web
  server; `OPENCODE_SERVER_PASSWORD` never reaches the browser. **The launcher
  generates a fresh random `OPENCODE_SERVER_PASSWORD` per run** and passes it to
  both `opencode serve` and the frontend, so the localhost OpenCode server is
  **authenticated** — other local processes/users cannot drive the sandboxed
  agent (verified: unauthenticated `/global/health` → HTTP 401 when the password
  is set). The frontend's `opencode_client` sends HTTP Basic auth; the launcher's
  health check sends it too.
- `permission`: `bash`, `webfetch`, `websearch`, `task` → `deny`;
  `external_directory` → `deny`; native file tools (`read`/`write`/`edit`/
  `glob`/`grep`/`list`) → `allow`; `agenda_*` → `allow` (read-only). These
  denials are set both **inside the `workspace-assistant` agent definition and
  at the top level** of `opencode.json` — defense-in-depth, because the default
  (unnamed) agent in OpenCode 1.15.0 is unrestricted.
- All traffic targets the **`workspace-assistant` agent** (bound at session
  creation via `POST /session` with `{"agent":"workspace-assistant"}`).
- **Confinement is anchored to the launch cwd, not to config location.** Source
  (OpenCode 1.15.13, `packages/opencode/src/project/instance-context.ts:18-24`):
  the `external_directory` check passes only if the target is under the launch
  **cwd** (`ctx.directory`) **or** the enclosing **git work-tree root**
  (`ctx.worktree`, from `git rev-parse --show-toplevel`); with no git,
  `worktree === "/"` is skipped, so the boundary is exactly the cwd. The launcher
  starts OpenCode with cwd = the **`workspace/` sandbox** and guarantees no `.git`
  at or above it, so the boundary is `workspace/` precisely. `opencode.json` lives
  one level up in the install-root and is still found by the config walk-up (a
  process-level read, not an agent file-tool call) and stays unreadable by the
  agent (it is outside `workspace/`). The behaviour matches on the installed
  1.15.0 binary (probed).
- **`OPENCODE_CONFIG` is honored (it merges, it does not replace).** An earlier
  note here claimed it was ignored; source (`config/config.ts:601-603`) merges it
  after the global config. We do **not** rely on it for isolation — confinement
  comes from the launch cwd plus an **isolated HOME/XDG** (below), not from where
  the config file sits.
- **Config/skill bleed is closed on BOTH channels — file and env.** OpenCode
  merges the global config (`~/.config/opencode`) and skill directories, and
  skillDirs feed the `external_directory` allow-list (`agent/agent.ts:107-126`).
  The launcher runs OpenCode with (a) a clean HOME/XDG (and `%APPDATA%`/
  `%LOCALAPPDATA%`/`%USERPROFILE%` on Windows) pointed at an install-local
  directory — closing the **file** channel; and (b) an environment with **all
  `OPENCODE_*` variables stripped** (`isolated_env`) — closing the **env** channel
  (notably `OPENCODE_CONFIG`, which OpenCode *merges* and which would otherwise
  leak from the user's shell and could loosen the agent's permission policy). The
  launcher then re-adds only `OPENCODE_SERVER_PASSWORD`.
- **No remote writes anywhere** → the `ask`-confirmation machinery is not needed;
  all writes are local sandbox writes that auto-execute.
- The agent cannot reach the wider filesystem or the internet; the only
  non-model outbound interaction is reading/writing the sandbox `workspace/` tree.

**Sandbox layout (ADR-0005).** The agent's sandbox is a **notes-only leaf**
(`workspace/`); the install-root that contains it holds `opencode.json`, `.env`,
`notes-agent.md`, and the notes git metadata (`notes.git/`, a split git-dir
*not* named `.git`) — all **outside** the sandbox boundary. The install-root is
**not** a git repository and there is no `.git` at or above `workspace/`, so
OpenCode confines the agent to exactly `workspace/` (the launch cwd).
This matters because the agent's native `read`/`write`/`edit` tools are *allowed
inside* the sandbox and `external_directory: deny` only blocks paths *outside* it.
Keeping config/secrets/prompt/git in the unreachable parent closes secret reads,
self-modification of the agent's own permissions/prompt, and tampering with the
version-control audit trail — none of which the "no `bash`" guarantee alone
prevents.

**Versioning (ADR-0003).** The notes `workspace/` is its **own git repo**,
separate from this code repo. The git **metadata lives outside the work-tree** as
a split `--git-dir`/`--work-tree`: the git-dir is `notes.git/` in the install-root
(named so, *not* `.git`, so OpenCode's git detection does not treat the
install-root as a work-tree — §8) and the work-tree is `workspace/`. The
sandboxed agent's file tools can't reach or tamper with it. Because the
agent has `bash` denied *and* can't reach `.git`, the **frontend** commits the
tree after each agent operation (currently the user's prompt as the subject;
mirroring the agent's structured changelog is deferred). This gives durable undo
(revert) and a full audit trail — a frontend responsibility, not an agent
capability.

---

## 9. Component inventory

(★ = new vs. spec v0.7)

| Component | Source |
|---|---|
| OpenCode server + restricted config | spec (minus Confluence; **plus** agenda MCP + notes prompt) |
| Native-FS workspace = `workspace/` tree | spec native-fs adapter |
| Python frontend: OpenCode client / proxy / SSE | spec WP2 |
| Chat UI + notes buttons + upload | spec WP4/WP5 subset + ★ buttons |
| **Agenda service** (deterministic engine, read-only) | ★ new |
| **Agenda MCP server** (`agenda_today/review/topic`) | ★ new |
| **Notes data model + system-prompt conventions** | ★ new |
| **Notes git versioning** (frontend-owned) | ★ new (ADR-0003) |
| Launcher | spec WP1 (simplified) |

---

## 10. Open items to settle in the implementation plan

- The frontend framework choice and the Agenda service's file-parsing library
  (todo.txt parser vs. hand-rolled) — pin in a stack decision record.
- The precise JSON schema returned by `agenda_today/review/topic`.
- The system-prompt conventions that encode the data model (§4) for the agent.
- The per-operation commit-message format for the frontend's notes-repo commits.

*(Resolved during docs-grilling 2026-05-30: terminology, action authority, topic
identity, ingest segmentation, ingest trust model, versioning, cold start,
staleness thresholds — see `CONTEXT.md` and ADR-0001…0004.)*
