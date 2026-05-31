# The agent sandbox is a notes-only leaf with no git ancestor; config, secrets, git, and prompt live in the unreachable parent

The OpenCode agent's sandbox (its launch directory, confined by
`permission.external_directory: deny`) is a **leaf directory containing only the
notes** (`workspace/`). Everything the agent must not touch — the generated
`opencode.json`, the `.env` secrets, the `notes-agent.md` system prompt, and the
notes git metadata — lives in the **install-root that contains the sandbox**,
outside the agent's reach:

```
<install-root>/        # NOT a git repo; outside the sandbox
  opencode.json  .env  notes-agent.md  notes.git/
  workspace/           # THE sandbox (launch cwd = NOTES_ROOT)
```

## Context

`external_directory: deny` only blocks paths *outside* the agent's reachable
scope; the agent's `read`/`write`/`edit` tools are *allowed inside* it. If config,
secrets, prompt, or git metadata lived inside the sandbox, the agent could (via
prompt injection or error) read credentials, rewrite its own permission policy or
system prompt, or corrupt the version-control audit trail — none of which the
"no `bash`" guarantee prevents. Putting those artifacts in the parent makes the
protection **structural**, not policy.

**The confinement boundary is source-verified** (OpenCode 1.15.13;
behaviour confirmed on the installed 1.15.0):

- `packages/opencode/src/project/instance-context.ts:18-24` — `containsPath`
  returns true if the target is under `ctx.directory` (the launch **cwd**) **or**
  `ctx.worktree`; when `ctx.worktree === "/"` (no git) the worktree check is
  **skipped**, so the boundary is exactly the cwd.
- `packages/core/src/project.ts:343` + `git.ts:43-59` — `ctx.worktree` is the
  **git work-tree root** from `git rev-parse --show-toplevel`; a non-git directory
  yields `worktree === "/"`.
- `packages/opencode/src/tool/external-directory.ts:16-44` — the deny check calls
  `containsPath`; outside → asks/denies.

The earlier "open dependency" (whether confinement anchors to launch-cwd or the
nearest git root) is resolved: **both**. The reachable scope is the launch cwd
*or* the enclosing git work-tree root. This dictates the layout decision below.

## Consequences

- **No `.git` at or above `workspace/`.** If the install-root (or any ancestor)
  were a git repo, OpenCode's `git rev-parse --show-toplevel` from `workspace/`
  would set the work-tree root to that ancestor and **expand the boundary to the
  whole install-root**, exposing `.env`, `opencode.json`, and the prompt. The
  install-root must therefore not be a git repository.
- **The notes audit repo uses a split git-dir named `notes.git/`** (not `.git`),
  with `--work-tree = workspace/`. Because there is no `.git` entry at or above
  `workspace/`, OpenCode's git detection finds no work-tree, `worktree === "/"`,
  and the agent is confined to exactly `workspace/`. The `notes.git/` directory
  sits in the install-root and is unreachable by the agent (relates to ADR-0003).
- **`opencode.json` may live in the parent** and is still found by OpenCode's
  config walk-up from the cwd (a process-level read, not gated by
  `external_directory`); it stays unreadable by the agent because it is outside
  `workspace/`. Confinement does **not** depend on the config file's location.
- **The launcher runs OpenCode with an isolated HOME/XDG** (and the Windows
  `%APPDATA%`/`%LOCALAPPDATA%`/`%USERPROFILE%` equivalents) so the user's global
  `~/.config/opencode` config and `~/.claude` / opencode skill directories do not
  merge into the agent — skillDirs otherwise feed the `external_directory`
  allow-list (`packages/opencode/src/agent/agent.ts:107-126`).
- The launcher/bootstrap creates the install-root, generates config/prompt into
  the parent, inits the split `notes.git/` repo, asserts no `.git` ancestor of
  `workspace/`, and launches `opencode serve` with cwd = `workspace/`.
