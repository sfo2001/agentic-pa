# Ingest becomes propose-confirm with deterministic frontend apply, and a Sweep re-sources Ingest from the conversation transcript to build a Diary

The notes assistant gains a **Sweep**: on demand, the frontend turns the live
OpenCode conversation transcript into filed structure (a **Diary** entry plus
**Actions**/**Topic** updates) by feeding it through the *existing* **Ingest**
segmentation. As part of this, **all Ingest** — transcript-sourced and user-dropped
`inbox/` files alike — moves from **auto-file** to **propose → confirm → write**,
where the agent emits a structured proposal and the **frontend applies it
deterministically**.

## Context

OpenCode already persists the full transcript losslessly and exposes it via the
documented `GET /session/{id}/message` API (`docs/decisions/D-opencode-http.md`), so
no capture layer is needed — the raw record exists; only *structuring* is missing.
Ingest (`notes-agent.md`) already segments a raw capture into structure. A solo
braindump, however, is **not** a Meeting (CONTEXT.md), so its narrative output is a
new backward-looking, accreted artifact — the **Diary** (`workspace/diary/…`),
distinct from the forward-looking, regenerated **Brief**.

## Decision

1. **Sweep = Ingest, re-sourced.** The frontend snapshots transcript-since-watermark
   into size-bounded `inbox/` capture files and runs the existing Ingest over each.
   No second segmentation pipeline.
2. **Diary is a first-class output** of Ingest, appended to
   `workspace/diary/YYYY-MM-DD.md`. A Meeting is produced only if a real gathering
   was recounted.
3. **All Ingest is propose-confirm.** The agent emits a structured proposal and
   writes nothing; the frontend renders it; on confirm it applies the proposal.
4. **Apply is deterministic and frontend-owned.** What the user confirms is
   byte-for-byte what is written — no second model pass.

## Considered options (ruled out)

- **A new parallel sweep pipeline** — duplicates segmentation/filing and risks the
  two paths drifting; rejected in favour of reusing Ingest.
- **Auto-file + git-undo** (Ingest's current behavior, undo already exists) —
  rejected because a transcript is noisier than a deliberately-dropped note, so
  unreviewed thoughts would land first; propose-confirm gates the noisy source.
- **Second agent pass writes on confirm** — non-deterministic (what lands may drift
  from what was approved) and doubles model cost; rejected for deterministic apply.
- **Staging area + promote** — extra plumbing and awkward partial-confirm; rejected.

## Consequences

- **Boundary shift:** the frontend, previously the writer only of *derived*
  structure (the Index) and the git owner (ADR-0003), now also writes Ground-Truth
  *content* (diary, actions, topic edits) from confirmed proposals. The agent's role
  for a Sweep narrows to *proposing*. This is what makes confirm-equals-what-lands
  hold, and it keeps the sandbox intact (the agent still never touches anything
  outside the workspace; the transcript is read by the frontend, not the agent).
- **Open actions snapshot regeneration:** when a topic is edited by a confirmed
  proposal, its trailing `## Open actions (as of YYYY-MM-DD)` block is regenerated
  from the current `tasks.todo.txt`, filtered to actions tagged with `+<slug>`.
  This is a frontend responsibility (proposal applier), not the agent's — the
  agent's only job for that block is to *omit* it from the proposal (the applier
  will rebuild it). See `frontend/proposal.py::_regenerate_open_actions_block`.
- **Sweep state location:** the per-session watermark (`.sweep-state.json`) lives
  in the notes git-dir (e.g. `notes.git/.sweep-state.json`), outside the agent's
  `workspace/` sandbox. The state file is git metadata (it describes the agent's
  progress through OpenCode's transcript) and the agent must never be able to
  read or write it via its file tools. See ADR-0005 for the sandbox layout.
- **Proposal validation policy:** the Pydantic v2 model at the `/api/sweep/confirm`
  HTTP boundary (`SweepConfirm`) hard-rejects malformed input (slugs that escape
  the regex, sections outside the known literal set, lists over the cap) with
  422. The applier itself (`proposal.apply_proposal`) is more lenient: it
  silently drops bad items and caps lists, so direct callers (tests, scripts)
  don't have to pre-validate. This split keeps the HTTP boundary strict without
  making the applier fragile.
- **Action sanitization:** action strings are stripped of *real* control
  characters that could smuggle a second action line into `tasks.todo.txt`:
  C0 controls (`\x00`..`\x08`, `\x0E`..`\x1F`, `\x7F`), real `\r\n\t\v\f`
  bytes, and Unicode line/paragraph separators (U+2028, U+2029, U+0085). The
  *two-character escape sequences* `\n`, `\r`, `\t` (backslash + letter) are
  NOT stripped — they are legitimate content (e.g. a Windows path `C:\new`);
  the file format splits on real newline bytes, not on the literal text
  `\` + letter. This stops an LLM from smuggling a second action line into
  the file by writing `(A) line one<LF>(B) line two` — only the first line
  lands. See `frontend/proposal.py::apply_proposal` for the regex.
- **Behavior change:** existing drop-file Ingest no longer auto-files — users who
  relied on that now confirm first. Recorded here so a future reader does not "fix"
  it back to auto-file.
- **New contract:** a structured proposal schema between the agent's output and the
  frontend applier (schema fixed at implementation time).
- `diary/` needs no housekeeping change — Index/orphan lint already scope to
  `topics/`+`meetings/` (`frontend/wiki.py`).

## References

- Builds on ADR-0003 (frontend owns git), ADR-0005 (sandbox), ADR-0007 (Ingest as a
  conventions layer). Transcript surface: `docs/decisions/D-opencode-http.md`.
- **Propose MCP tool:** the `present_propose` tool is served by the **present MCP
  server** (ADR-0006), alongside `present_present`. The server key `present`
  namespaces both tools as `present_<name>` for the agent.
- Deferred (trigger-gated): idle auto-trigger; Sweep as the *sole* structurer;
  auto-file toggle. See ROADMAP and the design spec.
