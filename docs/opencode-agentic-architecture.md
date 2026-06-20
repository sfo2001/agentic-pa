# OpenCode as an Agentic Platform — Architecture Guide

**Scope:** How to use OpenCode for non-coding agentic systems — where "agent" means
a persistent, tool-using LLM that operates autonomously over a long-lived data
corpus, with real side-effects, without a human in the loop for every action.

**Relationship to existing docs:** This document synthesizes the patterns from the
agentic-pa case study (ADRs 0005, 0010, 0011) and the planned web-researcher
extension (`web-research-architecture.md`) into a reusable guide.

---

## 0. The Central Principle

> **Every capability the agent must NOT have should be structurally unreachable,
> not merely instructed-not-to-use.**

Instructions can be overridden by prompt injection. File layout, process
environment, and permission JSON cannot. Every mechanism in this guide is a
concrete instantiation of that principle.

This shifts the question from "what did I tell the agent it can't do?" to "what is
it *possible* for the agent to do, even if someone crafts its input?" That question
has a better answer — one that doesn't depend on the model behaving correctly under
adversarial conditions.

---

## 1. What OpenCode Gives You

OpenCode is an AI coding assistant. Its value as a *general* agentic platform comes
from three things you can control:

| Mechanism | What you control |
|---|---|
| **`opencode.json` permission block** | Which built-in tools are allowed (`read`, `write`, `bash`, `webfetch`, `websearch`, `task`, `external_directory`, `glob`, `grep`, `list`) |
| **MCP servers** | What custom tools the agent can invoke — you write these, they run in your process, they can hold secrets and do validation |
| **Launch environment** | The process's HOME, XDG dirs, env vars, cwd, and whether a git repo is at or above the cwd |

Everything else (the model, the system prompt, the session protocol) is normal LLM
configuration. The three mechanisms above are what makes a *safely constrained*
agent possible.

---

## 2. The Sandbox Boundary

OpenCode's `external_directory: deny` permission confines the agent's file tools to
a bounded region. The boundary rule (source-verified against OpenCode
`packages/opencode/src/project/instance-context.ts`):

```
reachable scope = launch_cwd   OR   enclosing_git_worktree_root
                  (whichever is broader)
```

If the agent is launched from `/home/user/notes/workspace/` and there is no `.git`
at or above that path, the boundary is exactly `workspace/`. If there *is* a `.git`
at `/home/user/notes/`, the boundary expands to `/home/user/notes/` — including
any config, secrets, or prompt files stored there.

**Design implication: the install root must not be a git repository.**

```
<install-root>/          # NOT a git repo — no .git here or above
  opencode.json          # config — in parent, unreachable by agent
  .env / auth.json       # secrets — in parent, unreachable by agent
  notes-agent.md         # system prompt — in parent, unreachable by agent
  notes.git/             # split git-dir (NOT named .git) for notes audit trail
  workspace/             # THE sandbox — launch cwd = here
    topics/
    meetings/
    tasks.todo.txt
```

The notes audit repo uses a split git-dir (`notes.git/`) rather than `.git/` so
that `git rev-parse --show-toplevel` from inside `workspace/` finds nothing, and
the agent is confined to exactly `workspace/`. The `notes.git/` directory is in the
unreachable parent.

**Verification:** Run `git rev-parse --show-toplevel` from your intended sandbox
directory. If it returns a path that contains your secrets or config, you have a
layout problem.

---

## 3. Isolating the Process Environment

The sandbox boundary controls *file reach*. But OpenCode has two additional config
channels that bypass the sandbox:

1. **`~/.config/opencode/` (or `$XDG_CONFIG_HOME/opencode/`)** — OpenCode reads
   its global config and auth credentials from here. If the user's real home
   contains a `~/.config/opencode` with a loose permission policy, that policy
   *merges* into the sandboxed agent.

2. **The `OPENCODE_CONFIG` env var** — OpenCode merges (not replaces) the file it
   points to. A user with this set in their shell can loosen the agent's
   permissions without touching `opencode.json`.

Both channels must be closed before you can trust your permission policy.

### 3.1 Synthetic HOME / XDG (closes the file channel)

Launch OpenCode with a synthetic home directory inside your install root:

```python
env["HOME"] = str(install_root / "oc-home")
env["USERPROFILE"] = str(install_root / "oc-home")   # Windows
env["XDG_CONFIG_HOME"] = str(install_root / "oc-home" / ".config")
env["XDG_DATA_HOME"]   = str(install_root / "oc-home" / ".local" / "share")
env["XDG_STATE_HOME"]  = str(install_root / "oc-home" / ".local" / "state")
env["XDG_CACHE_HOME"]  = str(install_root / "oc-home" / ".cache")
env["APPDATA"]      = str(install_root / "oc-home" / "AppData" / "Roaming")
env["LOCALAPPDATA"] = str(install_root / "oc-home" / "AppData" / "Local")
```

OpenCode's `auth.json` is written by your bootstrap process into `oc-home/.config/
opencode/auth.json` (mode 600). The agent has no file tool access to this location
because `oc-home/` is in the install-root parent, outside the sandbox.

### 3.2 Env var stripping (closes the env channel)

Strip all `OPENCODE_*` variables from the environment before launching:

```python
for key in [k for k in env if k.startswith("OPENCODE_")]:
    del env[key]
```

Then add back only the specific vars your agent needs:

```python
env["OPENCODE_SERVER_PASSWORD"] = secrets.token_hex(32)
```

Also strip dynamic-linker injection variables (supply-chain risk):

```python
for k in ("LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
          "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH"):
    env.pop(k, None)
```

### 3.3 Per-run server password

Generate a fresh random `OPENCODE_SERVER_PASSWORD` on every launch. OpenCode's
HTTP API requires Basic auth when this is set. Other local processes cannot drive
the sandboxed agent without knowing the password, which is never written to disk.

```python
password = secrets.token_hex(32)
env["OPENCODE_SERVER_PASSWORD"] = password
# Pass the same password to your frontend — it is the only client
```

---

## 4. The Permission Block — Deny First

OpenCode's `opencode.json` permission block uses a deny-first philosophy for
non-coding agents. Start by denying everything dangerous, then selectively allow
what your agent legitimately needs:

```jsonc
// Annotated opencode.json for a sandboxed privileged agent
// (generated at runtime — never committed with machine paths)
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "my-provider": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "My LLM Provider",
      "options": {
        "baseURL": "<MODEL_ENDPOINT>"
        // apiKey is OMITTED when using auth.json — OpenCode falls through
        // to the credential in auth.json when apiKey is undefined.
        // Include "apiKey": "local" only for keyless/local servers (e.g. Ollama).
      },
      "models": { "<MODEL_ID>": { "name": "<MODEL_ID>" } }
    }
  },
  "model": "my-provider/<MODEL_ID>",

  "permission": {
    // ── Dangerous built-ins: always deny for non-coding agents ──────────
    "bash": "deny",          // arbitrary shell execution
    "webfetch": "deny",      // uncontrolled HTTP — use a hardened MCP instead
    "websearch": "deny",     // same
    "task": "deny",          // spawning subagents
    "external_directory": "deny",  // files outside the sandbox

    // ── File tools: allow inside the sandbox ────────────────────────────
    "read":  "allow",
    "write": "allow",        // set to "deny" in restrict-write mode (§5)
    "edit":  "allow",        // set to "deny" in restrict-write mode (§5)
    "glob":  "allow",
    "grep":  "allow",
    "list":  "allow",

    // ── MCP tool surfaces: wildcard-allow your tools ─────────────────────
    // OpenCode matches MCP tool names against permission keys.
    // Use a prefix + wildcard to gate an entire MCP's tool surface:
    "notes_*":   "allow",    // all tools from the "notes" MCP server
    "present_*": "allow"     // all tools from the "presenter" MCP server
  },

  "mcp": {
    "notes": {
      "type": "local",
      "command": ["<python>", "-m", "agenda.server"],
      "enabled": true,
      "environment": { "NOTES_ROOT": "<install-root>/workspace" }
    },
    "present": {
      "type": "local",
      "command": ["<python>", "-m", "presenter.server"],
      "enabled": true,
      "environment": { "NOTES_ROOT": "<install-root>/workspace" }
    }
  },

  "agent": {
    "my-agent": {
      "mode": "primary",
      "description": "My non-coding agentic assistant",
      "model": "my-provider/<MODEL_ID>",
      "prompt": "{file:<install-root>/my-agent.md}",
      "permission": { /* same as top-level permission block */ }
    }
  }
}
```

**Important:** `opencode.json` is generated at install/launch time with
machine-specific values (paths, ports, model endpoints). The *generator* is
committed to the repo; the *generated file* is gitignored. The installer writes the
config into the install-root parent (outside the sandbox) using the actual paths for
that machine.

---

## 5. Restrict-Write Mode — MCP Tools as the Sole Writer

OpenCode's permission system has a limitation: `write` and `edit` permissions have
no path-glob support (unlike `bash`, which supports patterns). You cannot express
"deny write to `tasks.todo.txt` but allow it to `topics/`". Write is all-or-nothing.

**The pattern for validation-enforced writes:**

1. Set `"write": "deny"` and `"edit": "deny"` in the permission block.
2. Expose write operations as **MCP tools** — the MCP server process writes via
   plain Python/JS I/O, which is not gated by the agent's permission JSON.
3. The MCP tool validates inputs (schema, field caps, referential integrity,
   date constraints) before writing. A weak or injected model cannot bypass this.
4. Stage mutations that need human review (add `_proposal.json`) rather than
   writing directly. Your frontend applies them after the user confirms.

This converts "the agent is told not to write freely" (instruction, bypassable) into
"the agent has no write capability; the only write path is through validated MCP
tools" (structure, not bypassable).

**When to use restrict-write mode:** Any deployment running a smaller/local model,
or any domain where wrong writes are hard to undo. The notes assistant uses it for
Ground Truth mutations (meeting records, actions, topics) while allowing direct
write for throwaway/regenerable digests.

---

## 6. MCP Servers as Trust Boundaries

MCP servers are the controlled entry/exit points for privileged operations. Their
key properties:

- They run in **your process** (not the agent's sandbox) — you control what they
  can do, what secrets they hold, and what validation they perform.
- They are invoked by **tool name** — the agent calls `notes_today()` and gets back
  what your code returns; it never sees the implementation.
- They can hold **credentials** the agent cannot reach — your MCP server can have
  the database token or API key; the agent's file tools cannot reach the process
  memory of an MCP server.

**Design pattern for privileged MCPs (notes, presentation, write operations):**

- Run in the same process as your backend/frontend (or as a child process it spawns)
- Hold all credentials (Confluence PAT, database URL, etc.)
- Validate every input before acting (schema, referential integrity, size caps)
- Expose **typed, minimal tool surfaces** — `present_propose(diary, actions, topics,
  meetings)` rather than `write_file(path, content)`
- Use a shared prefix (`notes_*`, `present_*`) for permission wildcarding

**Design pattern for read-only deterministic MCPs (agenda engine, search):**

- These expose computed views over a corpus, never the corpus itself
- They write nothing — `read: "allow"` in the agent's permissions covers the corpus
  reads directly; the MCP only serves calculated results
- Separating deterministic logic into an MCP keeps it auditable and testable

---

## 7. Trust Domains — Multiple OpenCode Instances

Some capabilities are incompatible with a privileged agent's trust properties. The
canonical example: **web access**. Giving an agent with Confluence credentials access
to arbitrary web content creates a prompt-injection attack surface where a malicious
page could instruct the agent to exfiltrate via Confluence writes.

The solution is a **second, capability-isolated OpenCode instance** for the
untrusted-facing capability, connected via a validated broker.

### 7.1 The Researcher Instance

A second `opencode serve` deployment with a maximally restricted tool surface:

```jsonc
// opencode.json for an untrusted-facing web researcher
// No privileged MCPs. No write. No file tools beyond what the web MCP needs.
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "researcher-llm": {
      // May use a different (cheaper, EU-cloud) model — this instance
      // never sees internal data, so data-class constraints don't apply.
      "npm": "@ai-sdk/openai-compatible",
      "name": "Researcher LLM",
      "options": { "baseURL": "<RESEARCHER_MODEL_ENDPOINT>" }
    }
  },
  "model": "researcher-llm/<RESEARCHER_MODEL_ID>",

  "permission": {
    // ── Everything dangerous: denied ────────────────────────────────────
    "bash": "deny",
    "task": "deny",
    "external_directory": "deny",
    "read":  "deny",          // no file access — results come via MCP
    "write": "deny",
    "edit":  "deny",
    "glob":  "deny",
    "grep":  "deny",
    "list":  "deny",
    // webfetch / websearch are also denied — all egress goes through
    // the hardened MCP (which validates every fetch, not OpenCode's built-in)
    "webfetch": "deny",
    "websearch": "deny",

    // ── Only the hardened web MCP's tools are allowed ────────────────────
    "web_search": "allow",
    "web_fetch":  "allow"
  },

  "mcp": {
    "web": {
      "type": "local",
      "command": ["<python>", "-m", "web_researcher.server"],
      "enabled": true,
      "environment": {
        // Minimal env — NO Confluence PAT, NO primary model keys
      }
    }
  }
}
```

The researcher instance holds no credentials, can write nothing, and has no path
back to internal systems.

### 7.2 The Hardened Fetch MCP (SSRF Protection)

OpenCode's built-in `webfetch`/`websearch` are denied. All egress goes through
your own MCP server, which enforces:

- **Scheme restriction** — only `http:` and `https:` accepted; reject `file:`,
  `data:`, `gopher:`, `ftp:`
- **Resolved-IP validation** — resolve the hostname, then check the *resolved IP*
  (not the hostname string) against deny ranges: `127/8`, `10/8`, `172.16/12`,
  `192.168/16`, `169.254/16` (cloud metadata), `::1`, `fc00::/7`, `fe80::/10`
- **Manual redirect following** — re-validate every `Location` hop; an allowed host
  can 302 to localhost/LAN
- **Connect to the validated IP** with explicit `Host` header (mitigates DNS
  rebinding)
- **Aggressive content sanitization** — readability extraction; strip
  `<script>/<style>/<template>`, comments, hidden elements (`display:none`,
  `aria-hidden`), zero-width chars, bidi overrides, Unicode Tag block
  (`U+E0000–U+E007F`); cap response size and redirect count

### 7.3 The Research Broker and Airlock

The researcher is connected to the privileged primary via a **broker** that lives in
the privileged agent's trust domain:

```
Primary (privileged) ──► broker.research(query) ──► Researcher instance
                         │                            (web-only, no secrets)
                         │◄── raw candidate envelope ─┘
                         │
                         airlock: deterministic validation + neutralization
                         │
                         sanitized findings ──► primary as tool result
```

**Airlock properties:**

- Runs in the **consumer's** (primary's) trust domain — a compromised producer
  cannot certify its own output; validate where you control
- **Deterministic** — no model in the airlock, only schema validation and
  sanitization (a model could be steered by the same injection you're trying to
  neutralize)
- Accepts only well-formed JSON matching the pinned schema; drops everything else
- Runs a sanitization pass on all string fields (strip invisible Unicode, bidi
  overrides)
- **URLs in findings are never auto-actioned** — if the primary wants to follow a
  discovered link, that's a fresh `research()` call, re-validated from the start

**Residual risk — query-as-exfil:** A primary that has been injected via its own
data corpus could embed internal text in the outbound `query`. Project separation
does not close this. Proportionate mitigation: cap query length; optionally flag
high-entropy or credential-shaped queries in the broker before forwarding.

---

## 8. Multi-Project Topology

Trust domains map directly to repositories. The split criterion is
**"does this code need to be in the same dependency closure as privileged
credentials?"**, not **"is this an MCP server?"**

| Project | Trust domain | Contents |
|---|---|---|
| `agentic-pa` | Privileged — holds credentials | Agent backend + frontend, launcher, `opencode.json` generator, privileged MCP servers (notes, presenter), research broker + airlock |
| `web-researcher` | Untrusted-facing — holds no credentials | Researcher `opencode.json` config, hardened SSRF-validating fetch/search MCP server, localhost-bound request/response endpoint |
| `shared-contract` | Neutral | Versioned envelope schema. **Owned by the consumer** (`agentic-pa`) — the party that must trust the data sets the schema, not the producer |

**The key security property:** A transitive vulnerability in the HTML parser inside
the fetch MCP (which processes hostile web content) does not live in the same
dependency closure as the Confluence PAT or the notes corpus. A compromise of the
researcher cannot reach privileged credentials — not because of a policy rule, but
because the processes run separately and there is no code path between them except
the validated airlock.

See `docs/adr/0013-multi-repo-mcp-topology.md` for the migration plan and
rationale.

---

## 9. Configuration Lifecycle

### 9.1 What is committed to the repo

The repo contains:

- **MCP server source code** — the Python/JS packages implementing your tools
- **The `opencode.json` generator** — a script that takes env vars (model endpoint,
  install path, etc.) and produces the machine-specific config
- **The system prompt** — your `agent.md` file (the prompt shipped as package data)
- **This architecture doc** and ADRs

The repo does **not** contain:

- Generated `opencode.json` (machine-specific paths) — gitignored
- `.env` files with secrets — gitignored
- Auth credentials (`auth.json`) — lives in `oc-home`, never committed

### 9.2 Install-time generation

The installer:

1. Generates `<install-root>/opencode.json` from env vars + sane defaults
2. Generates `<install-root>/.env` with any secrets (if applicable)
3. Writes `<install-root>/oc-home/.config/opencode/auth.json` (mode 600) with
   model credentials
4. Inits the split git-dir `<install-root>/notes.git/`
5. Asserts no `.git` at or above `<install-root>/workspace/`
6. Launches `opencode serve --cwd <install-root>/workspace/` with the isolated env

---

## 10. Env Var Preflight

Every entry point (launcher, installer, frontend) should validate its expected env
vars before proceeding. Prefer a single, stdlib-only preflight helper that:

- Checks required vars and exits with a clear message (not a Python traceback) if
  missing
- Validates types at the boundary (port numbers are integers, URLs are `http`/`https`)
- Provides per-shell "how to set" remediation hints on failure
- Is silent on the happy path (no output when everything is configured correctly)
- Masks secrets in error output (`secret=True` flag on the spec)

This converts "ERROR: {workspace} not found — run bootstrap first" (the symptom, not
the cause) into "INSTALL_ROOT is required but not set. On bash: `export INSTALL_ROOT=...`"

---

## 11. Starting a New Agentic Project — Checklist

Use this checklist when building a new non-coding OpenCode agent:

**Sandbox design**
- [ ] Define the sandbox directory (what the agent should read/write)
- [ ] Ensure no `.git` exists at or above the sandbox directory
- [ ] If you need a git audit trail, use a split git-dir (not `.git`)
- [ ] Place config, secrets, and system prompt in the parent of the sandbox

**Process isolation**
- [ ] Synthetic HOME/XDG pointing at `<install-root>/oc-home`
- [ ] Strip all `OPENCODE_*` env vars before launch
- [ ] Strip DLL injection vars (`LD_PRELOAD`, `LD_LIBRARY_PATH`, etc.)
- [ ] Generate fresh `OPENCODE_SERVER_PASSWORD` per run
- [ ] Credential in `oc-home/.config/opencode/auth.json` (mode 600)

**Permissions**
- [ ] `bash: deny` (add only if your agent genuinely needs shell)
- [ ] `webfetch: deny`, `websearch: deny` (add a hardened MCP if needed)
- [ ] `task: deny` (subagents open new attack surfaces)
- [ ] `external_directory: deny`
- [ ] Decide on `write`/`edit`: allow for free-hand agents, deny for restrict-write mode
- [ ] Use wildcard prefixes (`yourapp_*`) to gate each MCP's tool surface

**MCP design**
- [ ] One MCP per trust domain (not one per feature)
- [ ] Read-only MCPs: expose computed views, validate nothing they don't write
- [ ] Write MCPs: validate every input before acting; stage+confirm for risky mutations
- [ ] No credentials in MCPs that process untrusted input

**Config generation**
- [ ] Generator script reads env vars, writes `opencode.json` to install-root parent
- [ ] Generated config is gitignored
- [ ] `apiKey` omitted in config when using `auth.json` (let OpenCode fall through)
- [ ] `environment` block in each MCP spec carries only the vars that MCP needs

**Multi-instance (if needed)**
- [ ] Separate `opencode.json` per trust domain
- [ ] Researcher instance: minimal env, no privileged credentials
- [ ] SSRF-validating fetch MCP with resolved-IP checks
- [ ] Broker + airlock in privileged domain; deterministic validation, no model
- [ ] Structured envelope schema owned by consumer
- [ ] URLs in findings never auto-actioned

---

## 12. Further Reading

Within this project:

- `docs/adr/0005-sandbox-is-a-notes-only-leaf.md` — the layout invariant and its source-verification
- `docs/decisions/D-opencode-sandbox.md` — source-level proof of the sandbox boundary
- `docs/adr/0010-env-var-preflight-layer.md` — the env var preflight pattern
- `docs/adr/0011-restrict-write-mode-frontend-sole-writer.md` — restrict-write mode rationale
- `docs/adr/0012-present-propose-native-typed-args.md` — MCP tool design: native typed args
- `docs/adr/0014-multi-repo-mcp-topology.md` — multi-repo topology for trust-domain separation
- `docs/web-research-architecture.md` — full web-researcher design (trust model, SSRF, airlock)
