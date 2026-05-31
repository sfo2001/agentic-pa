# The frontend versions the notes workspace/ as its own git repo

The notes tree (`workspace/`) is a dedicated git repository, **separate from the
application code repo** (meeting notes are user data, not source), and the Python
frontend commits
it after each agent operation (ingest, weekly-review edits, etc.). "Undo" is a
git revert, and the history is a full, timestamped audit trail of how the Ground
Truth evolved — valuable in a governance context.

## Context

The agent runs sandboxed with `bash` denied (security model), so it **cannot run
git itself**. Versioning therefore has to be owned outside the agent.

`bash`-denial alone is insufficient, however: the agent's native `read`/`write`/
`edit` tools are allowed *inside* the sandbox. So the notes git metadata must also
live **outside the agent-writable tree** — implemented as a split `--git-dir`/
`--work-tree` where the work-tree is the sandbox and the git-dir is `notes.git/`
in the unreachable install-root. It is named `notes.git`, **not** `.git`, so
OpenCode's git detection does not treat the install-root as a work-tree and the
agent's sandbox stays confined to `workspace/` (see ADR-0005). Otherwise the agent
could corrupt the audit trail by writing to the git metadata directly.

## Consequences

Versioning, undo, and audit are a **frontend responsibility**, not an agent
capability. The frontend must initialise the `workspace/` repo on first run and
commit with a meaningful message per operation (mirroring the per-ingest
changelog shown to the user). The current implementation uses the user's prompt
text as the commit subject; mapping the agent's structured changelog to commit
messages is deferred.
