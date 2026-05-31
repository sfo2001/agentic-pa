# D — OpenCode sandbox-confinement boundary (source-verified)

**Status:** Decided · **Date:** 2026-05-31 · **Scope:** Milestone 1 launcher (N6)
**Relates to:** ADR-0005 (notes-only leaf), ADR-0003 (frontend-owned git)

## Question

Does `permission.external_directory: deny` confine the agent to the **launch cwd**
or to the **enclosing git work-tree root**? This decides where the notes git
metadata may live without becoming reachable by the agent.

## Decision (from reading the OpenCode source directly)

The boundary is **the launch cwd OR the enclosing git work-tree root** — whichever
applies. Investigated against the cloned source (`~/devel/opencode`, v1.15.13):

- `packages/opencode/src/project/instance-context.ts:18-24` — `containsPath(target)`
  returns true if `target` is under `ctx.directory` (the launch **cwd**) **OR**
  under `ctx.worktree`. When `ctx.worktree === "/"` (no git) the worktree branch is
  **skipped**, so the reachable scope is exactly the cwd.
- `packages/core/src/project.ts:343` + `packages/core/src/git.ts:43-59` —
  `ctx.worktree` is the git work-tree root from `git rev-parse --show-toplevel`;
  a non-git directory yields `worktree === "/"`.
- `packages/opencode/src/tool/external-directory.ts:16-44` — the deny/ask gate
  calls `containsPath`; anything outside is refused.
- `packages/opencode/src/agent/agent.ts:107-126` — built-in defaults include
  `"*": "allow"` and an `external_directory` allow-list of the tool-output dir +
  `/tmp/opencode/*` + **skillDirs**. Globally-installed skills therefore widen the
  allow-list unless `HOME`/`XDG` are isolated.
- `packages/opencode/src/config/config.ts:601-603` — `OPENCODE_CONFIG` **is**
  honored (it is merged, it does not replace). Confinement does not depend on it.

## Evidence (probes on the installed 1.15.0 binary)

The 1.15.0 binary matches the 1.15.13 source. Prior probes during the
investigation:

- **Parent is the git root** (`git init` at the install-root, launch from
  `workspace/` under it): reading `../<file>` in the parent **succeeded** — the
  boundary had expanded to the git work-tree root. *(This is the failure mode the
  layout invariant prevents.)*
- **Sandbox is the git root** (`git init` inside `workspace/`, file in the parent):
  reading `../OUTSIDE.txt` was **refused** — the boundary was the git root =
  `workspace/`.
- **No git + clean HOME/XDG**: the merged permission ruleset was minimal (no
  skill-dir allow entries), confirming `agent.ts:107-126` and that isolating HOME
  removes the global skill bleed.

## Consequence — the locked layout invariant

1. **No `.git` at or above `workspace/`.** A `.git` in the install-root would make
   `git rev-parse --show-toplevel` resolve to the install-root and expand the
   agent's reach to `.env`/`opencode.json`/the prompt. The install-root must not be
   a git repository.
2. **The notes audit repo uses a split git-dir named `notes.git/`** (not `.git`),
   with `--work-tree = workspace/`. Because there is no `.git` entry at or above
   `workspace/`, OpenCode finds no work-tree (`worktree === "/"`) and confines the
   agent to exactly `workspace/`. `notes.git/` sits in the install-root, unreachable
   by the agent.
3. **`opencode.json` may live in the install-root** (the parent); it is found by
   OpenCode's config walk-up (a process read, not gated by `external_directory`)
   and remains unreadable by the agent.
4. **OpenCode runs with an isolated HOME/XDG** (`<install-root>/oc-home`; plus the
   Windows `%APPDATA%`/`%LOCALAPPDATA%`/`%USERPROFILE%` equivalents) so the user's
   global `~/.config/opencode` config and `~/.claude` / opencode skill directories
   do not merge into the agent. **Isolation must cover the env channel too:**
   `isolated_env` also strips every `OPENCODE_*` variable from the inherited
   environment — `OPENCODE_CONFIG` is a second config source that OpenCode
   *merges* (`config/config.ts:601-603`), so a value set in the user's shell would
   otherwise leak in and could loosen the agent's permission policy. The launcher
   re-adds only `OPENCODE_SERVER_PASSWORD` (a per-run random token that
   authenticates the localhost server; unauthenticated `/global/health` → 401).

The four denials (`bash`/`webfetch`/`websearch`/`task`) continue to hold from
`workspace/` (set both top-level and in the `workspace-assistant` agent).

Tasks 2–4 of the N6 plan consume this: `versioning` takes an explicit split
git-dir, `bootstrap` refuses install inside a git repo and names the git-dir
`notes.git`, and the launcher pre-flight asserts `no_git_ancestor(workspace)` and
runs OpenCode with `isolated_env()`.
