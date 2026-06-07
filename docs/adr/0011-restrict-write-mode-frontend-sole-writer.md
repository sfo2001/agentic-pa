# A setup-chosen restrict-write mode makes the frontend the sole writer of the notes, with all agent mutation flowing through validated MCP tools

For deployments running a smaller/local model (the ROADMAP "Now" target is a 36B-A3B
MoE), the agent's direct `write`/`edit` tools are denied and **every** notes
mutation flows through a trusted, validating MCP tool — `present_propose` (add),
`present_task` (mutate/complete an existing action), `present_brief` (write a
digest). Adding *or* mutating Ground Truth is confirm-gated; only throwaway digests
write directly. The mode is a launch-time flag (`RESTRICT_WRITE`) whose default is
chosen by the setup wizard.

## Context

A weak model mis-filed a real capture (2026-06-05): it wrote to the wrong path
(`tasks/todo.txt` instead of `tasks.todo.txt`), set a tickler *after* the deadline,
and tagged a topic it falsely claimed existed. Root cause: in a normal chat the
agent has `write`/`edit` allowed and free-hands file mutations — the propose-confirm
machinery only guarded the sweep path. The `present_propose` MCP tool
(propose-mcp-tool branch) closed the *append* path with validation, but the agent
could still write directly, briefs still needed direct write, and there was no path
to *mutate* an existing action without `edit`.

OpenCode's permission model is coarse: `edit`/`write` are `ask|allow|deny` with **no
path globs** (only `bash` supports patterns), and the frontend does not answer
permission prompts (so `ask` would hang a headless turn). Therefore "deny write only
on ingest files" is not expressible — write is all-or-nothing. The only way to deny
it safely is to first remove every *legitimate* need for agent write.

A trusted MCP tool can write even when the agent's `write` is denied: the presenter
process writes via plain Python I/O (e.g. `present_propose` already stages
`inbox/_proposal.json`), which is unaffected by the agent's `opencode.json`
permissions. That is the mechanism this ADR builds on.

## Decision

1. **The agent never writes Ground Truth directly in restrict mode.** `write` and
   `edit` are set to `deny`; the frontend (and its MCP tools) become the sole
   writer. Reads (`notes_*`, native read/glob/grep) stay allowed.

2. **Three mutation tools, always present** (so the prompt is uniform across modes):
   - `present_propose(json)` — *add* actions/topics/meetings/diary (exists).
   - `present_task(id, op)` — *mutate* an existing action: `complete`, `reprioritize`,
     `retickle`, targeted by a stable `id:`.
   - `present_brief(kind, content)` — write a daily/weekly digest.

3. **Stable `id:` tags.** The applier stamps `id:<6-char>` on every action; the
   agenda parser recognises `id:` as a tag; an idempotent backfill stamps existing
   actions. `id:` is how `present_task` targets a line unambiguously (todo.txt has no
   native identity).

4. **Confirm rule: add *and* mutate Ground Truth are confirm-gated** (unified
   staging — one confirm clears a turn's whole change-set); only throwaway,
   regenerable digests (`present_brief`) write directly. This puts the gate where a
   weak model does real damage (mutating the wrong existing action is worse than
   appending).

5. **Launch-time toggle.** `RESTRICT_WRITE` is an `EnvSpec` in the ADR-0010
   preflight. The setup wizard writes the default; the launcher regenerates
   `opencode.json`'s `write`/`edit` permission block from it at boot. Flipping mode =
   change the env + restart, not a full re-setup.

## Considered options (ruled out)

- **Path-scoped write denial** (deny write to `tasks.todo.txt`/`topics/` only) —
  not expressible in OpenCode's permission schema.
- **`edit: "ask"`** — hangs the headless agent (the frontend doesn't reply to
  permission prompts).
- **`edit: "deny"` without tool-ifying briefs/mutation** — breaks daily briefs and
  weekly-review edits.
- **Prompt-only enforcement** (keep `write: allow`, just instruct) — the very
  failure that triggered this; a weak model ignores the instruction.
- **`present_task` direct-apply (no confirm)** — inverts safety: it would gate the
  safe op (append) and leave the risky op (mutate/complete) ungated.
- **Frontend/UI owns all task mutation** (no agent tool) — purest, but the agent
  could not apply weekly-review changes; deferred as a possible future UI affordance.

## Consequences

- **Structural guardrail, not a judgment one.** Restrict mode makes wrong paths,
  dangling tags, missing diary, malformed/after-deadline dates, and unseen wrong-id
  mutation *impossible*. It does **not** stop the model generating confidently-wrong
  content or picking a plausible-but-wrong `id:` — the **confirm gate is the only
  backstop for those, and only if the user actually reads it** (confirm-fatigue
  degrades its value).
- **Frontier models lose free-hand flexibility** in restrict mode — intentional;
  run with `RESTRICT_WRITE=0` to keep `write` as an escape hatch.
- **New launcher responsibility:** regenerate the permission block at boot from
  `RESTRICT_WRITE` (previously `opencode.json` was only setup-generated).
- **`id:` is now part of the action line format** — a format change with an
  idempotent backfill; the read-only agenda engine learns to parse (not write) it.
- **Wiki/document ingest is unaffected** — already frontend-driven (`upload.py`,
  `wiki.run_housekeeping`).
- Builds toward "the frontend is the sole writer" already recorded for ingest in
  ADR-0009; this extends it to briefs and existing-action mutation.

## References

- Builds on ADR-0005 (sandbox), ADR-0009 (propose-confirm ingest), ADR-0010
  (env-var preflight). Tool surface: `presenter/server.py`. Permission constraint
  verified against the OpenCode SDK `Config.permission` type.
