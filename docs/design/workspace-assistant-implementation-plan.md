# Agentic Workspace Assistant — Implementation Plan & Acceptance Criteria

**Status:** Companion to two specs — *Chief-of-Staff Notes Assistant*
(`mvp-chief-of-staff-notes-design.md`, **Milestone 1**) and *Agentic Workspace
Assistant — System Specification* **v0.8** (north-star, **Milestone 2**)
**Plan version:** 0.3
**Last updated:** 2026-05-30

> **Revision note (v0.3 — consolidation, 2026-05-30):** **Milestone 1 is
> redefined.** The first shippable product is no longer "MVP-0 = Confluence
> grounding + local notes"; it is the **Chief-of-Staff Notes MVP** — a local-only
> structured-notes assistant, specified authoritatively in
> `mvp-chief-of-staff-notes-design.md` and decomposed below into work packages
> **N0–N7**. The former MVP-0 section is removed (superseded by ADR-0004:
> grounding is local-only in the MVP). The original **WP0–WP10** track is
> retained verbatim as **Milestone 2 — external adapters & profiles** (Confluence,
> Jira, the profile mechanism), now framed as future work, not the MVP.
> Terminology follows `CONTEXT.md` (Grounding Source = external; the local corpus
> is the Ground Truth). See ADR-0001…0004.

> **Revision note (v0.2):** Added an explicit **MVP-0** milestone (live Confluence
> grounding + local notes). *Superseded by v0.3* — see above.

> **Implementation note (verified OpenCode 1.15.0, 2026-05-30):** All WP
> descriptions in this plan reflect empirically-verified OpenCode 1.15.0
> behavior: the launcher sets CWD (not `OPENCODE_CONFIG`); the SSE `/event`
> stream carries text deltas only (not tool progress); agent binding is
> session-level; the `opencode.json` carries a top-level `permission` block as
> defense-in-depth. Details in `workspace-assistant-spec.md` v0.8 and
> `docs/decisions/D-opencode-http.md`.

This document decomposes two specs into delegatable **work packages (WP)** and
per-WP **tasks (T)**, each with explicit pass criteria. It is written so a less
capable implementing agent can execute **one work package** correctly with only
that WP's section, the frozen `contracts/` files, and (for rationale only) the
relevant spec. The spec says *why*; this plan says *what to build, in what order,
and how to know it is done*. **Milestone 1 (N0–N7)** builds the notes MVP;
**Milestone 2 (WP0–WP10)** builds the north-star external-adapter architecture.

---

## 0. How to use this document

### 0.1 Roles

- **Lead** (a capable agent, or the human): owns WP0, freezes the contracts,
  assigns WPs, and runs each package Acceptance Gate before marking a WP done.
- **Implementing agent**: a less capable sub-agent assigned exactly **one WP**.
  It receives that WP's section, the `contracts/` directory, and the spec.
- **Verifier**: runs the Acceptance Gate. May be the Lead or a separate agent.

### 0.2 Pass criteria are layered

- **Definition of Done (DoD)** — attached to each *task*. Structural, checkable
  without judgement: a file exists at a path, a function has an exact signature,
  a command exits 0, no `TODO`/`FIXME`/stub remains. An implementing agent
  self-checks DoD before declaring a task complete.
- **Acceptance Gate** — attached to each *work package*. Behavioural, in
  Given / When / Then form. The Verifier runs it; **all** gate items must hold
  for the WP to be accepted. A WP is not "done" until its gate passes.

### 0.3 Build order

*(This covers **Milestone 2** — the external-adapter WP0–WP10 track. **Milestone 1**
— the Chief-of-Staff Notes MVP (N0–N7) — has its own build order in its section
below and ships first.)*

```
WP0  (contracts) ── must complete and be FROZEN before any other WP starts
  │
  ├─► WP1  Launcher                ─┐
  ├─► WP2  Frontend: OpenCode core ─┤
  ├─► WP3  Frontend: config-gen    ─┤ may run in parallel
  ├─► WP5  Frontend: upload+errors ─┤
  ├─► WP6  Confluence core         ─┤
  └─► WP9  Jira grounding          ─┘
            │
  WP4  Frontend: chat UI        depends on WP2
  WP7  Confluence grounding     depends on WP6
  WP8  Confluence workspace     depends on WP6
            │
  WP10 Profiles & integration   depends on WP1–WP9
```

A WP may start only when **every** WP it depends on has passed its Acceptance
Gate. WP0 is the single hard serialization point; after it, six WPs parallelise.

### 0.4 Global rules for implementing agents (MANDATORY)

These reduce the predictable failure modes of less capable agents. An
implementing agent **MUST**:

1. **Stay in scope.** Create and modify **only** the files listed under its WP's
   *Deliverables*, at exactly those paths. Do not create extra files. Do not
   touch other WPs' code or the `contracts/` files.
2. **Treat `contracts/` as read-only and authoritative.** Every tool name,
   function signature, JSON schema, env-var name, and file path comes from
   `contracts/`. If a contract appears wrong, insufficient, or contradictory,
   **STOP** and emit a single line `BLOCKED: <WP-id> <precise problem>`. Do not
   edit the contract. Do not improvise an alternative.
3. **Match signatures byte-for-byte.** Public tools, functions, and emitted file
   structures MUST match the contract exactly (names, parameters, return shape,
   key casing).
4. **Leave nothing unfinished.** No `TODO`, `FIXME`, `pass  # stub`, `raise
   NotImplementedError`, commented-out code, or placeholder return values in
   delivered files.
5. **Not be clever.** No refactors beyond the WP scope, no new abstractions, no
   dependencies beyond the WP's declared allowlist, no behaviour the WP did not
   ask for. When the WP is silent on a detail, choose the simplest option that
   satisfies the contract and record it in a one-line comment.
6. **Honour the security model.** No network calls except to the WP's declared
   backend/endpoint. No shelling out unless the WP is the launcher. Secrets only
   from environment variables — never hardcoded, never logged.
7. **Self-verify.** Before declaring a task done, confirm every DoD item.
   Before declaring the WP done, confirm every Acceptance Gate item or hand off
   to the Verifier with a gate report.

### 0.5 Handling unknowns — spike tasks

Where the spec has a genuine unknown (an external API surface, a library
choice), the WP contains a **spike task** whose deliverable is a short
*decision record* (`docs/decisions/<id>.md`, ~1 page: options, choice, reason).
A build task that depends on a spike **MUST NOT start** until the spike's
decision record exists. This prevents weak agents improvising around unknowns.

### 0.6 Repository layout (fixed by WP0/T0.1; all WP paths assume it)

```
/contracts/                 frozen interface contracts (WP0, N0)
/docs/decisions/            decision records from spike tasks
/docs/adr/                  architecture decision records (0001–0004)
/agenda/                    N2  Agenda service (engine + MCP)
/notes-mvp/                 N1  opencode.json + notes-agent.md (static config)
/launcher/                  N6 / WP1
/frontend/                  N3–N5 / WP2–WP5  (incl. notes git versioning)
/adapters/confluence/       WP6–WP8  (Milestone 2)
/adapters/jira/             WP9      (Milestone 2)
/profiles/{a,b,c,d}/        WP10     (Milestone 2)
/tests/smoke/               N7 / WP10  smoke-test scripts
```

### 0.7 Delivery milestones

Delivery is in two milestones, in order:

- **Milestone 1 — Chief-of-Staff Notes MVP** (work packages **N0–N7**, next
  section): the smallest build that is genuinely *this product* — a local-only,
  sandboxed agent that triages the day/week and maintains a topic-centric Ground
  Truth from meeting notes, with a deterministic Agenda service guaranteeing
  nothing date-based slips. Authoritative spec: `mvp-chief-of-staff-notes-design.md`.
  Grounds solely on the local Ground Truth (ADR-0004); no external systems.
  Depends on nothing and can begin immediately.
- **Milestone 2 — external adapters & profiles** (**WP0–WP10**): the
  north-star architecture of `workspace-assistant-spec.md` v0.7 — the two-role
  model, the pluggable Confluence/Jira **Grounding Sources**, the remote
  **Workspace**, and the profile mechanism. WP0 freezes the contracts; the rest
  follows §0.3. This is future work, layered on top of the MVP.

The two milestones share the §0.6 repository layout and the security model. The
notes MVP (N-track) is independently useful and ships first; the external-adapter
architecture (WP-track) is **additive** — it introduces Grounding Sources and a
remote Workspace alongside the notes layer, and does not require rewriting it.

---

## Milestone 1 — Chief-of-Staff Notes MVP  *(work packages N0–N7)*

**Authoritative spec:** `mvp-chief-of-staff-notes-design.md`. **Glossary:**
`CONTEXT.md`. **Decisions:** `docs/adr/0001`–`0004`.

**Goal.** A local-only, fully-sandboxed agent that (a) captures meeting notes
(hybrid: an `inbox/` drop folder + chat), (b) maintains a topic-centric **Ground
Truth** (`topics/` → meetings → documents), (c) triages the day/week by
Eisenhower quadrant with tickler-based resurfacing, and (d) answers/drafts from
the Ground Truth. A deterministic **Agenda service** guarantees nothing
date-based slips; the **frontend** versions `workspace/` in git for undo + audit.

**What it is — one vertical product.**
- Sandboxed OpenCode server (localhost, restricted config); `bash`/`webfetch`/
  `websearch`/`task` denied; `external_directory: deny`.
- **Workspace = native filesystem** = the `workspace/` tree (design §4). No remote
  Workspace, no `ask` flow — all local writes auto-execute.
- A read-only **Agenda service** MCP server — `agenda_today` / `agenda_review` /
  `agenda_topic` — read-only by construction.
- A **Python web frontend** (Open-WebUI-style chat) with inbox status,
  Process-inbox / Daily-brief / Weekly-review buttons, upload, and per-ingest
  changelog rendering; it owns the `workspace/` git repo.
- The agentic loop (ingest / capture / brief / review / query / report) realised
  by the system prompt + the Agenda service + frontend triggers.

**Depends on:** nothing — can begin immediately.

**Build order (Milestone 1).**

```
N0  (notes contracts & stack) ── freeze before N1–N7 start
  │
  ├─► N1  OpenCode config + notes system prompt  ─┐
  ├─► N2  Agenda service (engine + MCP)           ─┤ may run in parallel
  ├─► N3  Frontend: OpenCode client/proxy/SSE     ─┤
  └─► N6  Launcher                                ─┘
            │
  N4  Frontend: chat UI + notes affordances + upload   depends on N3
  N5  Notes git versioning (frontend-owned)            depends on N3 (+N4)
            │
  N7  Integration & smoke tests                        depends on N1–N6
```

### N0 — Notes contracts & stack  *(keystone — freeze before N1–N7)*

**Depends on:** nothing. **Inputs:** `mvp-chief-of-staff-notes-design.md`,
`CONTEXT.md`, ADR-0001…0004.
**Deliverables:** `contracts/notes-data-model.contract.md`,
`contracts/agenda-service.contract.md`, `docs/decisions/D-notes-stack.md`,
`docs/decisions/D-todo-parser.md`.

**Tasks.**
- **TN0.1 — Stack decision (spike).** Pin Python version, the frontend web
  framework, the `todo.txt` parsing approach (library vs. hand-rolled), and the
  office→Markdown library.
- **TN0.2 — Notes data-model contract.** Freeze the `workspace/` layout (design §4),
  the `tasks.todo.txt` extensions (quadrant↔priority letter, `due:`, `t:`,
  `upd:` last-touched, `+topic`, `@context`, `x`), the meeting frontmatter, and
  the topic frontmatter
  (**immutable `slug` + mutable `title`**, stamped `## Open actions`).
- **TN0.3 — Agenda service contract.** Freeze the JSON returned by
  `agenda_today` / `agenda_review` / `agenda_topic`, with the **7-day** stale-item
  and **3-week** stale-topic thresholds as named config.
- **TN0.4 — System-prompt conventions.** Specify the agent-behaviour contract:
  ingest **segmentation**, **auto-file + changelog** + ambiguity prompts,
  **auto-tickler +1 week**, **action authority** (`tasks.todo.txt` sole truth),
  the **`upd:` last-touched convention** (set on create and on every edit, so the
  Agenda service's staleness check is deterministic), cold-start seeding.

**Acceptance Gate.** Every notes interface has a complete schema (no "TBD");
`D-notes-stack.md` pins one value per question; `contracts/` frozen for the
N-track.

### N1 — OpenCode config + notes system prompt

**Depends on:** N0. **Deliverables:** `notes-mvp/opencode.json`,
`notes-mvp/notes-agent.md`.

**Tasks.**
- **TN1.1 — Restricted config.** `opencode.json`: OpenAI-compatible provider +
  model + the agent; `permission` denies `bash`/`webfetch`/`websearch`/`task`,
  sets `external_directory: deny`, native tools `allow`, `agenda_*` `allow`;
  declares the single Agenda MCP server entry; validates against the schema.
- **TN1.2 — Notes prompt.** `notes-agent.md` encodes the data model, the six loop
  verbs, and the TN0.4 conventions; English; no external systems referenced.

**Acceptance Gate.** Config validates and denies the four tools + external dir;
the prompt names the `agenda_*` tools and the folder conventions; **no Confluence/
Jira references**.

### N2 — Agenda service (engine + read-only MCP)

**Depends on:** N0. **Deliverables:** `agenda/engine.py`, `agenda/server.py`.

**Tasks.**
- **TN2.1 — Engine.** Deterministic parse of `tasks.todo.txt` + meeting/topic
  frontmatter; compute `today` (do-now / schedule / resurfacing / overdue /
  stale@7d), `review` (per-topic last-touched, 3-week stale topics, ticklers this
  week), and `topic(slug)`. Pure function of disk state; **never writes**.
- **TN2.2 — MCP server.** Expose `agenda_today/review/topic` over stdio,
  read-only by construction (no write tool); output matches the N0 schema.

**Acceptance Gate.** Given fixture notes, each tool returns the contract schema; a
`(B)` item with `t:` ≤ today appears in `resurfacing`; the server exposes **zero**
write tools; identical input → identical output (determinism).

### N3 — Frontend: OpenCode client, proxy, SSE

**Depends on:** N0. **Deliverables:** `frontend/opencode_client.py`,
`frontend/proxy.py`, `frontend/app.py`. *(Same scope as Milestone-2 WP2.)*

**Acceptance Gate.** Exactly one long-lived session; assistant deltas + tool-call
events relayed to the browser; `OPENCODE_SERVER_PASSWORD` never in a browser-bound
response; no direct browser→OpenCode route.

### N4 — Frontend: chat UI + notes affordances + upload

**Depends on:** N3. **Deliverables:** `frontend/ui/`, `frontend/upload.py`.

**Tasks.**
- **TN4.1 — Chat + tool events.** Streaming chat; tool calls shown as readable
  items ("filed meeting → project-atlas", "3 actions added", "agenda computed").
- **TN4.2 — Notes controls.** Inbox status ("N new notes") + Process-inbox,
  Daily-brief, Weekly-review buttons that send the canned loop prompts.
- **TN4.3 — Upload.** PPTX/DOCX/PDF → `.md` sibling into `workspace/documents/`
  (design §4.4); originals kept.
- **TN4.4 — Changelog render.** Render the per-ingest changelog and an `undo`
  affordance.

> **Ingest is propose-confirm by construction.** The agent never writes
> `tasks.todo.txt` / `topics/*.md` / `meetings/*` directly — it calls the
> `present_propose` MCP tool (served by the present MCP server alongside
> `present`; ADR-0006/0009), which stages a structured proposal at
> `inbox/_proposal.json`. The frontend shows the proposal to the user
> (reusing the sweep-panel) and applies the confirmed proposal
> deterministically. The shared validation schema (slug regex, section
> literal set, list caps `MAX_ACTIONS=50` / `MAX_TOPICS=20` /
> `MAX_MEETINGS=10`, per-field length caps, 1 MiB total JSON cap) lives in
> `frontend/proposal.py` and is imported by `presenter/server.py` so the
> MCP entry and the HTTP apply boundary stay in lock-step.

**Acceptance Gate.** Text streams progressively; buttons drive the loop; uploads
land in `documents/` with `.md` siblings; changelog + undo are visible.

### N5 — Notes git versioning (frontend-owned)  *(ADR-0003)*

**Depends on:** N3 (+ N4 changelog). **Deliverables:** `frontend/versioning.py`.

**Tasks.**
- **TN5.1 — Repo init.** On first run, initialise `workspace/` as its **own** git repo
  (separate from the code repo).
- **TN5.2 — Commit per operation.** After each agent operation, commit `workspace/`
  with a message mirroring the per-ingest changelog.
- **TN5.3 — Undo.** "undo" reverts the last operation's commit.

**Acceptance Gate.** Each ingest produces exactly one commit; `undo` restores the
prior state via revert; the **agent never invokes git** (it has no `bash`).

### N6 — Launcher

**Depends on:** N0. **Deliverables:** `launcher/start.ps1`. *(Same scope as
Milestone-2 WP1, simplified — no profile selection.)*

**Acceptance Gate.** Pre-flight (OpenCode/Bun present, port free); starts frontend
+ OpenCode; health probe passes; clean shutdown leaves no orphan process or held
port.

### N7 — Integration & smoke tests

**Depends on:** N1–N6. **Deliverables:** `tests/smoke/notes-mvp/`.

**Tasks.** End-to-end against fixtures: ingest an inbox file (segmentation →
meetings + actions + topic updates + changelog + one commit); daily brief; weekly
review with resurfacing; a query answered from the Ground Truth; an `undo`;
cold-start topic seeding.

**Acceptance Gate.** Each loop verb works end-to-end; the cross-cutting security
checklist (§ below) passes; a date-based tickler reliably resurfaces on its day.

**Out of scope for Milestone 1** (→ Milestone 2 / future): all external Grounding
Sources — Confluence, Jira (WP6–WP9); the remote Workspace + `ask` flow (WP8); the
profile mechanism + config generation (WP3, WP10); auto folder-watch; a visual
triage dashboard; rich report/document filling; **architecture C** (schema-
enforcing local notes write-MCP).

---

## WP0 — Interface Contracts & Foundations  *(keystone)*

**Goal.** Extract every interface the spec defines into frozen, machine-checkable
contract files, and pin the stack. After WP0 is accepted, `contracts/` is
**frozen** — no later WP may change it.

**Owner role:** Lead / architect agent.
**Depends on:** nothing.
**Inputs:** spec v0.7 (esp. §6, §10, §11).
**Deliverables:** the `/contracts/` directory and `/docs/decisions/` for any
stack spikes, plus `contracts/README.md` stating the freeze.
**Dependency allowlist:** none (documentation only).

### Tasks

**T0.1 — Stack & conventions decision record.**
Goal: remove every "which library / which framework" question for downstream WPs.
Done when:
- `docs/decisions/D-stack.md` exists and pins: Python version (one version,
  e.g. 3.12.x); the frontend web framework; the MCP server SDK (the official
  `mcp` Python SDK); the Atlassian client (`atlassian-python-api`); candidate
  office→Markdown and storage↔Markdown libraries.
- `contracts/README.md` records the repo layout of §0.6 and the naming
  convention `<server_key>_<tool_name>` for MCP tools.
- The dependency allowlist for each WP (WP1–WP10) is listed.

**T0.2 — Grounding MCP contract.**
Done when `contracts/mcp-grounding.contract.md` specifies, for the §11.1 core
(`search`, `get`, `list_attachments`, `download_attachment`) and the
document-shaped extensions (`get_section`, `list_children`, `projection="outline"`):
- exact bare tool names and parameter names/types/optionality;
- the **full JSON return schema** for each tool — every field name, type, and
  nullability (no field left as "TBD");
- the `projection` enum mechanism: how an adapter declares its legal values and
  that `full` is the omitted-parameter default.

**T0.3 — Workspace MCP contract.**
Done when `contracts/mcp-workspace.contract.md` specifies the §11.2 tools
(`create`, `append`, `replace_section`, `replace`, `list`, `read`,
`read_section`) with full parameter and return schemas, **and** the
*confirmation payload*: the exact JSON the Workspace MCP server returns / the
frontend renders for the write-confirmation dialog (target identifier + a
diff/preview representation).

**T0.4 — Jira grounding contract.**
Done when `contracts/jira-grounding.contract.md` specifies the §11.6 surface
(`search`, `get`, `list_attachments`, `download_attachment`, `get_comments`),
the `{summary, full}` projection, and the comments fields in a `full` `get`
(`comments[]`, `comment_count`, `comments_truncated`) with full schemas.

**T0.5 — OpenCode integration contract.**
Done when `contracts/opencode-config.contract.md` specifies:
- the exact `opencode.json` structure the frontend must emit (§10.3), including
  `provider`, `model`, the `workspace-assistant` agent, `permission`, and `mcp`;
- the agent prompt-file contract (filename, that it is emitted with all `<...>`
  pre-substituted);
- the `--role {grounding|workspace}` CLI convention for adapters;
- the env-var names per backend (`CONFLUENCE_BASE_URL`, `CONFLUENCE_PAT`,
  `WORKSPACE_PAGE_ID`, `GROUNDING_SPACE_KEYS`, `JIRA_BASE_URL`, `JIRA_PAT`,
  `GROUNDING_PROJECT_KEYS`) and the OpenCode server vars
  (`OPENCODE_CONFIG`, `OPENCODE_SERVER_PASSWORD`);
- the fixed default OpenCode server **port** and **hostname** (`127.0.0.1`).

**T0.6 — Runtime contracts.**
Done when:
- `contracts/workspace-json.contract.md` gives the full schema of the
  per-instance `workspace.json` (§6.3);
- `contracts/process-model.contract.md` gives the process list, ports, the
  `GET /global/health` readiness probe, and the start/stop sequence (§3.3, §8);
- `contracts/error-taxonomy.contract.md` enumerates the error classes (§7.6) —
  grounding (auth, network, not-found, malformed-query) and workspace (auth,
  network, not-found, write-rejected, local-IO) — and how an MCP server signals
  each so the frontend can classify it.

### WP0 Acceptance Gate

- **Given** the spec, **when** the contract files are reviewed, **then** every
  tool in spec §11.1, §11.2, §11.6 has a complete schema with no field typed
  "TBD" / "TODO".
- **Given** `contracts/opencode-config.contract.md`, **when** a sample
  `opencode.json` is generated for **each** of profiles A–D from it, **then**
  each sample validates against `https://opencode.ai/config.json`.
- **Given** `contracts/README.md`, **then** it contains an explicit sentence
  freezing `contracts/` and naming this plan version.
- **Then** `docs/decisions/D-stack.md` pins exactly one value for every stack
  question (no "either/or" left open).

**Out of scope for WP0:** any implementation code.

---

## WP1 — PowerShell Launcher

**Goal.** A launcher that pre-flight-checks, starts the frontend and the OpenCode
server, and shuts both down cleanly. (Spec §8.)

**Owner role:** PowerShell agent.
**Depends on:** WP0.
**Inputs:** `contracts/process-model.contract.md`.
**Deliverables:** `launcher/start.ps1` (plus a `launcher/README.md` of one
screen).
**Dependency allowlist:** PowerShell built-ins only.

### Tasks

**T1.1 — Pre-flight checks.** Done when the script verifies OpenCode and Bun are
on `PATH` and the configured port is free, and aborts with a distinct,
human-readable message for each failure **before** starting any process.

**T1.2 — Process start.** Done when the script starts the Python frontend and
the OpenCode server (`opencode serve --hostname 127.0.0.1 --port <fixed>`),
with the OpenCode process **started with its CWD set to the directory containing
the generated `opencode.json`** (OpenCode 1.15.0 ignores `OPENCODE_CONFIG` and
discovers config by walking up from CWD), and waits for `GET /global/health` to
succeed before reporting "ready".

**T1.3 — Shutdown.** Done when Ctrl+C / window-close terminates both processes;
no orphan process and no held port remains afterward.

### WP1 Acceptance Gate

- **Given** OpenCode is not on `PATH`, **when** the launcher runs, **then** it
  prints a specific error naming the missing prerequisite and starts **no**
  process.
- **Given** the port is already bound, **when** the launcher runs, **then** it
  aborts with a port-conflict message and does **not** pick another port.
- **Given** a clean environment, **when** the launcher runs, **then** both
  processes start and the health probe passes within a stated timeout.
- **Given** a running system, **when** the user interrupts it, **then** both
  processes exit and re-running the launcher succeeds (port free).

**Out of scope:** any application logic; restart/auto-reconnect.

---

## WP2 — Frontend: OpenCode Client & Proxy Core

**Goal.** The backend half of the frontend: the sole OpenCode HTTP client,
session management, SSE relay, and browser↔OpenCode proxy. (Spec §3.2, §5.3,
§7.5, §10.5.)

**Owner role:** Python backend agent.
**Depends on:** WP0.
**Inputs:** `contracts/opencode-config.contract.md`,
`contracts/process-model.contract.md`.
**Deliverables:** `frontend/opencode_client.py`, `frontend/proxy.py`,
`frontend/app.py` (web-server entrypoint).
**Dependency allowlist:** the frontend web framework (D-stack), an HTTP/SSE
client library.

### Tasks

**T2.1 — OpenCode client.** Done when a client module talks to the OpenCode HTTP
API for session create/get/delete and `POST /session/{id}/message`, carrying the
basic-auth credential from `OPENCODE_SERVER_PASSWORD`. Session creation uses
`POST /session` with body `{"agent":"workspace-assistant"}` (agent bound at
session creation — OpenCode 1.15.0 verified). Messages use body
`{"parts":[{"type":"text","text":…}]}`.

**T2.2 — Session lifecycle.** Done when the backend creates exactly one session
on startup and reuses it for all turns; on OpenCode failure it surfaces a
session-lost error (no auto-reconnect).

**T2.3 — SSE relay.** Done when the backend consumes the **global** `GET /event`
SSE stream, filters events by `properties.sessionID`, and relays assistant text
deltas (`message.part.delta` events, text at `properties.delta`) to the browser.
**Note (OpenCode 1.15.0):** tool-call progress is NOT in the SSE stream.
On receiving `session.idle`, the backend fetches `GET /session/{id}/message`
and surfaces tool-call events (from `type:"tool"` parts with tool name and
`state.status`) to the browser as discrete items.

**T2.4 — Proxy.** Done when the browser communicates only with the Python web
server; there is no code path by which the browser reaches the OpenCode server
directly, and `OPENCODE_SERVER_PASSWORD` never appears in any browser-bound
response.

### WP2 Acceptance Gate

- **Given** a running OpenCode server, **when** the frontend starts, **then**
  exactly one session is created.
- **Given** a user message, **when** it is sent, **then** the assistant response
  streams back and any tool calls appear as discrete relayed events.
- **Given** the OpenCode server is killed mid-session, **then** the frontend
  reports a session-lost error and does not silently retry.
- **Then** inspection of all browser-bound responses shows no OpenCode
  credential and no direct OpenCode URL.

**Out of scope:** UI rendering (WP4); config generation (WP3).

---

## WP3 — Frontend: Profile Loading & Config Generation

**Goal.** Load the active profile, run first-run binding collection, and generate
`opencode.json` + the agent prompt file; persist/read `workspace.json`. (Spec
§5.1–§5.2, §6.)

**Owner role:** Python backend agent.
**Depends on:** WP0.
**Inputs:** `contracts/opencode-config.contract.md`,
`contracts/workspace-json.contract.md`. Profile *content* is delivered by WP10;
WP3 builds the *machinery* and is tested against a stub profile.
**Deliverables:** `frontend/profiles.py` (loader), `frontend/configgen.py`.
**Dependency allowlist:** a JSON-schema validator.

### Tasks

**T3.1 — Profile loader.** Done when a profile (its five declared elements,
spec §6.1) loads from `profiles/<id>/` and is validated against its schema.

**T3.2 — First-run binding collection.** Done when, with no `workspace.json`
present, the backend queries `GET /v1/models`, exposes the profile's binding
schema to the UI, and resolves each binding (e.g. a Confluence page URL/ID → page
ID confirmed by title+space).

**T3.3 — Config generation.** Done when `configgen` emits `opencode.json`
matching `contracts/opencode-config.contract.md` and a prompt file with **all**
`<...>` variables substituted, then `workspace.json` is written. The emitted
`opencode.json` must include a **top-level `permission` block** (denying `bash`,
`webfetch`, `websearch`, `task`, and setting `external_directory: "deny"`) in
addition to the agent-level `permission` block — defense-in-depth because the
default (unnamed) agent is unrestricted in OpenCode 1.15.0.

**T3.4 — Subsequent-run path.** Done when, with `workspace.json` present, the
first-run dialog is skipped and a reconfigure entry point can rewrite bindings
and model.

### WP3 Acceptance Gate

- **Given** a stub profile + bindings, **when** config generation runs, **then**
  the emitted `opencode.json` validates against `https://opencode.ai/config.json`
  **and** against the WP0 contract.
- **Then** the emitted prompt file contains **no** unsubstituted `<...>` token.
- **Given** an existing `workspace.json`, **when** the frontend starts, **then**
  no first-run dialog appears and the stored model/bindings are used.
- **Given** a profile with a remote Workspace, **then** the emitted `permission`
  block sets the workspace write tools to `ask` and the grounding tools to
  `allow`, per §6.7.

**Out of scope:** profile content (WP10); UI widgets (WP4).

---

## WP4 — Frontend: Chat UI

**Goal.** The Open-WebUI-style chat interface: streaming, visible tool calls,
write-confirmation dialog, first-run and reconfigure dialogs. (Spec §7.1–§7.4.)

**Owner role:** Frontend UI agent.
**Depends on:** WP0; integrates with WP2 and WP3.
**Inputs:** `contracts/mcp-workspace.contract.md` (confirmation payload),
`contracts/error-taxonomy.contract.md`.
**Deliverables:** `frontend/ui/` (templates/assets).
**Dependency allowlist:** the frontend framework's view layer; **no** browser
storage APIs.

### Tasks

**T4.1 — Chat layout & streaming.** Done when messages render in an
Open-WebUI-style layout and assistant responses appear incrementally as they
stream.

**T4.2 — Tool-call events.** Done when each relayed tool-call event is shown as a
discrete, labelled item (e.g. "Grounding searched", "Note created").

**T4.3 — Write-confirmation dialog.** Done when a workspace-write event renders
the confirmation payload (target + diff/preview per the contract) and the user's
approve/reject choice is sent back; nothing is written without approval.

**T4.4 — First-run & reconfigure dialogs.** Done when the model picker and the
profile's binding fields render from data supplied by WP3, and a reconfigure
control re-opens them.

### WP4 Acceptance Gate

- **Given** a streamed response, **then** text appears progressively, not only
  at completion.
- **Given** a workspace write, **then** a dialog shows the target and a
  diff/preview, and **no** write proceeds until the user approves.
- **Given** a classified error from the backend, **then** a clear system message
  is shown.
- **Then** the UI uses no `localStorage`/`sessionStorage`/browser storage.

**Out of scope:** the proxy/streaming transport (WP2).

---

## WP5 — Frontend: Upload, Conversion & Error Classification

**Goal.** Document upload with office→Markdown conversion, and the
error-classification layer. (Spec §5.4, §7.6.)

**Owner role:** Python backend agent.
**Depends on:** WP0.
**Inputs:** `contracts/error-taxonomy.contract.md`,
`contracts/process-model.contract.md` (sandbox path rules).
**Deliverables:** `frontend/upload.py`, `frontend/errors.py`.
**Dependency allowlist:** the office→Markdown libraries pinned in D-stack.

### Tasks

**T5.1 — Upload & storage.** Done when an uploaded file is stored in the sandbox
directory and is reachable by the agent's `read` tool.

**T5.2 — Conversion.** Done when PDF, PPTX, DOCX are converted to Markdown with
**both** the original and the `.md` stored; TXT, CSV and other formats store the
original only.

**T5.3 — Per-turn file note.** Done when, after an upload, the agent receives a
short note naming the available file(s) for that turn, and the file content is
**not** auto-loaded into context.

**T5.4 — Error classification.** Done when `errors.py` maps every error class in
the taxonomy to a specific user-facing message, distinct per class.

### WP5 Acceptance Gate

- **Given** one file of each type {PDF, PPTX, DOCX, TXT, CSV}, **when** uploaded,
  **then** storage matches §5.4 (converted types have a `.md` sibling; others do
  not).
- **Given** an upload, **then** the per-turn note names the file and the content
  is not in the prompt context.
- **Given** a simulated instance of each taxonomy error class, **then** the
  classifier returns the matching, class-specific message.

**Out of scope:** UI rendering of messages (WP4).

---

## WP6 — Confluence Adapter: Shared Core

**Goal.** The shared Confluence machinery used by both roles: client wrapper,
storage↔Markdown conversion, the MCP stdio skeleton, and `--role` dispatch.
(Spec §11.3.)

**Owner role:** Python MCP agent.
**Depends on:** WP0.
**Inputs:** `contracts/mcp-grounding.contract.md`,
`contracts/mcp-workspace.contract.md`, `contracts/opencode-config.contract.md`
(`--role`, env vars).
**Deliverables:** `adapters/confluence/client.py`,
`adapters/confluence/storage_markdown.py`, `adapters/confluence/server.py`
(MCP skeleton with `--role`), `docs/decisions/D-confluence-conversion.md`.
**Dependency allowlist:** `atlassian-python-api`, the MCP SDK, the
storage↔Markdown library from D-stack.

### Tasks

**T6.1 — Conversion spike.** *Spike.* Done when `D-confluence-conversion.md`
selects the storage↔Markdown approach (reuse vs. bespoke) with reasons.
**Downstream tasks T6.3/T6.4 must not start until this exists.**

**T6.2 — Client wrapper.** Done when a wrapper authenticates to Confluence Data
Center with a PAT from `CONFLUENCE_PAT` + `CONFLUENCE_BASE_URL`.

**T6.3 — storage→Markdown.** Done when Confluence Storage Format converts to
Markdown for reads; lossy on macros is acceptable and noted.

**T6.4 — Markdown→storage.** Done when agent-authored Markdown converts to
storage XHTML, and the **core rule** holds: existing page content is preserved
verbatim as opaque XHTML and never round-trips through Markdown.

**T6.5 — MCP skeleton + `--role`.** Done when `server.py` starts an MCP stdio
server that, given `--role grounding` or `--role workspace`, registers **only**
that role's tool set.

### WP6 Acceptance Gate

- **Then** `D-confluence-conversion.md` exists and names one approach.
- **Given** sample storage XHTML, **when** converted, **then** headings, lists,
  tables, and links render as valid Markdown.
- **Given** a page with a macro and an appended agent-authored block, **when**
  written back, **then** the original macro XHTML is byte-identical to before.
- **Given** `--role grounding`, **then** no write tool is registered; **given**
  `--role workspace`, **then** no grounding-only tool is registered.

**Out of scope:** the role tool implementations (WP7, WP8).

---

## WP7 — Confluence Adapter: Grounding Role

**Goal.** The read-only Confluence Grounding tools on top of WP6. (Spec §11.1
core + document extensions, §11.3 grounding.)

**Owner role:** Python MCP agent.
**Depends on:** WP6.
**Inputs:** `contracts/mcp-grounding.contract.md`.
**Deliverables:** `adapters/confluence/grounding.py`.
**Dependency allowlist:** as WP6.

### Tasks

**T7.1 — search / get.** Done when `search` (CQL) and `get` (projection enum
`{outline, full}`) match the contract schemas; `outline` returns the heading
tree only.

**T7.2 — Document extensions.** Done when `get_section` and `list_children`
match the contract.

**T7.3 — Attachments + read extensions.** Done when `list_attachments`,
`download_attachment` (saving into the sandbox), `get_page_history`, and
`get_labels` match the contract.

### WP7 Acceptance Gate

- **Given** each grounding tool, **then** its request and response match the
  `mcp-grounding` contract schema exactly.
- **Given** `get(id, "outline")` on a long page, **then** the payload contains
  the heading tree and **no** full body; **given** `get(id, "full")`, **then**
  it contains the body.
- **Then** the registered tool set contains **no** write tool.
- **Given** `download_attachment`, **then** the file lands inside the sandbox
  directory and nowhere else.

**Out of scope:** any write capability.

---

## WP8 — Confluence Adapter: Workspace Role

**Goal.** The Confluence Workspace write tools and subtree enforcement on top of
WP6. (Spec §11.2, §11.3 workspace, §4.3.)

**Owner role:** Python MCP agent.
**Depends on:** WP6.
**Inputs:** `contracts/mcp-workspace.contract.md`,
`contracts/opencode-config.contract.md` (`WORKSPACE_PAGE_ID`).
**Deliverables:** `adapters/confluence/workspace.py`.
**Dependency allowlist:** as WP6.

### Tasks

**T8.1 — create / append.** Done when `create` (→ create child page) and
`append` match the contract.

**T8.2 — replace_section / replace.** Done when `replace_section` performs a
storage-XHTML section splice leaving the rest byte-identical, and `replace`
(full page-body rewrite — D1, §9.4) matches the contract.

**T8.3 — Subtree enforcement.** Done when every write verifies the target page
(or `parent_ref`) is `WORKSPACE_PAGE_ID` or a descendant, reading the anchor
**only** from the environment, never from a tool parameter.

**T8.4 — Optimistic locking.** Done when each update fetches the current page
version immediately before writing and handles a version conflict as a
classified error.

### WP8 Acceptance Gate

- **Given** a write whose target is outside the `WORKSPACE_PAGE_ID` subtree,
  **then** the adapter rejects it and writes nothing.
- **Given** `replace_section` on one section, **then** all other sections of the
  page are byte-identical afterward.
- **Given** a stale page version, **then** the write fails with a classified
  conflict error, not a silent overwrite.
- **Then** there is no code path where the subtree anchor is taken from a tool
  argument.

**Out of scope:** comments (excluded by §11.3).

---

## WP9 — Jira Adapter: Grounding

**Goal.** The full issue-shaped Jira Data Center Grounding adapter. (Spec §11.6.)

**Owner role:** Python MCP agent.
**Depends on:** WP0.
**Inputs:** `contracts/jira-grounding.contract.md`,
`contracts/opencode-config.contract.md` (`--role`, env vars).
**Deliverables:** `adapters/jira/client.py`, `adapters/jira/convert.py`,
`adapters/jira/grounding.py`, `adapters/jira/server.py`,
`docs/decisions/D-jira-api.md`.
**Dependency allowlist:** `atlassian-python-api`, the MCP SDK, an HTML→Markdown
or wiki-markup→Markdown library per the spike.

### Tasks

**T9.1 — Jira API spike (O5).** *Spike.* Done when `D-jira-api.md` confirms the
Jira DC REST v2 surface and chooses **wiki-markup→Markdown** vs.
**`expand=renderedFields` (HTML→Markdown)**, with reasons.
**Downstream tasks must not start until this exists.**

**T9.2 — Client + conversion.** Done when the client authenticates with
`JIRA_PAT` + `JIRA_BASE_URL`, and `convert.py` converts descriptions and comment
bodies to Markdown via the spike's chosen route (lossy is acceptable; the
known-limitation note from §11.6 is recorded).

**T9.3 — search.** Done when `search(jql, limit)` returns the contract result
shape; when `GROUNDING_PROJECT_KEYS` is set, the agent's JQL is parenthesised
before the scope clause is ANDed, so it cannot escape scope.

**T9.4 — get + comments.** Done when `get(issue_key, projection)` honours
`{summary, full}`; a `full` result includes the recent-comments window plus
`comment_count` and `comments_truncated`; `get_comments` pages older comments.

**T9.5 — Attachments + custom fields + `--role`.** Done when `list_attachments`
and `download_attachment` match the contract; custom-field IDs are resolved to
human names; `server.py` registers the grounding tool set under `--role
grounding` and exposes no write tool.

### WP9 Acceptance Gate

- **Then** `D-jira-api.md` exists and names one conversion route.
- **Given** each Jira grounding tool, **then** request/response match the
  `jira-grounding` contract.
- **Given** `get(key, "full")` on an issue with > N comments, **then**
  `comments` holds the newest N, `comment_count` is the true total, and
  `comments_truncated` is `true`.
- **Given** `GROUNDING_PROJECT_KEYS` is set and an agent JQL of the form
  `... OR project = OTHER`, **then** results stay within the configured
  project(s).
- **Then** the registered tool set contains **no** write tool.

**Out of scope:** any Jira write capability (record-shaped Workspace — deferred,
§9.2).

---

## WP10 — Profiles & Integration

**Goal.** Author the four profile bundles and wire the system end-to-end. (Spec
§6, Appendices A–D.)

**Owner role:** Integration agent.
**Depends on:** WP1–WP9 (all gates passed).
**Inputs:** all `contracts/`; spec Appendices A–D.
**Deliverables:** `profiles/{a,b,c,d}/prompt.md` and
`profiles/{a,b,c,d}/profile.json` (the descriptor: the five §6.1 elements);
`tests/smoke/` scripts.
**Dependency allowlist:** as the WPs being integrated.

### Tasks

**T10.1 — Profile A.** Done when profile A (Confluence Workspace assistant) has a
descriptor and prompt template matching Appendix A; generated `opencode.json`
has two Confluence servers (`confluence` grounding, `workspace`) and the
Appendix-A `permission` block.

**T10.2 — Profile B.** As T10.1 for Appendix B (local notes + Confluence
grounding): one grounding server, native-FS Workspace.

**T10.3 — Profile C.** As T10.1 for Appendix C (Jira grounding + local notes).

**T10.4 — Profile D.** As T10.1 for Appendix D (Jira grounding + Confluence
Workspace): a `jira` grounding server **and** a `workspace` Confluence server —
two backends.

**T10.5 — Smoke tests.** Done when `tests/smoke/` has one script per profile
that launches the system and drives one representative end-to-end task.

### WP10 Acceptance Gate

- **Given** each profile A–D, **when** the system launches, **then** it reaches
  health-ready and the expected MCP servers are running (per the profile's
  Appendix).
- **Given** Profile A, **when** the agent is asked to create a page, **then** a
  confirmation dialog appears and, on approval, a child page is created inside
  the Workspace subtree.
- **Given** Profile B/C, **when** the agent is asked to take a note, **then** a
  dated file appears in the sandbox `workspace/` directory with **no** confirmation
  dialog.
- **Given** Profile D, **when** the agent is asked to summarise Jira issues into
  a status page, **then** it reads via `jira_*`, and writing via `workspace_*`
  triggers the confirmation dialog.
- **Then** the cross-cutting security checklist (§ below) passes for every
  profile.

**Out of scope:** new adapters or profiles beyond A–D.

---

## Cross-Cutting Acceptance — Security Checklist

Verified during WP10 for every profile; traces to spec §4.

- The OpenCode server is reachable only on `127.0.0.1` at the fixed port; not on
  any external interface.
- The browser has no route to the OpenCode server; `OPENCODE_SERVER_PASSWORD`
  appears in no browser-bound response.
- `permission` denies `bash`, `webfetch`, `websearch`, and `task`.
- `permission.external_directory` is `"deny"`; a path-taking tool aimed outside
  the launch directory is refused.
- Every Grounding MCP server, started in the grounding role, exposes **zero**
  write tools.
- Remote-Workspace write tools are `ask`; no remote write occurs without user
  approval.
- All backend credentials come from environment variables; none are hardcoded;
  none appear in logs.

---

## Traceability — Work Package → Specification

**Milestone 1 — Chief-of-Staff Notes MVP** (spec: `mvp-chief-of-staff-notes-design.md`):

| WP | Builds | Design sections |
|----|--------|-----------------|
| N0 | Notes contracts (data model, agenda schema), stack | §4, §5, §6 |
| N1 | OpenCode config + notes system prompt | §3, §6, §8 |
| N2 | Agenda service (engine + read-only MCP) | §5 |
| N3 | Frontend: OpenCode client, proxy, SSE | §7 |
| N4 | Chat UI, notes buttons, upload, changelog render | §6, §7 |
| N5 | Notes git versioning (frontend-owned) | §8, ADR-0003 |
| N6 | Launcher | §7 |
| N7 | Integration & smoke tests | §6 (loop verbs) |

**Milestone 2 — external adapters & profiles** (spec: `workspace-assistant-spec.md` v0.7):

| WP | Builds | Spec sections |
|----|--------|---------------|
| WP0 | Interface contracts, stack | §6, §10, §11 |
| WP1 | PowerShell launcher | §8, §3.3 |
| WP2 | OpenCode client, proxy, SSE | §3.2, §5.3, §7.5, §10.5 |
| WP3 | Profile loading, config generation | §5.1–§5.2, §6 |
| WP4 | Chat UI, confirmation dialog | §7.1–§7.4 |
| WP5 | Upload, conversion, error classification | §5.4, §7.6 |
| WP6 | Confluence core, conversion, `--role` | §11.3, §11.5 |
| WP7 | Confluence grounding tools | §11.1, §11.3 |
| WP8 | Confluence workspace tools, subtree scope | §11.2, §11.3, §4.3 |
| WP9 | Jira grounding adapter | §11.6, §11.5 |
| WP10 | Profiles A–D, integration, smoke tests | §6, Appendices A–D |
| Cross-cutting | Security checklist | §4 |

Milestone 1 builds the local-only notes product and reuses N1/N3/N4/N6 scope that
Milestone 2's WP1/WP2/WP4/WP5 generalise. Items deliberately **not** allocated
(deferred): chat-history persistence, auto-reconnect, multiple parallel
workspaces, model routing, subagents, a record-shaped Workspace (spec §9.2), and
architecture C (design §2.2 deferral).
