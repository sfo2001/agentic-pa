# Agentic Workspace Assistant — System Specification

**Status:** North-star architecture — **future external-adapter track** (the
current MVP is specified separately; see the revision note)
**Version:** 0.8
**Last updated:** 2026-05-30

> **Revision note (v0.8 — verified OpenCode 1.15.0 corrections, 2026-05-30):**
> Five empirically-verified findings (from live spike `docs/decisions/D-opencode-http.md`
> and plan-2 wiring) are reconciled into this spec:
> (1) **Confinement is anchored to the launch CWD or the enclosing git work-tree
> root, not to config location** (superseded the earlier "OPENCODE_CONFIG is not
> honored" note — that was wrong). `opencode serve`/`run` discover `opencode.json`
> by walking up from the CWD to the git root, and `OPENCODE_CONFIG` **is** honored
> (it *merges*, it does not replace — source `config/config.ts:601-603`). The
> launcher therefore does not rely on `OPENCODE_CONFIG`: it sets CWD = the
> `workspace/` sandbox, keeps no `.git` at/above it, and isolates HOME/XDG **plus
> strips all `OPENCODE_*` env vars** so global config cannot bleed in. Source-
> verified — see `docs/decisions/D-opencode-sandbox.md` §8 (§10.1 corrected).
> (2) **Tool-call progress is not in the `/event` SSE stream** — the stream carries
> assistant text deltas only; tool calls (and their results) are available on the
> finished message via `GET /session/{id}/message` after `session.idle` (§5.3, §7.1,
> §10.5 corrected).
> (3) **Event shapes confirmed:** text delta = `{"type":"message.part.delta",
> "properties":{"sessionID":…,"field":"text","delta":"<chunk>"}}` (text at
> `properties.delta`); turn end = `{"type":"session.idle","properties":{"sessionID":…}}`;
> `/event` is a GLOBAL stream — consumers filter by `properties.sessionID` (§10.5).
> (4) **Agent bound at session creation:** `POST /session` body `{"agent":"workspace-assistant"}`;
> messages via `POST /session/{id}/message` body `{"parts":[{"type":"text","text":…}]}`
> (open item in §9.1 O1 / §10.5 resolved).
> (5) **The default (unnamed) agent is unrestricted** — `permission` denials must also
> be set at the **top level** of `opencode.json` as defense-in-depth, not only inside
> the named agent (§10.4 updated).

> **Revision note (v0.7 — consolidation, 2026-05-30):** The **current MVP is no
> longer defined here.** It is the **Chief-of-Staff Notes Assistant**, specified
> authoritatively in `mvp-chief-of-staff-notes-design.md` — a local-only,
> structured-notes system (sandboxed OpenCode + native-FS workspace + Python
> frontend + a deterministic Agenda service). **Note on terminology:** this
north-star spec uses `notes/` generically for the agent's workspace directory; the
realized Milestone-1 layout names that directory **`workspace/`** (the sandbox leaf
— see `mvp-chief-of-staff-notes-design.md` §4 / ADR-0005). This document is now the
> **north-star architecture for the future external-adapter track**: the two-role
> model, the pluggable Confluence/Jira adapters, and the profile mechanism. Those
> are deferred to **Milestone 2** of the implementation plan (v0.3), *not* the
> MVP. Terminology is reconciled to `CONTEXT.md`: **"Grounding Source" means an
> external, read-only knowledge backend behind an MCP adapter** (Confluence,
> Jira); the local notes corpus the MVP maintains is the **Ground Truth**, read
> via native file tools, and is **not** a Grounding Source. Where §1.3/§1.4 below
> say "MVP", read "target architecture scope (Milestone 2)". See also ADR-0004.

> **Revision note (v0.6):** Adds **Jira as a Grounding Source**. Jira is
> issue/record-shaped rather than document-shaped, which surfaces a distinction
> the earlier interface left implicit: the §11.1 Grounding interface is now an
> explicit **shape-agnostic core** plus **document-shaped extensions**, and
> `get` is polymorphic across backends via an adapter-declared `projection`
> enum (replacing the document-only `format="markdown"|"outline"`). A Jira Data
> Center grounding adapter is specified (§11.6) and two profiles are added:
> Appendix C (Jira grounding + local notes) and Appendix D (Jira grounding +
> Confluence Workspace — grounding and workspace on *different* backends). A
> record-shaped **Workspace** interface (writing to Jira: transition,
> field-update, comment, link) does **not** fit the document-shaped Workspace
> contract of §11.2 and is explicitly deferred (§9.2).

> **History.** v0.1–v0.3: single-purpose *Confluence Workspace assistant*. v0.4:
> generalised into a read-only **Grounding Source** + read-write **Workspace**,
> each behind a pluggable adapter, selected by a deployment **profile**. v0.5:
> O4 resolved (MCP namespacing), one-server-per-role adopted, sandbox hardening.
> v0.6: Jira added as a Grounding Source; backend *shape* made explicit.

---

## 1. Goal & Scope

### 1.1 Purpose

A locally-run agentic system that lets a user interact, via a chat interface,
with an LLM agent that can **search and read** one or more knowledge sources for
grounding, and **accumulate its outputs** in a designated workspace. The
knowledge sources and the workspace are independent, pluggable backends; a given
deployment binds concrete adapters to each role.

### 1.2 The core abstraction

Two roles, defined in full in §2:

- **Grounding Source** — read + search only. The agent consults it; it is never
  mutated by the agent. A deployment may bind several.
- **Workspace** — read + write. Where the agent's outputs accumulate. A
  deployment binds exactly one.

A backend may fill one role or both. The v0.3 design is the special case where a
single Confluence instance is bound to *both* roles.

### 1.3 In scope (target architecture — Milestone 2)

- OpenCode running in server mode, localhost-bound, driven by a generated,
  restricted configuration.
- A **deployment profile** mechanism: a named bundle that selects a Workspace
  adapter, one or more Grounding adapters, a system-prompt template, and a
  permission/confirmation policy.
- One or more **Grounding MCP servers** (stdio), each exposing a fixed read-only
  tool set for one knowledge source.
- A **Workspace** realised either by OpenCode's native filesystem tools (local
  workspace) or by a **Workspace MCP server** (remote workspace).
- A Python web frontend in an Open-WebUI-style chat layout.
- A PowerShell launcher that starts and lifecycles the processes.
- First-run configuration of the active profile's per-instance bindings and the
  agent model.
- User document upload via chat, with automatic conversion of common office
  formats to Markdown.
- Confluence (document-shaped) and Jira (issue-shaped) backend adapters.
- Four reference profiles (Appendix A–D).

### 1.4 Out of scope (target architecture — see §9.2)

- Chat history persistence and session recovery / auto-reconnect.
- Multiple parallel workspaces within one running instance.
- User-editable system prompt.
- Model routing or subagents.
- A record/issue-shaped **Workspace** (e.g. writing to Jira); the Jira adapter
  is Grounding-only in the MVP.
- Profiles and adapters beyond the four reference profiles (the mechanism is in
  scope; further adapters are future work).

---

## 2. The Two-Role Model

This section defines the abstraction; §11 specifies the concrete interfaces and
adapters.

### 2.1 Grounding Source (read-only)

A Grounding Source is anything the agent can search and read for context but must
not modify. Conceptually it offers: full-text / structured search, retrieval of
an item, and retrieval of attachments into the sandbox. Document-like sources
additionally offer heading-tree navigation (§11.1).

- Always read-only **by construction** — a Grounding adapter exposes no write
  tools at all, so the restriction is not a policy that could be misconfigured
  (see §11.5 for how "one server per role" makes this hold even when the same
  backend also serves as the Workspace).
- A deployment may bind **several** Grounding Sources; each is a separate MCP
  server with a distinct namespace.
- Grounding operations always auto-execute (read-only ⇒ non-critical).

Backends differ in **shape**: Confluence is *document-shaped* (items have a body
and a heading hierarchy); Jira is *issue/record-shaped* (items are sets of
fields with no body hierarchy). The Grounding interface accommodates both via a
shape-agnostic core plus document-shaped extensions (§11.1). Confluence (§11.3)
and Jira (§11.6) are the MVP Grounding adapters; a local document corpus, a
vector index, SharePoint, or a wiki are future work.

### 2.2 Workspace (read-write)

The Workspace is where the agent's deliverables accumulate. Conceptually it
offers: list, read (whole or by section), create, append, replace-section, and
— as an explicit exception — full replace.

- A deployment binds **exactly one** Workspace.
- The Workspace is realised by one of two mechanisms, chosen by the adapter:
  - **Native** — the local sandbox directory, operated on by OpenCode's built-in
    `read` / `write` / `edit` / `glob` / `grep` / `list` tools. No MCP server.
  - **Remote** — an external system (e.g. a Confluence page subtree), operated on
    by a **Workspace MCP server** exposing the tiered write tools.
- Each Workspace adapter **declares its own confirmation policy** (§4.5) and its
  own write-scope enforcement (§4.3).

The Workspace operations of §11.2 are **document-shaped**. Record-shaped
backends (writing to Jira) have a different write vocabulary and are out of MVP
scope (§9.2, §11.2 scope note).

### 2.3 One MCP server per role

Each role is realised by its own MCP server (or, for a native Workspace, by
OpenCode's native tools — no server). A backend that fills *both* roles runs as
**two** MCP servers, one per role. This is what makes the server key a clean
namespace and the read-only guarantee constructive; the mechanics and rationale
are in §11.5.

### 2.4 The sandbox is always present

Independent of the Workspace mechanism, every deployment has a **sandbox
directory** (the OpenCode launch directory). It holds user uploads, Grounding
attachment downloads, and agent scratch files.

- With a **native** Workspace, the workspace *is a subtree of* the sandbox — the
  agent's deliverables and its scratch files share one directory tree.
- With a **remote** Workspace, the workspace is *disjoint from* the sandbox — the
  sandbox is scratch/uploads/downloads only, and deliverables live in the remote
  system.

### 2.5 Why the split matters

In v0.3 the write restriction, the `ask` confirmation policy, the
Markdown↔storage conversion, and the workspace-page injection all existed solely
because the *write target* was Confluence. Separating the roles localises every
one of those concerns inside the relevant **adapter**, leaving the launcher,
frontend, OpenCode server, and core data flows backend-agnostic. Adding a profile
becomes an adapter + prompt + policy exercise, not a redesign. Profile D
(Appendix D) — Jira grounding with a Confluence Workspace — exercises this: the
two roles are served by entirely different backends.

---

## 3. Architecture & Components

### 3.1 Component overview

```
Browser (chat UI in browser)
  │  HTTP/SSE
  ▼
PowerShell Launcher
  ├─ starts ──> Python Frontend
  │              ├─ web server  (serves UI, talks to browser only)
  │              └─ backend     (sole OpenCode client; proxies browser <-> OpenCode)
  │                     │
  │                     └─ HTTP API + SSE ──> OpenCode Server (localhost-bound)
  │                                               │
  └─ starts ──> OpenCode Server                   │
                     │                            │
                     │  Workspace (native): OpenCode's own file tools
                     │      operate on the sandbox directory — no MCP.
                     │
                     ├─ spawns (stdio) ──> Grounding MCP Server(s)   [≥1, read-only]
                     │                          └─ adapter over a knowledge source
                     │
                     └─ spawns (stdio) ──> Workspace MCP Server      [0 or 1, remote workspace]
                                                └─ adapter over a write target
```

Which MCP servers are spawned is determined by the **active profile** (§6). A
profile with a native Workspace spawns Grounding server(s) only; a profile with a
remote Workspace additionally spawns a Workspace server. A backend that serves
**both** roles (e.g. Confluence in Profile A) is spawned as *two* servers, one
per role (§2.3, §11.5).

### 3.2 Components

**PowerShell Launcher.**
Performs pre-flight checks, starts the Python frontend and the OpenCode server,
and terminates both on shutdown. Backend-agnostic.

**Python Frontend.**
Two logical parts in one process: a web server that serves the Open-WebUI-style
chat UI, and a backend that is the **sole OpenCode HTTP client**. The browser
communicates only with the Python web server; it never reaches the OpenCode
server directly. The backend proxies every browser request to the OpenCode HTTP
API and relays the OpenCode SSE event stream back to the browser. On first run it
loads the active profile, collects the profile's per-instance bindings and the
model, and generates `opencode.json` plus the agent prompt file. It handles
document uploads and conversion, and intercepts and displays runtime errors.
Backend-agnostic except for the profile it loads.

**OpenCode Server.**
Runs headless via `opencode serve`, bound to localhost only. Driven by the
generated, restricted `opencode.json`: dedicated model, reduced tool set, fixed
system prompt. Spawns the profile's MCP server(s).

**Grounding MCP Server(s).**
One thin stdio MCP server per knowledge source, each exposing a fixed
**read-only** tool set (§11.1) and serving the Grounding role only. Each
delegates to a backend-specific adapter. A Grounding server exposes no write
tools.

**Workspace MCP Server (remote-workspace profiles only).**
A thin stdio MCP server exposing the tiered Workspace tools (§11.2) for a remote
write target, serving the Workspace role only. Delegates to a Workspace adapter
that enforces the adapter's write scope. Absent in profiles with a native
Workspace.

**Adapters.**
Per-backend code behind each MCP server. A Grounding adapter implements the
read-only Grounding interface (§11.1); a remote-Workspace adapter implements the
Workspace interface (§11.2) and enforces its write scope. The Confluence adapter
(§11.3) can serve both roles; the Jira adapter (§11.6) serves the Grounding role
only; the native filesystem adapter (§11.4) implements the Workspace role via
OpenCode's built-in tools and needs no MCP server.

### 3.3 Process topology and start sequence

`Launcher → Frontend → OpenCode Server → (OpenCode spawns) Grounding MCP server(s) [+ Workspace MCP server]`

MCP servers run as stdio children of the OpenCode server; they are not separately
lifecycled and require no additional ports.

---

## 4. Security Model & Constraints

### 4.1 Network exposure

- The OpenCode server is bound to localhost only (`--hostname 127.0.0.1`).
- The Python backend is the sole client of the OpenCode HTTP API. The browser
  communicates only with the Python web server; it has no direct route to the
  OpenCode server. The OpenCode basic-auth credential
  (`OPENCODE_SERVER_PASSWORD`) stays server-side and is never exposed to the
  browser. The `--cors` flag is not required.
- The agent has no general internet access: `webfetch` and `websearch` are
  denied (§6.7). The only outbound access is to the configured backends (via
  their MCP servers) and to the configured model endpoint (via OpenCode).

### 4.2 Grounding is read-only by construction

A Grounding MCP server exposes search and read tools only. There is no Grounding
write path to restrict, mis-scope, or prompt around. Because each MCP server
serves exactly one role (§2.3, §11.5), this holds even when the same backend
also serves as the Workspace: the Grounding server is a distinct process started
in the grounding role, and it advertises no write tools at all.

### 4.3 Workspace write scope

Write-scope enforcement is **adapter-specific** and lives in the adapter, never
in the prompt and never in OpenCode tool permissions alone:

- **Native (filesystem) Workspace** — the scope is the sandbox directory.
  Enforcement is OpenCode's working-directory confinement of path-taking tools,
  hardened by `permission.external_directory: "deny"` (§10.4). The workspace is
  the sandbox; nothing further is needed.
- **Remote Workspace (e.g. Confluence subtree)** — the scope is declared by the
  adapter (e.g. a page + its descendants). Enforcement lives in the adapter; the
  scope anchor is injected at startup via the MCP `environment` block, not as a
  tool parameter the model can choose. OpenCode cannot bypass the adapter.

### 4.4 Filesystem sandbox

- OpenCode runs with its working directory set to the launch directory.
- The OpenCode file tools (`read`, `write`, `edit`, `glob`, `grep`, `list`) are
  confined to this directory tree. With `permission.external_directory` set to
  `"deny"` (§10.4) the agent cannot access the wider filesystem at all — a path
  outside the launch directory is a hard denial, not a user prompt.
- All user uploads, Grounding attachment downloads, and agent scratch files
  reside within this single sandbox directory. With a native Workspace, the
  workspace deliverables reside here too (§2.4).

### 4.5 Confirmation policy

Confirmation policy is **declared per role / per adapter**:

- **Grounding operations** — always `allow` (auto-execute); read-only.
- **Native Workspace operations** — `allow` (auto-execute); the sandbox makes
  local file writes non-critical.
- **Remote Workspace operations** — `ask`: the frontend shows a confirmation
  dialog (target + diff/preview) before each write; the user approves it.

The active profile fixes the policy; the frontend does not infer it.

### 4.6 Authentication

- Each backend adapter receives its own credentials via environment variables
  (e.g. a Confluence or Jira Personal Access Token and base URL). These are
  installation constants. When one backend serves two roles, both server
  entries receive the same credentials (§11.5).
- Model endpoint: OpenAI-compatible base URL (and key, if required), set in the
  frontend configuration as an installation constant.

### 4.7 Model data class

The agent passes Grounding content and (for native-Workspace profiles) local
workspace content to the model. The configured model endpoint must be approved
for the **most sensitive** data class the active profile handles — typically the
local backend or an explicitly approved endpoint. The spec states the
requirement; it does not mandate a backend (see O3, §9.1).

---

## 5. Data Flows & Workflows

### 5.1 First run

1. The frontend loads the **active profile** (§6.1) and finds no stored instance
   bindings.
2. It queries `GET /v1/models` on the configured model endpoint and presents the
   returned list for selection.
3. It prompts for the profile's **per-instance bindings** — the variable inputs
   the profile declares (e.g. a Confluence Workspace page; a notes directory
   name; the Grounding space(s) or project(s) to search).
4. The frontend resolves each binding (e.g. a Confluence page URL/ID → page ID,
   confirmed by title + space) and shows it back for confirmation.
5. The selected model and resolved bindings are persisted to `workspace.json`.
6. The frontend generates `opencode.json` and the agent prompt file from the
   profile + bindings, and starts the OpenCode server.

### 5.2 Subsequent runs

`workspace.json` is present and is read; the first-run dialog is skipped. A
reconfigure option in the UI allows changing the bindings/model without manually
deleting the configuration file. Changing the *profile itself* is an
installation action, not an in-UI reconfigure (§6.4).

### 5.3 Chat turn

1. The browser sends the user message to the Python web server.
2. The backend forwards it to the OpenCode server (`POST /session/{id}/message`)
   within the single long-lived session, directed at the dedicated agent.
3. The backend consumes the OpenCode SSE `/event` stream — assistant text deltas
   (`message.part.delta` events, filtered by `sessionID`) — and relays them to
   the browser. **Note (OpenCode 1.15.0):** tool-call progress is NOT in the SSE
   stream; it is available only on the finished message.
4. The browser renders the streamed response. On `session.idle`, the backend
   fetches `GET /session/{id}/message` to obtain the finished message (which
   includes `type:"tool"` parts with tool name and `state.status`); tool-call
   events are surfaced in the UI from those parts.

### 5.4 Document upload

1. The user uploads a file via chat.
2. The file is stored in the sandbox directory.
3. If it is PDF, PPTX, or DOCX, the frontend converts it to Markdown and stores
   both the original and the `.md` version.
4. If it is TXT or CSV (or another non-converted format), only the original is
   stored.
5. The agent receives a short note for that turn naming the available file(s).
   The file content is not auto-loaded into context; the agent reads it via its
   `read` tool if needed.

### 5.5 Grounding read / search / download

The agent uses the Grounding tools to search, read items, navigate hierarchy or
relations, list attachments, and download attachments into the sandbox. These
operations are unrestricted and auto-executing. Tool signatures are in §11.1.
When several Grounding Sources are bound, each has a distinct namespace (§11.5)
and the agent chooses among them.

### 5.6 Workspace write

The agent writes its deliverables to the bound Workspace:

- **Native Workspace** — the agent uses OpenCode's `write` / `edit` tools on the
  sandbox, following the conventions in the profile prompt (e.g. one file per
  day). Writes auto-execute.
- **Remote Workspace** — the agent uses one of the tiered Workspace tools
  (§11.2). For every write the frontend presents a confirmation dialog (target +
  diff/preview); on approval the adapter performs the write, having first
  verified the target is within the declared write scope.

---

## 6. Configuration & Profiles

### 6.1 Deployment profile

A **profile** is a named, installed configuration bundle. It declares:

1. **Workspace binding** — adapter (`native-fs` or a remote adapter) and adapter
   configuration.
2. **Grounding bindings** — one or more Grounding adapters and their
   configuration.
3. **System-prompt template** — a prompt file with profile-specific behaviour and
   `<...>` variables filled at generation time.
4. **Permission / confirmation policy** — the `permission` block (§10.4) and the
   confirmation policy (§4.5) implied by the chosen adapters.
5. **Per-instance binding schema** — the variable inputs collected at first run
   (§5.1 step 3).

Exactly one profile is *active* per installation. Four reference profiles are
specified (Appendix A–D).

### 6.2 Installation constants

- Per-backend credentials and base URLs (environment variables) — e.g. Confluence
  and/or Jira base URL and PAT.
- Model endpoint base URL and optional key (frontend configuration).
- The active profile (installation selection).

### 6.3 Per-instance configuration (`workspace.json`)

Written by the frontend during first run, read on subsequent runs:

- The active profile name.
- The resolved per-instance bindings (profile-defined — e.g. a resolved
  Confluence Workspace page ID/title/space; a notes directory name; resolved
  Grounding space or project keys).
- Selected model (provider/endpoint and model ID).

### 6.4 Changing profile vs. reconfiguring

- **Reconfigure** (in-UI, §5.2) changes bindings and/or model within the active
  profile.
- **Changing the profile** swaps adapters, prompt, and policy; it is an
  installation action (select a different profile, clear `workspace.json`,
  re-run first-run). Not exposed in the MVP UI.

### 6.5 Generated `opencode.json`

The frontend generates `opencode.json` (in the launch directory, the OpenCode
project root) before starting the OpenCode server. It contains:

- A custom `provider` entry (OpenAI-compatible) pointing at the configured model
  endpoint, and a top-level `model` selecting the dedicated model — no routing,
  no runtime switching.
- A dedicated **primary agent** definition carrying the profile's `permission`
  set and referencing the generated system-prompt file via its `prompt` field
  (see §6.6 and §10.3).
- The profile's MCP server definitions (`type: "local"`, stdio): one per
  Grounding Source, plus the Workspace server for remote-Workspace profiles —
  one server per role (§2.3, §11.5). Per-backend scope anchors (e.g.
  `WORKSPACE_PAGE_ID`) are passed via the relevant server's `environment` block.
- The `permission` block implementing the profile's tool restrictions (§6.7,
  §10.4).

The exact field-by-field model is in §10; profile-specific skeletons are in the
appendices.

### 6.6 System prompt

**Mechanism (verified — see §10.3).** OpenCode's base system prompt is a static,
provider-specific file selected by model ID. It is *replaced entirely* when the
active agent defines its own `prompt`. The system prompt is therefore set by
defining the dedicated primary agent with a `prompt` field pointing to a prompt
file. The top-level `instructions` option and any `AGENTS.md` / `CLAUDE.md`
discovered in the working tree are *appended* to the prompt, not replaced.

**Consequences for this design:**

- The frontend writes a `prompt` file (e.g. `workspace-agent.md`) from the active
  profile's template, with the per-instance variables already substituted at
  generation time — OpenCode does not template the file. Variable substitution is
  the frontend's responsibility, identical to how it generates `opencode.json`.
  The substituted variables include the active profile's MCP tool namespaces
  (§11.5) and each Grounding Source's query language, so the prompt can name
  tools and query syntax precisely.
- For a fully controlled prompt in the MVP, `instructions` is left unset. The
  agent could in principle `write` an `AGENTS.md` into the sandbox, which
  OpenCode would append on the next run; this is an accepted minor caveat. (It is
  slightly more salient for native-Workspace profiles, where the agent writes
  into the sandbox routinely — see B-note in Appendix B.)

**Content.** Profile-specific (see appendices). Common invariants: the agent's
Grounding Sources are read-only and named (by namespace); the Workspace is where
deliverables go; sandbox files are reachable via `read`. Not user-editable in the
MVP. Default agent language: English.

### 6.7 Tool surface and permissions

Tool access is controlled through the `permission` field. The legacy boolean
`tools` config is deprecated (OpenCode v1.1.1) and merged into `permission`
(`true`→`allow`, `false`→`deny`); it remains accepted. Permission keys match
tool names with `*`/`?` wildcards, last matching rule wins (§10.4). MCP tools are
namespaced `<server_key>_<tool>` and addressed per role (§11.5).

**Denied** (`"deny"`), all profiles: `bash`, `webfetch`, `websearch`, `task`
(no subagents) — the agent has no shell, no internet, and no subagents.

**Native file tools** (`read`, `write`, `edit`, `glob`, `grep`, `list`) —
`"allow"`. `permission.external_directory` is set to `"deny"` (its OpenCode
default is `"ask"`), making the sandbox boundary a hard denial rather than a
user prompt (§4.4, §10.4). In native-Workspace profiles these tools are the
Workspace mechanism; in remote-Workspace profiles they serve
uploads/downloads/scratch only.

**Planning tools** (`todowrite`, `todoread`) — left at OpenCode's default
(`allow`).

**Grounding MCP tools** — `allow`, scoped by the server-prefix glob
`"<source>_*"` per Grounding server (read-only; the glob is safe here — see
§11.5).

**Workspace MCP tools** (remote-Workspace profiles only) — `ask`, so the
frontend confirmation dialog fires before each write. Because the workspace tool
set is small and fixed and the policy is `ask` (not expressible via the legacy
boolean `tools` config), it is set as **explicit per-tool `permission` entries**
(`"workspace_create": "ask"`, …); a build that honours top-level glob keys may
collapse this to `"workspace_*": "ask"` (§11.5).

Concrete `permission` blocks are in the appendices.

---

## 7. Frontend Behavior

### 7.1 Chat UI

Open-WebUI-style chat layout. Assistant responses are streamed. Tool-call events
are surfaced as visible items (e.g. "Grounding searched", "Note created").
**Implementation note (OpenCode 1.15.0):** tool-call events are NOT available
from the `/event` SSE stream; they are surfaced by fetching the finished message
(`GET /session/{id}/message`) after the `session.idle` event, from the `type:"tool"`
parts of that message.

### 7.2 First-run dialog

Model selection (from the `/v1/models` query) and collection of the active
profile's per-instance bindings (§5.1). The dialog fields are driven by the
profile's binding schema (§6.1 item 5).

### 7.3 Reconfigure

A UI option to change the per-instance bindings and/or model within the active
profile, without manually editing `workspace.json` (§6.4).

### 7.4 Upload

File upload via chat, with conversion behavior per §5.4.

### 7.5 Session model

One OpenCode session per frontend instance — effectively one long-lived session.
Conversation context is retained across turns within that session.

### 7.6 Error handling and display

The frontend evaluates tool-call events and intercepts failures, showing a clear
system message directly rather than leaving the explanation to the agent. This
requires an error-classification layer that maps MCP/runtime error types to
user-facing messages. Error classes are grouped by role:

- **Grounding errors:** authentication (credential expired/invalid), network /
  source unreachable, item not found, malformed query (e.g. invalid CQL/JQL).
- **Workspace errors:** authentication, network / target unreachable, target not
  found, write rejected (remote-Workspace profiles); local I/O error
  (native-Workspace profiles).

The agent still processes the tool result in its loop; the user-facing
explanation is deterministic and comes from the frontend.

If the model endpoint is unreachable at first run, the frontend shows a clear
error and blocks — there is no silent fallback to a hardcoded model.

---

## 8. Launcher Behavior

### 8.1 Pre-flight checks

Before starting processes, the launcher verifies prerequisites (OpenCode / Bun
present) and that the OpenCode server port is free. On a port conflict it aborts
with a clear error message rather than selecting a random port.

### 8.2 Process start

The launcher starts the Python frontend and the OpenCode server. The profile's
MCP server(s) are spawned by the OpenCode server itself (stdio).

### 8.3 Shutdown

On termination (Ctrl+C / window close) the launcher terminates the frontend and
the OpenCode server cleanly. The MCP servers, being children of the OpenCode
server, terminate with it. Running agent tasks are not persisted across a
restart.

### 8.4 Session loss

If the OpenCode server dies, its session is lost. The frontend shows an error and
the user restarts. There is no auto-reconnect and no chat-history recovery in the
MVP.

---

## 9. Open Points & Decisions

### 9.1 Open points / to verify

| # | Item | Note |
|---|------|------|
| O1 | OpenCode HTTP API version pinning | **Validated and pinned at 1.15.0 (2026-05-30):** `opencode serve` exposes a documented OpenAPI 3.1 API (spec at `/doc`) with session CRUD and SSE event streaming — see §10.5. The API shape (event types, session-level agent binding, SSE scope) is empirically verified against **OpenCode 1.15.0** via live spike; see `docs/decisions/D-opencode-http.md`. Re-check `/doc` on any upgrade beyond 1.15.0. |
| O2 | Frontend ↔ OpenCode client generation | **Recommended:** generate the Python client from the live OpenAPI spec at `/doc` rather than hand-writing it, keeping it in lockstep with the pinned version. |
| O3 | Model backend choice | Operator decision. The configured endpoint must be approved for the most sensitive data class the active profile handles (§4.7). The spec states the requirement; it does not mandate a backend. |
| O4 | MCP tool namespacing & permission mapping | **Resolved (v0.5) — see §11.5.** OpenCode registers MCP tools as `<server_key>_<tool_name>` (single-underscore separator); `permission`/`tools` patterns use `*`/`?` wildcards with last-match-wins. The design adopts one MCP server per role, generic bare tool names, and per-role permission scoping. One trivial pinned-version check remains (whether top-level `permission` glob keys are honoured); a documented fallback exists. |
| O5 | Jira Data Center API surface | **To verify before build.** Confirm the Jira DC REST v2 surface; whether issue and comment bodies are best consumed as Jira wiki markup or via `expand=renderedFields` (server-rendered HTML → Markdown); and `atlassian-python-api` `Jira`-client method coverage — all against the pinned Jira version (§11.6). Parallel to O1. |

### 9.2 Deliberately out of MVP scope

- Chat history persistence; auto-reconnect / session recovery.
- Multiple parallel workspaces within one running instance.
- User-editable per-instance system prompt.
- Model routing; subagents.
- A **record/issue-shaped Workspace** interface — writing to Jira (transition,
  field-update, comment, link). The document-shaped Workspace contract of §11.2
  does not fit issue writes; this is deferred until an agent needs to mutate
  Jira. The MVP Jira adapter is Grounding-only.
- Profiles and adapters beyond the four reference profiles.

### 9.3 Confirmed decisions

- Two-role model: read-only Grounding Source(s) + a single read-write Workspace,
  each behind a pluggable adapter; deployment selects a profile.
- **Backend shape is explicit.** Document-shaped backends (Confluence) have a
  body and heading hierarchy; issue/record-shaped backends (Jira) are field sets.
  The §11.1 Grounding interface is a shape-agnostic core plus document-shaped
  extensions; `get` is polymorphic via an adapter-declared `projection` enum.
- **One MCP server per role.** A backend filling both roles runs as two MCP
  server entries; the server key is the tool namespace (§2.3, §11.5).
- Grounding adapters expose no write tools (read-only by construction).
- Workspace write scope and confirmation policy are adapter-declared:
  native-filesystem (sandbox-scoped, auto-execute) or remote (adapter-enforced
  scope, `ask`). The MVP Workspace adapters are both document-shaped.
- The sandbox (launch directory) always exists; it is the workspace itself in
  native-Workspace profiles and scratch/uploads/downloads only otherwise.
  `permission.external_directory` is set to `"deny"` so the sandbox boundary is
  a hard denial.
- Confluence and Jira integration via custom stdio MCP servers, spawned by
  OpenCode; on-prem Data Center deployments, Atlassian SDK, PAT via environment
  variable. Confluence serves either role; Jira serves Grounding only (MVP).
- Frontend ↔ OpenCode via the OpenCode HTTP API; the Python backend is the sole
  client and proxies all browser ↔ OpenCode traffic; one session per instance;
  tool calls visible in the UI.
- The frontend generates `opencode.json` and the agent prompt from the active
  profile + per-instance bindings.
- `bash`, `webfetch`, `websearch`, and subagents (`task`) disabled; native file
  tools active and sandbox-confined; remote-Workspace writes run in `ask` mode.
- One fixed model, no routing; model selected at first run from a `/v1/models`
  query; hard error if the endpoint is unreachable.
- Static, profile-derived system prompt with substituted per-instance variables;
  default language English.
- No chat-history persistence and no auto-reconnect in the MVP.
- Runtime tool errors intercepted by the frontend and shown directly via an
  error-classification layer, grouped by role.

### 9.4 Confluence-adapter open decision (carried from v0.3)

| # | Decision | Note |
|---|----------|------|
| D1 | Include the full-rewrite Workspace operation (`replace`, exposed as `workspace_replace`) in the Confluence Workspace adapter? | The operation is lossy by nature (it round-trips the whole page through Markdown). Default recommendation: include it, keep it `ask`, and clearly label it in the confirmation dialog as a full-page replacement. Irrelevant to the Confluence Grounding server, which has no write tools. |

---

## 10. OpenCode Configuration Reference

> Verified against the official OpenCode documentation and OpenAPI spec on
> 2026-05-23. Field availability is version-dependent; pin a known OpenCode
> version for the deployment (see O1).

### 10.1 Config file: location, format, precedence

- `opencode.json` (or `opencode.jsonc`, JSON-with-comments). Schema reference:
  `https://opencode.ai/config.json` (set as `$schema`).
- Load order, lowest to highest precedence: remote organizational defaults
  (`.well-known/opencode`) → global (`~/.config/opencode/opencode.json`) →
  project (`./opencode.json` in the working directory or nearest Git root).
- Configs are *merged* ("later wins" per key); array fields such as
  `instructions` are concatenated and de-duplicated.
- **`OPENCODE_CONFIG` is NOT honored in OpenCode 1.15.0.** The `OPENCODE_CONFIG`
  environment variable was intended to force a custom config path, but empirical
  testing confirms it is not respected by `opencode serve`/`run` in this version.
  OpenCode discovers the project config by walking up from the **current working
  directory** to the nearest `opencode.json` or git root.

**Design choice (verified OpenCode 1.15.0):** the frontend generates a
project-level `opencode.json` in the launch directory. The launcher starts
OpenCode with its **CWD set to that directory** (not via `OPENCODE_CONFIG`, which
1.15.0 ignores). This guarantees directory-walk discovery finds the generated
config and not a pre-existing global one.

### 10.2 Top-level fields used by this system

| Field | Purpose |
|-------|---------|
| `$schema` | Schema URL for editor validation. |
| `model` | Default model, format `provider/model-id`. |
| `provider` | Custom provider definitions (§10.3). |
| `agent` | Named agent definitions, incl. the dedicated primary agent (§10.3). |
| `mcp` | MCP server definitions — one per role: one per Grounding Source, plus a Workspace server for remote-Workspace profiles (§10.3, §11.5). |
| `permission` | Tool approval rules — `allow` / `ask` / `deny` (§10.4). |
| `instructions` | Array of extra instruction files/globs/URLs, *appended* to the prompt. **Left unset** in this design. |

### 10.3 Generic config skeleton

The structure below is profile-agnostic; `<...>` placeholders and the contents
of `agent.<...>.permission` and `mcp` are filled from the active profile.
Concrete per-profile skeletons are in the appendices.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",

  // Custom OpenAI-compatible provider pointing at the configured endpoint
  "provider": {
    "workspace-llm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Workspace LLM",
      "options": { "baseURL": "<MODEL_ENDPOINT_BASE_URL>" },
      "models": { "<MODEL_ID>": { "name": "<MODEL_DISPLAY_NAME>" } }
    }
  },

  "model": "workspace-llm/<MODEL_ID>",

  // Dedicated primary agent — its `prompt` REPLACES the provider base prompt.
  // `permission` is filled from the active profile (see appendices).
  "agent": {
    "workspace-assistant": {
      "mode": "primary",
      "description": "<PROFILE_DESCRIPTION>",
      "model": "workspace-llm/<MODEL_ID>",
      "prompt": "{file:./workspace-agent.md}",
      "permission": { /* profile-specific — see appendices */ }
    }
  },

  // MCP servers — one per role: one per Grounding Source, plus a Workspace
  // server for remote-Workspace profiles. Filled from the active profile.
  "mcp": { /* profile-specific — see appendices */ }
}
```

Notes on verified behavior:

- **Provider id & API key.** The provider key (`workspace-llm` above) is the
  single constant `frontend.config.PROVIDER_ID`; it must match the `model`
  reference and the key under which a credential is stored in OpenCode's
  `auth.json`. For keyless/local endpoints the frontend writes
  `options.apiKey: "local"`; for authenticated endpoints it **omits** `apiKey`
  and writes the real key to `auth.json` (mode 600) under the isolated oc-home —
  OpenCode only falls back to `auth.json` when `options.apiKey` is *undefined*
  (`provider.ts`: `if (options["apiKey"] === undefined && provider.key) …`), so
  an inline value would shadow the stored credential.
- **System prompt.** An agent's `prompt` replaces the static, provider-specific
  base prompt entirely. `instructions` and any `AGENTS.md`/`CLAUDE.md` in the
  tree are still appended (§6.6). The `prompt` file is read as-is — no
  templating — so the frontend substitutes variables when writing it.
- **MCP `environment`.** Values in the `environment` block are passed to the
  spawned MCP process (merged over the parent environment). This is the verified
  channel for injecting per-backend constants (credentials, base URLs, a
  remote-Workspace scope anchor such as `WORKSPACE_PAGE_ID`, a grounding scope
  hint such as `GROUNDING_PROJECT_KEYS`, and a role flag) — none of these are
  tool parameters the model can set.
- **MCP `command`.** The `command` array is executed verbatim to spawn the
  server. Whoever writes `opencode.json` controls process spawning; here that is
  the frontend, the intended trust boundary. A backend serving two roles is
  spawned twice with different role arguments (§11.5, App. A).
- **Tool naming.** MCP tools are registered to the agent as
  `<server_key>_<tool_name>` (single-underscore separator). The full namespacing
  and permission-mapping scheme is specified in §11.5.

### 10.4 Permissions (verified)

- The `permission` field replaces the deprecated boolean `tools` config
  (deprecated as of OpenCode v1.1.1; merged into `permission`, `true`→`allow` /
  `false`→`deny`; still accepted for backward compatibility).
- Actions are `allow`, `ask`, `deny`. Permissions can be set globally with `*`,
  per tool, or — for most tools — as an object of input-pattern → action rules.
- Pattern matching uses simple wildcards: `*` (zero or more characters), `?`
  (exactly one). Rules are evaluated with the **last matching rule winning**; the
  conventional layout puts the catch-all `*` first and specific rules after.
- `permission.external_directory` governs tool access to paths outside the
  working directory and applies to any path-taking tool (`read`, `edit`, `list`,
  `glob`, `grep`, …). **Its OpenCode default is `"ask"`** (the user is prompted).
  This design sets it explicitly to **`"deny"`** so the sandbox boundary is a
  hard denial — the agent cannot reach outside the launch directory even with a
  user present (§4.4). For native-Workspace profiles this `deny` is also the
  Workspace write-scope enforcement (§4.3).
- `read` defaults to `allow` but `.env` files are denied by default; this design
  keeps that default.
- Permissions may be set at top level and/or inside an agent definition; agent
  rules are merged with and take precedence over global rules. This design sets
  them on the dedicated agent **and** at the top level.
- **Defense-in-depth (verified OpenCode 1.15.0):** the default (unnamed) agent
  is unrestricted — any session not explicitly targeting `workspace-assistant`
  would run without the `permission` denials. To close this gap, the `permission`
  block (denying `bash`, `webfetch`, `websearch`, `task`, and setting
  `external_directory: "deny"`) **must also be set at the top level** of
  `opencode.json`, in addition to inside the agent definition. All sessions and
  all traffic must target the `workspace-assistant` agent.

### 10.5 Server interface (verified)

- `opencode serve [--port <number>] [--hostname <string>] [--cors <origin>]`
  runs the headless HTTP server. For a localhost-only bind, pass an explicit
  `--hostname 127.0.0.1` and a fixed `--port`.
- Optional HTTP basic auth via `OPENCODE_SERVER_PASSWORD` (username defaults to
  `opencode`, override with `OPENCODE_SERVER_USERNAME`). Recommended as
  defense-in-depth even on localhost.
- OpenAPI 3.1 spec is served at `/doc` and is the source for client generation.
- Relevant endpoints:
  - `GET /global/health` — health check (launcher readiness probe).
  - `GET /session`, `POST /session` — list / create sessions.
  - `GET /session/{id}`, `PATCH /session/{id}`, `DELETE /session/{id}`.
  - `POST /session/{id}/message` — send a prompt to the agent.
  - `GET /session/{id}/message` — fetch the finished message (includes
    `type:"tool"` parts with tool name and `state.status`); used to surface
    tool-call events after `session.idle` (§5.3, §7.1).
  - `GET /event` — **global** SSE stream of session events across all sessions.
    **Verified (OpenCode 1.15.0):** the stream carries assistant **text deltas
    only** — event shape `{"type":"message.part.delta","properties":{"sessionID":…,
    "field":"text","delta":"<chunk>"}}` (text at `properties.delta`). Turn end
    is signalled by `{"type":"session.idle","properties":{"sessionID":…}}`.
    **Tool-call progress is NOT in this stream.** Because `/event` is global,
    consumers must filter by `properties.sessionID`. After `session.idle`, fetch
    `GET /session/{id}/message` to obtain tool-call results.
  - `GET /file/content?path=<path>` — read file content within the workspace.
- **Agent binding (verified OpenCode 1.15.0):** the agent is bound at **session
  creation** — `POST /session` with body `{"agent":"workspace-assistant"}`. This
  is the authoritative binding; the open item about the exact parameter name is
  resolved. Messages are sent as `POST /session/{id}/message` with body
  `{"parts":[{"type":"text","text":…}]}`. All sessions must target the
  `workspace-assistant` agent.

**Topology consequence:** the Python frontend's backend process is the OpenCode
HTTP client. It opens the SSE `/event` stream, manages the single session, and
proxies between the browser UI and the OpenCode server, which stays bound to
localhost only.

---

## 11. Backend Interfaces & Adapters

This section specifies the role interfaces and the MVP adapters. An adapter is
the code behind an MCP server (Grounding, or remote Workspace) or, for the native
filesystem, behind OpenCode's built-in tools.

### 11.1 Grounding Source interface (read-only)

A Grounding adapter exposes a **shape-agnostic core** that every Grounding Source
implements, optionally a set of **document-shaped extensions** for backends whose
items have an internal heading hierarchy, and optionally a few **backend-specific
extension tools**. Tool names below are the **bare** names the MCP server
advertises; OpenCode exposes each as `<server_key>_<bare_name>` (§11.5).

**Core (every Grounding adapter):**

| Bare tool | Signature | Returns |
|-----------|-----------|---------|
| `search` | `(query, limit=25)` | list of `{id, title, source, url, excerpt}`. `query` is in the adapter's own query language (CQL, JQL, plain text, …) — the system prompt tells the agent which. |
| `get` | `(id, projection)` | `{id, title, metadata, content}`. `projection` is an **adapter-declared enum** (see below). |
| `list_attachments` | `(id)` | `{id, filename, media_type, size}` |
| `download_attachment` | `(id, filename)` | saved to the sandbox; returns the local path |

**The `projection` parameter.** `get` is polymorphic across backends through an
adapter-declared projection enum, replacing the document-only
`format="markdown"|"outline"` of earlier drafts. Each adapter documents its legal
values; the contract requires a `full` value (the complete item) and at least one
cheaper value, and treats `full` as the default when `projection` is omitted.
Examples: Confluence `{outline, full}` (§11.3); Jira `{summary, full}` (§11.6).
The agent picks the cheapest projection that answers the question and escalates
if needed.

**Document-shaped extensions (document-like backends only).** Backends whose
items have an internal heading hierarchy additionally offer:

| Bare tool | Signature | Returns |
|-----------|-----------|---------|
| `get_section` | `(id, section_id)` | one section as Markdown (`section_id` from the `outline` projection) |
| `list_children` | `(id)` | child items `{id, title}` (the item-containment tree) |

…and accept `projection="outline"` on `get` (the heading tree only).
Issue/record-shaped backends (e.g. Jira) implement none of these — an issue has
no sections and no child-page tree; its relations ride inline on `get` as
fields, and `search` covers "all items under X" (§11.6).

**Backend-specific extension tools.** An adapter may add a small number of tools
for content the core cannot express — e.g. Jira's paginated `get_comments`
(§11.6). These remain read-only and namespaced like every other tool.

- Read-only by construction — no write tool exists on a Grounding adapter, core
  or extension.
- A backend's native representation is converted to Markdown at the adapter
  boundary; lossy conversion is acceptable for comprehension (see §11.3, §11.6).

### 11.2 Workspace interface (read-write)

The Workspace interface is a conceptual contract realised by one of two
mechanisms. Tool names below are the **bare** names; a remote adapter exposes
each as `workspace_<bare_name>` (§11.5).

**Operations (safe → dangerous):**

1. `create(parent_ref, name, body_markdown)` — the **default write path**. New
   content becomes a new item; no pre-existing structure is at risk.
2. `append(ref, body_markdown)` — appends a block; existing content is untouched.
3. `replace_section(ref, section_id, body_markdown)` — replaces only the targeted
   section; the rest is left byte-identical.
4. `replace(ref, body_markdown)` — full rewrite. An explicit, potentially lossy
   exception; used only when the agent authored the whole item or the user
   accepts the loss.

Plus reads: `list()`, `read(ref, format)`, `read_section(ref, section_id)`.

**Realisation:**

- **Native filesystem adapter (§11.4)** — operations map to OpenCode's built-in
  `list`/`read`/`write`/`edit` tools over the sandbox. There is no Workspace MCP
  server; the contract is satisfied by native tools plus the conventions in the
  profile prompt. Confirmation policy: `allow` (auto-execute).
- **Remote adapter (e.g. Confluence, §11.3)** — operations map to the tiered MCP
  write tools, exposed as `workspace_create`, `workspace_append`,
  `workspace_replace_section`, `workspace_replace`. The adapter enforces the
  write scope and holds any representation-conversion logic. Confirmation
  policy: `ask`.

**Scope note — this interface is document-shaped.** The four operations above
assume an item with a body and sections. Record/issue-shaped backends (writing
to Jira) have a different write vocabulary — transition an issue through its
workflow, update fields, add a comment, link issues — that does not fit this
contract. A record-shaped Workspace interface is deferred (§9.2); the MVP
Workspace adapters are both document-shaped (Confluence remote, native
filesystem).

### 11.3 Confluence adapter (Grounding and/or Workspace)

The Confluence adapter can serve **both** roles over a Confluence Data Center
instance. Per §2.3 it is registered as up to two MCP server entries — a Grounding
server and a Workspace server — each started in a single role via a `--role`
argument (§11.5). The two entries share the adapter binary, the PAT, and the
base URL; only the Workspace entry receives `WORKSPACE_PAGE_ID`.

It uses `atlassian-python-api` (the `ConfluenceServer` / `Confluence` client for
Data Center, authenticated with a PAT). It is delivered as a thin stdio MCP layer
over a pre-existing Python wrapper. The wrapper holds the representation-conversion
and scope-enforcement logic; the MCP layer is protocol only.

A custom adapter is required rather than an off-the-shelf Confluence MCP server
because no existing server restricts writes to a page subtree, and existing
servers perform whole-page Markdown↔storage round-trips that are lossy for pages
with macros. The storage↔Markdown conversion may be reused from an open-source
server; the subtree-enforcement and section-splicing layers are bespoke.

**Representations and the conversion boundary.**
Confluence Data Center stores page content in **Confluence Storage Format** — an
XHTML dialect with `ac:` / `ri:` namespaced elements for macros, links, and
attachments. Confluence does not accept Markdown.

- **Storage → Markdown** — used for all *reads* (Grounding reads and remote
  Workspace reads). Lossy for macros and structured content; acceptable for
  comprehension.
- **Markdown → storage** — used only for **agent-authored** Workspace content.
  Headings, lists, tables, links, and inline formatting map cleanly. Fenced code
  blocks map either to the Confluence code macro or to plain `<pre><code>`
  (MVP-acceptable).
- **Core rule:** existing page content must never round-trip through Markdown. It
  is preserved verbatim as opaque storage XHTML; only agent-authored deltas cross
  the conversion boundary. Raw storage XHTML is never exposed to the agent.

**As a Grounding server (`--role grounding`).** A document-shaped Grounding
Source. Advertises the §11.1 core read tools — `search` (CQL queries), `get`,
`list_attachments`, `download_attachment` — the document-shaped extensions
`get_section` and `list_children`, and read extensions `get_page_history` and
`get_labels`. Its `get` projection enum is `{outline, full}`: `outline` returns
the heading tree only (cheap for long pages), `full` the whole body as Markdown.
Registered under a grounding server key (e.g. `confluence`), so the agent sees
`confluence_search`, `confluence_get`, …. Unrestricted; auto-executing.

**As a Workspace server (`--role workspace`).** A document-shaped Workspace.
Advertises the §11.2 bare write ops, mapped to Confluence operations: `create` →
create child page, `append` → append block, `replace_section` → storage-XHTML
section splice, `replace` → full page-body rewrite (the lossy exception — D1,
§9.4). Optionally a Confluence-specific extension `add_label`. Registered under
the workspace server key `workspace`, so the agent sees `workspace_create`,
`workspace_append`, `workspace_replace_section`, `workspace_replace` (and
`workspace_add_label`). All `ask`.

**Long-page handling.** Reading: the agent first requests `projection="outline"`,
then pulls sections with `get_section`; full storage XHTML is never dumped into
context. Writing: because the REST API supports only whole-page updates, the
wrapper holds the full storage body server-side, performs the section splice, and
issues a single full-body `update_page`; the agent only ever sees and returns the
section in question.

**Write-scope enforcement.** For every write op the wrapper verifies the target
page (or `parent_ref`) is the Workspace page or a descendant, by checking the
page's ancestors. The Workspace page ID comes from `WORKSPACE_PAGE_ID` in the
Workspace server's MCP `environment`; it is never a tool parameter. Updates carry
the current page version (optimistic locking); the wrapper fetches the version
immediately before the write. Appends and section replacements are marked as
minor edits to reduce notification noise.

**Excluded from the MVP:** reading or writing comments — this would widen the
write surface beyond page content.

### 11.4 Native filesystem adapter (Workspace only)

A filesystem Workspace requires no adapter code and no MCP server: the §11.2
Workspace contract is satisfied by OpenCode's built-in tools over the sandbox.

- `create` → `write` a new file; `append` / `replace_section` → `edit`;
  `replace` → `write` over an existing file; `list`/`read` → `list`/`read`.
- Markdown is the native on-disk format; there is no conversion boundary.
- Write scope is the sandbox, enforced by OpenCode's path confinement plus
  `permission.external_directory: "deny"` (§10.4).
- Confirmation policy: `allow` — sandbox writes are non-critical (§4.5).
- Structure (file naming, an index/journal file, etc.) is not enforced by the
  adapter; it is established by the profile prompt's conventions (see
  Appendix B).

### 11.5 MCP tool namespacing and permission mapping (resolves O4)

**Verified against the OpenCode docs (mcp-servers, permissions; 2026-05-23):**

- Every tool an MCP server advertises is registered to the agent as
  `<server_key>_<tool_name>`, where `<server_key>` is the key under `mcp` in
  `opencode.json` and `<tool_name>` is the bare name the server advertises. The
  separator is a single underscore. (Example: server key `confluence`,
  advertised tool `search` → the agent sees `confluence_search`.)
- `permission` (and the legacy `tools` config) match tool names with simple
  wildcards — `*` (zero or more characters), `?` (exactly one) — with the last
  matching rule winning. The documented idiom for addressing an entire server's
  tool surface is the server-prefix glob `"<server_key>_*"`.
- The legacy boolean `tools` config is deprecated as of OpenCode v1.1.1 and
  merged into `permission` (`true`→`allow`, `false`→`deny`); it remains accepted.

**Design rule — one MCP server per role.** Each MCP server registered in
`opencode.json` serves exactly one role. Consequences:

- The **server key is the role's namespace.** Grounding servers are keyed by
  source (`confluence`, `jira`, …); the remote Workspace server is keyed
  `workspace`. Tool surfaces never collide because keys differ.
- An MCP server advertises **generic, bare** tool names — the §11.1 / §11.2
  contract names (`search`, `get`, …; `create`, `append`, …) and any extension
  names. It must **not** pre-prefix them with the backend name, or a double
  prefix (`confluence_confluence_search`) would result. The exposed identifier,
  used in `permission` keys and in the system prompt, is always
  `<server_key>_<bare>`.
- A backend that fills **both** roles (Confluence, §11.3) is registered as **two
  server entries**, one per role, each spawned in its single role via a
  `--role` argument. They share the adapter binary, credentials, and base URL;
  they are distinct OpenCode MCP servers with distinct keys.
- Because a Grounding server started in the grounding role advertises no write
  tools at all, "Grounding is read-only by construction" (§4.2) holds
  *literally* — including in Profile A — not merely as a permission policy.

**Permission mapping, per role.** Each server's whole tool surface shares one
policy, so the policy is expressed at the role/server level rather than per
tool:

- *Grounding (allow-only).* Use the server-prefix glob `"<source>_*": "allow"`.
  This is robust: even if a pinned build did not honour glob keys in
  `permission`, the documented-equivalent legacy form
  `"tools": { "<source>_*": true }` (boolean `true` ⇒ allow) covers the
  allow-only case exactly.
- *Workspace (ask).* `ask` cannot be expressed by the boolean `tools` config, so
  it must go through `permission`. The Workspace tool set is small and fixed
  (four generic ops + an optional `add_label`), so it is set as **explicit
  per-tool `permission` entries** — `"workspace_create": "ask"`,
  `"workspace_append": "ask"`, `"workspace_replace_section": "ask"`,
  `"workspace_replace": "ask"` (`"workspace_add_label": "ask"` if used). This
  form depends only on `permission` honouring exact MCP-tool-named keys, which
  v0.3 verified. A build that also honours glob keys at `permission` top level
  may collapse the five entries to `"workspace_*": "ask"`.

**Multiple Grounding Sources.** Distinct sources are distinct server keys, hence
distinct prefixes — no tool-name collision is possible. Each gets its own
`"<source>_*": "allow"` rule; the system prompt names each source by its prefix
and states its query language so the agent can choose among them. Profile D
(Appendix D) is a concrete instance: a `jira` grounding server alongside a
Confluence `workspace` server.

**Residual version check.** One item remains for the pinned-version pre-flight
(O1): confirm whether the pinned OpenCode build honours a *top-level* `permission`
key of glob form (`"<server_key>_*"`). If yes, both roles may use the compact
one-line glob. If no, the design still holds unchanged — grounding via the legacy
`tools` glob, workspace via the explicit per-tool `permission` entries. Either way
this is a one-line config check, not an open design question.

### 11.6 Jira adapter (Grounding only, MVP)

The Jira adapter exposes an **issue-shaped** Grounding Source over a Jira Data
Center instance. It uses the `Jira` client of `atlassian-python-api`,
authenticated with a Personal Access Token (PAT) — consistent with the Confluence
adapter (§11.3). Like the Confluence adapter it is a thin stdio MCP layer over a
Python wrapper, started in the grounding role, registered under the server key
`jira` (so the agent sees `jira_search`, `jira_get`, …).

> **Scope.** Jira can in principle serve the Workspace role too, but its write
> surface is record-shaped — transition, field-update, comment, link — and does
> not fit the document-shaped Workspace contract of §11.2. A record-shaped
> Workspace interface is deferred (§9.2); the MVP Jira adapter serves the
> **Grounding role only** and exposes no write tools.

**Tool surface.** Jira implements the §11.1 **core only** — no document-shaped
extensions (an issue has no heading hierarchy or child-page tree) — plus one
backend-specific extension:

| Bare tool | Signature | Notes |
|-----------|-----------|-------|
| `search` | `(jql, limit=25)` | `query` is **JQL**. Per-issue result `{id, title, url, excerpt}`: `id` = issue key (`PROJ-123`), `title` = summary, `url` = browse link, `excerpt` = a status / assignee line (issues have no natural snippet). |
| `get` | `(issue_key, projection)` | projection enum `{summary, full}`. `summary` = key fields (status, type, assignee, priority, labels) without the description body or comments — cheap. `full` (default) = the full field set including the description and the recent-comments window. |
| `list_attachments` | `(issue_key)` | §11.1 core. |
| `download_attachment` | `(issue_key, filename)` | §11.1 core; saves to the sandbox. |
| `get_comments` | `(issue_key, limit=20, before=null)` | **backend-specific extension** — paginated comment retrieval, newest-first, for threads longer than the window `get` returns. |

`get_section` and `list_children` are **not** implemented. An issue's relations
(subtask keys, epic/parent link, issue links) ride inline on `get` as fields, so
the agent navigates by calling `get` again on a related key; `search` (JQL)
covers "all issues in a project / epic / sprint".

**Comments are first-class content.** A `full` `get` includes a `comments`
field: the most recent N comments (default ~20), newest-first, each
`{author, created, updated, body_markdown}`. The return also carries
`comment_count` (the total) and a `comments_truncated` boolean. When
`comments_truncated` is true the agent can page the remainder with
`get_comments`. Comments are kept inside `get` (rather than requiring a separate
call) so a single `get` returns the whole picture; `get_comments` exists only
for the long-thread tail.

**Conversion boundary (Jira Data Center).** Jira Data Center stores issue
descriptions and comments as **Jira wiki markup** over REST API v2 — *not* ADF
(Atlassian Document Format), which is the Cloud representation. The adapter
converts wiki markup → Markdown for the `description` and comment bodies. A more
robust option is to request `expand=renderedFields`, take Jira's server-rendered
HTML, and convert HTML → Markdown — avoiding a bespoke wiki-markup parser and
covering comments by the same path; this should be decided during the O5
verification. Either way the conversion is **lossy, and that is acceptable for
grounding** (the read-side rule of §11.3): `@mentions`, inline attachment/issue
links, and quoted prior comments may degrade to plain text. The adapter records
this as a known limitation rather than guaranteeing fidelity.

**Custom-field resolution.** Jira custom fields are opaque IDs
(`customfield_10234`). The adapter resolves IDs to human-readable names via the
field-metadata API and presents `get` results keyed by name. This ID→name
resolution is the structured-data analogue of the Confluence storage↔Markdown
boundary.

**Optional grounding scope.** Grounding is unrestricted by default. An optional
`GROUNDING_PROJECT_KEYS` environment variable (the analogue of Confluence's
`GROUNDING_SPACE_KEYS`) makes the adapter AND a project-scope clause onto every
JQL query, to cut noise. If used, the adapter must compose JQL **safely** —
parenthesise the agent-supplied query before ANDing the scope clause — so a
malformed or overly broad query cannot escape the intended scope.

**Verify before build (O5).** The exact Jira Data Center REST v2 surface, the
wiki-markup vs. `renderedFields` decision, and `atlassian-python-api` `Jira`-client
method coverage should be checked against the pinned Jira version before
implementation — parallel to O1 for OpenCode.

---

## Appendix A — Profile A: Confluence Workspace Assistant

The v0.3 system, expressed as a profile. The agent reads and searches Confluence
for grounding and writes its deliverables back into one designated Confluence
page subtree.

**Bindings.**

- **Grounding:** Confluence adapter in `--role grounding` — unrestricted
  search/read across the instance. Server key `confluence`.
- **Workspace:** Confluence adapter in `--role workspace` — the **Workspace page
  + its subtree**. Server key `workspace`.
- The single Confluence backend is therefore registered as **two MCP server
  entries** (§2.3, §11.5). Same adapter binary, same PAT and base URL; only the
  Workspace entry carries `WORKSPACE_PAGE_ID`.

**Per-instance binding schema (first run).** A Confluence Workspace page,
supplied as a page URL or page ID; resolved to a page ID and confirmed by title +
space.

**Confirmation policy.** Grounding reads `allow`; Confluence write ops `ask`
(diff/preview dialog).

**System prompt (template summary).** The agent is a Confluence Workspace
assistant: unrestricted Confluence read/search via the `confluence_*` tools
(query language CQL); writes confined to the Workspace subtree via the
`workspace_*` tools; uploads and downloads in the sandbox. Prefer the safe write
path (`workspace_create`) for long outputs. Does not announce write actions in
advance (the confirmation dialog covers approval).

**`opencode.json` — profile-specific fragments.**

```jsonc
{
  "agent": {
    "workspace-assistant": {
      "mode": "primary",
      "description": "Confluence Workspace assistant",
      "model": "workspace-llm/<MODEL_ID>",
      "prompt": "{file:./workspace-agent.md}",
      "permission": {
        // Built-in tools
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
        "external_directory": "deny",
        "read": "allow",
        "write": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",

        // Grounding server `confluence` — read-only, whole surface allowed
        "confluence_*": "allow",

        // Workspace server `workspace` — explicit per-tool `ask`
        // (collapsible to "workspace_*": "ask" if the build honours glob keys)
        "workspace_create": "ask",
        "workspace_append": "ask",
        "workspace_replace_section": "ask",
        "workspace_replace": "ask",
        "workspace_add_label": "ask"
      }
    }
  },

  // Same Confluence backend, registered twice — one server per role
  "mcp": {
    "confluence": {
      "type": "local",
      "command": ["<INTERPRETER>", "<PATH_TO_CONFLUENCE_MCP>", "--role", "grounding"],
      "enabled": true,
      "environment": {
        "CONFLUENCE_BASE_URL": "<CONFLUENCE_BASE_URL>",
        "CONFLUENCE_PAT": "<CONFLUENCE_PAT>"
      }
    },
    "workspace": {
      "type": "local",
      "command": ["<INTERPRETER>", "<PATH_TO_CONFLUENCE_MCP>", "--role", "workspace"],
      "enabled": true,
      "environment": {
        "CONFLUENCE_BASE_URL": "<CONFLUENCE_BASE_URL>",
        "CONFLUENCE_PAT": "<CONFLUENCE_PAT>",
        "WORKSPACE_PAGE_ID": "<RESOLVED_WORKSPACE_PAGE_ID>"
      }
    }
  }
}
```

> `workspace_replace` is subject to D1 (§9.4): include it, keep it `ask`, label
> it as a full-page replacement. Drop the `workspace_add_label` entry if the
> `add_label` extension is not enabled.

---

## Appendix B — Profile B: Local Notes with Confluence Grounding

A daily-notes agent. The agent captures notes into a **local** workspace and
consults Confluence **only for grounding** — it never edits Confluence.

**Bindings.**

- **Grounding:** Confluence adapter in `--role grounding` — search/read for
  grounding. Server key `confluence`.
- **Workspace:** native filesystem adapter — the sandbox directory.
- **No Workspace MCP server.** Confluence is bound to the Grounding role only;
  there is no second Confluence server entry, no `workspace` server, and no
  `WORKSPACE_PAGE_ID`.

**Per-instance binding schema (first run).** Optionally, a Confluence space (or
set of spaces) to scope grounding searches, and a notes directory name within
the sandbox (default `notes/`). No write target is collected — there is none to
resolve.

**Confirmation policy.** Grounding reads `allow`; native file writes `allow`
(sandbox, auto-execute). No `ask` paths — there is no remote write.

**What collapses relative to Profile A.** Only one Confluence MCP server (the
grounding one); no subtree enforcement, no `WORKSPACE_PAGE_ID`, no
Markdown→storage conversion, no write-confirmation dialog, and D1 is moot. The
conversion boundary is one-directional (storage→Markdown) and lossy-is-fine.

**System prompt (template summary).** The agent is a daily-notes assistant. Its
workspace is the local `notes/` directory; it captures notes there following a
convention: one Markdown file per day, `notes/YYYY-MM-DD.md`, and a running
`notes/index.md` it appends to. It uses the `confluence_*` Grounding tools
(query language CQL) to search and read for context and to ground statements,
citing the Confluence page title/URL it drew from. It must **not** attempt to
modify Confluence — it has no tool to do so. Uploads and Grounding attachment
downloads are in the sandbox, reachable via `read`.

**B-note (prompt-append caveat).** Because this profile writes into the sandbox
routinely (§6.6), the `AGENTS.md`-append caveat is marginally more salient: an
agent-authored `notes/AGENTS.md` would not be auto-appended (OpenCode discovers
`AGENTS.md` at the project / Git root, not arbitrary subdirectories), but a
root-level `AGENTS.md` would. Keeping notes under a `notes/` subdirectory and
leaving `instructions` unset keeps this benign for the MVP; if stricter isolation
is wanted, a future revision can point the OpenCode working directory at a
scratch root and mount `notes/` as a sibling.

**`opencode.json` — profile-specific fragments.**

```jsonc
{
  "agent": {
    "workspace-assistant": {
      "mode": "primary",
      "description": "Local daily-notes assistant with Confluence grounding",
      "model": "workspace-llm/<MODEL_ID>",
      "prompt": "{file:./workspace-agent.md}",
      "permission": {
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
        "external_directory": "deny",

        // Native filesystem tools ARE the Workspace here — auto-execute
        "read": "allow",
        "write": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",

        // Grounding server `confluence` — read-only, whole surface allowed
        "confluence_*": "allow"

        // No `workspace_*` tools exist in this profile — no Workspace MCP server.
      }
    }
  },

  "mcp": {
    "confluence": {
      "type": "local",
      "command": ["<INTERPRETER>", "<PATH_TO_CONFLUENCE_MCP>", "--role", "grounding"],
      "enabled": true,
      "environment": {
        "CONFLUENCE_BASE_URL": "<CONFLUENCE_BASE_URL>",
        "CONFLUENCE_PAT": "<CONFLUENCE_PAT>",
        "GROUNDING_SPACE_KEYS": "<OPTIONAL_RESOLVED_SPACE_KEYS>"
      }
    }
  }
}
```

> The Confluence MCP server runs in the **grounding** role, so — as a matter of
> construction, not permission policy — it exposes no write tools (§4.2, §11.5).
> `GROUNDING_SPACE_KEYS` is optional and only scopes search.

---

## Appendix C — Profile C: Standup Assistant (Jira grounding, local notes)

A triage / standup agent. The agent grounds in Jira and captures notes into a
**local** workspace — it never edits Jira. This is Profile B with a Jira
Grounding Source in place of Confluence, and it needs no document-shaped
extensions: the issue-shaped core suffices.

**Bindings.**

- **Grounding:** Jira adapter in `--role grounding` — JQL search and issue
  reads. Server key `jira`.
- **Workspace:** native filesystem adapter — the sandbox directory.
- **No Workspace MCP server.**

**Per-instance binding schema (first run).** Optionally, Jira project key(s) to
scope grounding searches (`GROUNDING_PROJECT_KEYS`); a notes directory name
within the sandbox (default `notes/`). No write target is collected.

**Confirmation policy.** Grounding reads `allow`; native file writes `allow`. No
`ask` paths — there is no remote write.

**System prompt (template summary).** The agent is a standup / triage assistant.
Its workspace is the local `notes/` directory; it captures notes there as one
Markdown file per day `notes/YYYY-MM-DD.md` plus a running `notes/index.md`. It
uses the `jira_*` Grounding tools to search (**query language: JQL**) and read
issues and their comments for context, citing issue keys (`PROJ-123`). It reads
issue comments via the recent-comments window in `jira_get` and pages older ones
with `jira_get_comments` when needed. It must **not** attempt to modify Jira — it
has no tool to do so.

**`opencode.json` — profile-specific fragments.**

```jsonc
{
  "agent": {
    "workspace-assistant": {
      "mode": "primary",
      "description": "Standup assistant — Jira grounding, local notes",
      "model": "workspace-llm/<MODEL_ID>",
      "prompt": "{file:./workspace-agent.md}",
      "permission": {
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
        "external_directory": "deny",

        // Native filesystem tools ARE the Workspace here — auto-execute
        "read": "allow",
        "write": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",

        // Grounding server `jira` — read-only, whole surface allowed
        "jira_*": "allow"

        // No `workspace_*` tools — no Workspace MCP server.
      }
    }
  },

  "mcp": {
    "jira": {
      "type": "local",
      "command": ["<INTERPRETER>", "<PATH_TO_JIRA_MCP>", "--role", "grounding"],
      "enabled": true,
      "environment": {
        "JIRA_BASE_URL": "<JIRA_BASE_URL>",
        "JIRA_PAT": "<JIRA_PAT>",
        "GROUNDING_PROJECT_KEYS": "<OPTIONAL_RESOLVED_PROJECT_KEYS>"
      }
    }
  }
}
```

> The Jira MCP server runs in the **grounding** role and exposes no write tools
> (§4.2, §11.6). `GROUNDING_PROJECT_KEYS` is optional and only scopes JQL search.

---

## Appendix D — Profile D: Ticket-to-Status-Page Assistant (Jira grounding, Confluence Workspace)

The configuration that exercises the v0.4 split most directly: the Grounding
Source and the Workspace are **different backends**. The agent reads Jira issues
for context and writes status summaries into a designated Confluence page
subtree.

**Bindings.**

- **Grounding:** Jira adapter in `--role grounding` — server key `jira`.
- **Workspace:** Confluence adapter in `--role workspace` — server key
  `workspace`, a Confluence Workspace page + its subtree.
- Two MCP servers, **two different backends**, one role each. There is no
  Confluence *grounding* server and no Jira *workspace* server.

**Per-instance binding schema (first run).** A Confluence Workspace page
(URL/ID → resolved page ID, confirmed by title + space); optionally Jira project
key(s) for grounding scope.

**Confirmation policy.** Jira grounding reads `allow`; Confluence `workspace_*`
writes `ask` (diff/preview dialog).

**System prompt (template summary).** The agent produces status pages. It reads
Jira issues via the `jira_*` tools (**query language: JQL**; `jira_get` for
issue detail and recent comments, `jira_get_comments` for long threads) and
writes status summaries into the Confluence Workspace subtree via the
`workspace_*` tools, preferring `workspace_create` for new pages. It cites the
Jira issue keys it summarised. It cannot modify Jira (no tool exists) and cannot
write Confluence outside the Workspace subtree (adapter-enforced — §4.3).

**`opencode.json` — profile-specific fragments.**

```jsonc
{
  "agent": {
    "workspace-assistant": {
      "mode": "primary",
      "description": "Ticket-to-status-page assistant — Jira grounding, Confluence Workspace",
      "model": "workspace-llm/<MODEL_ID>",
      "prompt": "{file:./workspace-agent.md}",
      "permission": {
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "task": "deny",
        "external_directory": "deny",
        "read": "allow",
        "write": "allow",
        "edit": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",

        // Grounding server `jira` — read-only, whole surface allowed
        "jira_*": "allow",

        // Workspace server `workspace` (Confluence) — explicit per-tool `ask`
        "workspace_create": "ask",
        "workspace_append": "ask",
        "workspace_replace_section": "ask",
        "workspace_replace": "ask",
        "workspace_add_label": "ask"
      }
    }
  },

  // Two backends — Jira in the grounding role, Confluence in the workspace role
  "mcp": {
    "jira": {
      "type": "local",
      "command": ["<INTERPRETER>", "<PATH_TO_JIRA_MCP>", "--role", "grounding"],
      "enabled": true,
      "environment": {
        "JIRA_BASE_URL": "<JIRA_BASE_URL>",
        "JIRA_PAT": "<JIRA_PAT>",
        "GROUNDING_PROJECT_KEYS": "<OPTIONAL_RESOLVED_PROJECT_KEYS>"
      }
    },
    "workspace": {
      "type": "local",
      "command": ["<INTERPRETER>", "<PATH_TO_CONFLUENCE_MCP>", "--role", "workspace"],
      "enabled": true,
      "environment": {
        "CONFLUENCE_BASE_URL": "<CONFLUENCE_BASE_URL>",
        "CONFLUENCE_PAT": "<CONFLUENCE_PAT>",
        "WORKSPACE_PAGE_ID": "<RESOLVED_WORKSPACE_PAGE_ID>"
      }
    }
  }
}
```

> The two roles are served by different adapter binaries against different
> Atlassian products. The system prompt must name each tool namespace and its
> query language (`jira_*` → JQL, read-only; `workspace_*` → Confluence writes,
> `ask`). `workspace_replace` is subject to D1 (§9.4).
