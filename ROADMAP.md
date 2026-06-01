# agentic-pa — Roadmap

The Chief-of-Staff Notes Assistant. This file is the single place the project's
direction is tracked; the deferred items below used to live scattered across the
README, the design spec, and `workspace-assistant-spec.md`.

**Philosophy (same as lwt-wiki):** each planned item has a **Trigger** that says
*when* to actually build it. Speculative implementation costs more than waiting —
build a phase when its trigger fires, not before. Newest at the top.

---

## ▶ Now — make it usable, then dogfood

The one active track. It is not a feature; it is the thing that unblocks
everything else: the assistant has to be **fast enough to live in** before more
capability is worth adding.

- **Run it on real hardware.** Turns take minutes on the 16 GB box (the 36B-A3B
  MoE spills ~50 % to CPU). A 48 GB card (e.g. Radeon PRO W7800) holds the model
  resident → ~30–60 s turns → genuinely usable. This is the gate to daily use.
- **Dogfood it.** Use it for actual day/week triage and note-filing. Real use is
  what surfaces the next priorities — this session's eval already produced three
  shipped fixes (topic dedup, document-link convention, the `present_present`
  tool-name correction) that no amount of speculation would have found.
- **Continuous prompt / UX hardening** from those findings — the software side of
  this track. Small, frequent `notes-agent.md` / convention fixes as live use
  exposes gaps.

*No trigger — this is the current focus.* Everything below waits for its trigger.

---

## ✅ Already shipped

| Tag / date | What |
|---|---|
| **v0.1.0** · 2026-06-01 | First tagged release (setuptools-scm, version from git tags). |
| 2026-06-01 | **CI hardening** — matrix `ubuntu + windows × 3.10/3.11/3.12/3.13`, SHA-pinned actions, `pip cache`, pinned lwt-wiki install ref, non-blocking `pip-audit` job. Python floor lowered to 3.10. |
| 2026-05-31 | **lwt-wiki integration** (ADR-0007) — document **ingest** with traceability frontmatter, **`notes_search`** (BM25 over the Ground Truth), frontend-push **lint**, and a **code-owned `index.md`**, as a conventions layer over the existing topic/meeting/task model. The read-only Agenda server broadened into the **Ground Truth service**. |
| 2026-05-31 | **Presentation pane** (ADR-0006) — a `present_present(path)` MCP signal renders a workspace Artifact read-only beside the conversation, server-side sanitized. |
| (M1) | **Local-only MVP** — topic-centric Ground Truth, deterministic Agenda engine (read-only MCP), sandboxed OpenCode agent, frontend proxy + notes git versioning, one-command launcher. ADRs 0001–0005. |

Design history: `docs/superpowers/specs/` and `docs/superpowers/plans/`; decisions in `docs/adr/`.

---

## 🔭 Planned (trigger-gated)

### Milestone 2 — external grounding (the north star)

The corpus model (one read service per corpus, provenance in every citation) was
built forward-compatible so these slot in cleanly. Full design:
`workspace-assistant-spec.md` (v0.6); terminology in `CONTEXT.md`
(**Ground Truth** = local, native-file-read; **Grounding Source** = external,
read-only, behind an MCP adapter).

#### Phase A — read-only Confluence Grounding Source

**What.** An MCP adapter exposing read+search over a Confluence instance as a
**Grounding Source** — a *separate* tool/corpus from the local Ground Truth, never
federated into one ranked list; answers cite which corpus they came from.
Structurally it mirrors the existing `notes` / `present` MCP servers.

**Why.** The first real step beyond the local notes: ground answers in the team's
existing knowledge base without copying it in.

**Trigger.** You have a Confluence instance you actually want to ground against.

**Rough effort.** Medium — one MCP server (auth + read + search), config wiring in
`frontend/config.py`, prompt guidance on provenance/citation.

#### Phase B — Jira Grounding Source

**What.** Same pattern as Phase A for Jira (issues as a read-only Grounding
Source). lwt already has a Confluence client that the ingest/grounding sides could
share.

**Trigger.** After Phase A, and a Jira instance to ground against.

#### Phase C — remote read-write Workspace

**What.** A **Workspace** abstraction distinct from grounding: writing back to the
system of record (e.g. Jira transitions), so the assistant's actions land in the
real backend rather than only the local notes tree.

**Why.** Today the Workspace is always the local notes leaf. Teams that live in
Jira/Confluence need the assistant to act there.

**Trigger.** The local notes tree stops being the source of truth — you need
write-back to the external system.

**Rough effort.** Large — a read-write adapter contract + the sandbox/permission
story for an external mutating backend.

#### Phase D — deployment profiles

**What.** A named bundle selecting a **Workspace** adapter + one or more
**Grounding Sources** (Appendices C/D of the spec: Jira+local, Jira+Confluence on
*different* backends).

**Trigger.** ≥2 distinct deployment shapes are actually needed.

---

### qmd semantic search

**What.** Upgrade `notes_search` from BM25-only to hybrid (qmd: BM25 + vector +
rerank) for large notes trees.

**Why.** BM25 misses synonyms/paraphrase once a corpus is large. lwt's own roadmap
documents the qmd path and the cost trade-off (~2 GB model + 1–3 s startup).

**Trigger.** The notes tree crosses ~200–300 pages, or missed-search complaints
surface. (Today's tree is tiny → premature.)

---

### Publish the notes externally (`lwt deploy`)

**What.** Render/serve the notes (mkdocs / docker / Confluence) using lwt's deploy
backends.

**Why.** Currently the notes are private/local and the Presentation pane already
renders them in-app.

**Trigger.** A real need to publish the notes to an external audience.

---

## 🗄 Deferred (consciously parked)

| Item | Why deferred | Revisit when |
|---|---|---|
| `lwt update` / manifest / three-way merge | We pin lwt-wiki to a commit SHA (`LWT_REF`) and bump deliberately; lwt's self-distribution story is irrelevant here. | We ship lwt-scaffolded wikis to others. |
| `windows-latest` → `windows-2025` runner migration | GitHub auto-migrates the image by 2026-06-15; no action needed. | A Windows CI break traces to the image change. |
| A formal release pipeline (wheels / PyPI) | agentic-pa is installed editable from source, not published; `v0.1.0` is for version identity, not distribution. | We need installable artifacts for others. |

---

## How to use this file

- **Adding an item:** prefer extending an existing phase to creating a new one.
  Each item is one focused capability with a clear trigger; resist roadmap
  inflation.
- **Shipping an item:** move it from *Planned* to *Already shipped* with the date
  (and tag, if it coincides with a release); keep the original What / Why as the
  historical record.
- **Killing an item:** move it under *Deferred* with a one-line note on why it
  never happened.
