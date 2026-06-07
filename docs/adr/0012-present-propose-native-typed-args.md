# `present_propose` exposes native typed args (diary / actions / topics / meetings), not a single JSON-string blob

The `present_propose` MCP tool's public argument shape changed from
`propose(proposal: str)` to `propose(diary: str, actions: list[str] | None,
topics: list[dict] | None, meetings: list[dict] | None)`. The hard validation
(size cap, JSON shape, field caps, `+tag<->topic`, tickler-after-due, atomic
staging) is unchanged — it moved into a private `_propose_payload(json_str)` seam
that the public tool delegates to. The on-disk `inbox/_proposal.json` and the
frontend confirm path are byte-for-byte unchanged. **This is a breaking change
to the MCP tool surface** (a `presenter` package MAJOR bump in semver terms;
the project's setuptools-scm version is bumped at the next tag).

## Context

Local function-calling models would not emit `present_propose`. Across both
`qwen3.6` and `qwen3-coder` sessions the tool fired **0 times** while
plainly-typed tools fired hundreds, because its sole argument was a
stringified-JSON blob the model had to escape inline. Reasoning models
hallucinated the call as `<tool_call>` text; coder models deferred to read-only
tools indefinitely (one live session: 208 read-only calls, 0 proposes).

The root cause is well known in the function-calling literature: stringified-
JSON args are an antipattern for typed tool surfaces. Models reliably fill in
*typed* parameters and reliably fail at escaping nested quotes / special
characters inside a single string. The MCP tool is a strongly-typed surface
(native `list[str]`, `list[dict]`) and the stringification was costing real
ingest throughput.

## Decision

1. **The public `propose` tool exposes four native typed parameters.** All four
   default to empty so a `diary`-only call is still a valid (empty) proposal,
   matching the prior contract. The `diary` field is required non-empty when
   any of `actions / topics / meetings` are present (preserved invariant).
2. **Validation moves into a private `_propose_payload(proposal: str)` seam.**
   The public `propose(diary, actions, topics, meetings)` assembles a JSON
   string from the typed args and delegates. The size cap, `+tag<->topic`
   check, tickler-after-due rule, field caps, and atomic staging all stay in
   `_propose_payload` — the single place where validation lives, directly
   unit-testable. The 14 existing `TestPropose` cases rewire to
   `_propose_payload`; 3 new `TestPropose.test_propose_native_*` cases
   exercise the public glue end-to-end.
3. **No on-disk format change.** `inbox/_proposal.json` shape and the
   `/api/proposal/confirm` apply path are byte-for-byte unchanged. The wire
   surface between the agent and the frontend is what shifted, not the wire
   surface between the frontend and the apply layer.

## Consequences

- **Breaking change for the MCP tool surface.** Any external caller that
  invoked `propose(json_string)` must migrate to `propose(diary=..., ...)` with
  native args. Within this repo the only external consumer is the agent
  itself (the system prompt and the in-test direct callers); both are updated
  by the same series.
- **Surfaces that document the prior signature and need to be updated in
  this series** (cross-references for future readers; the agent reads the
  prompt, humans read the rest):
  - `frontend/assets/notes-agent.md` — the agent's system prompt (lines 28,
    121, 126 in the prior version). Critical because the LLM demonstrably
    reads the prompt, and a stale prompt defeats the fix.
  - `presenter/pyproject.toml:4` — the package `description` shown on PyPI /
    packaging metadata.
  - `README.md:30` — the package table line in the README.
  - `docs/adr/0006-presentation-pane.md` — the prose around `propose(proposal)`.
  - `docs/adr/0009-propose-confirm-ingest-and-diary-sweep.md` — references
    the prior shape.
  - `docs/adr/0011-restrict-write-mode-frontend-sole-writer.md` — names
    `present_propose(json)` in the mutation-tools list.
  - `docs/design/mvp-chief-of-staff-notes-design.md` — design prose.
  - `docs/design/workspace-assistant-implementation-plan.md` — plan prose.
  - `docs/FIRST-RUN.md` — user-facing walkthrough.
  - `CONTEXT.md:168` — glossary mention.
- **Test-seam contract.** `_propose_payload` is private (leading underscore)
  but the test suite (~14 cases) calls it directly. The rationale: keeping
  the validation pipeline string-based means tests exercise the exact code
  path that the propose tool delegates to, and the public `propose()` only
  needs 3 end-to-end tests for the typed-args glue (defaults, native pass-
  through, validation still fires). A header comment in
  `tests/presenter/test_server.py` documents this contract.
- **No public MCP protocol version change.** The MCP wire itself only
  enforces tool-name + arg-types-as-described; it has no schema-level
  "tool-version" header. Versioning lives in the `presenter` package's
  setuptools-scm version. The next tag is a MAJOR bump on the same package
  (per semver, a breaking change to a public tool surface warrants MAJOR;
  the project's `v0.1.0` is for identity, not distribution — see ROADMAP).
- **Verification path that produced this fix:** qwen3-coder-next now emits a
  single structured `present_propose` on the first step (was: 0 emits across
  208 read-only calls in one live session). 482 tests pass (44 in `presenter`,
  incl. 3 new native-param tests).

## References

- Builds on ADR-0006 (presentation pane + `propose` tool), ADR-0009
  (propose-confirm ingest), ADR-0011 (restrict-write mode).
- The 2026-06-05 mis-file incident (recorded in ADR-0011's Context) is
  *separate* from this fix — it motivated restrict-write mode; this ADR
  addresses the no-emit-at-all failure that survives in unrestricted mode.
- Out of scope (separate work): the pre-existing `present_present_brief` /
  `present_present_task` tool-name double-prefix bug (FastMCP server-key
  prefixing) — recorded in `pr-audit-findings.md`, not addressed here.
