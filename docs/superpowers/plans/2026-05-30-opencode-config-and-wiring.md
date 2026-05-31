# OpenCode Config + Notes Prompt + Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built Agenda service into a runnable, sandboxed OpenCode agent driven by the local `<model-id>` model on `<ollama-host>`, and prove end-to-end that the agent can call the read-only `agenda_*` tools and capture notes — closing the "never actually run under OpenCode" gap.

**Architecture:** A static `opencode.json` defines (a) an OpenAI-compatible provider pointing at ollama's `/v1` endpoint on `<ollama-host>`, (b) a single restricted primary agent whose system prompt is the notes-assistant prompt, (c) the locked-down `permission` set, and (d) one MCP server entry that spawns the Agenda service over stdio with `NOTES_ROOT` injected. The Agenda service is run from a repo-local venv. Verification is split into a **deterministic wiring check** (OpenCode spawns the server and registers exactly the 3 read tools) and a **model-behaviour check** (qwen3.6 actually calls `agenda_today` and writes a note).

**Tech Stack:** OpenCode 1.15.0 · Bun 1.3.11 · ollama on `<ollama-host>:11434` (OpenAI-compatible `/v1`, model `<model-id>`) · Python 3.12 venv running the `agenda-service` package (already on `main`).

**Scope note:** Plan **2 of 4** for Milestone 1 (spec `mvp-chief-of-staff-notes-design.md`; plan WP **N1**). Plan 1 (Agenda service) is merged on `main`. Follow-ups: (3) frontend N3–N5, (4) launcher + integration N6–N7. This plan does NOT build the web frontend — it drives OpenCode via its CLI/HTTP API to verify wiring.

**Verified environment (pre-flight, 2026-05-30):**
- `opencode` 1.15.0; `bun` 1.3.11.
- `curl http://<ollama-host>:11434/v1/models` lists `<model-id>` (and `<model-id>`). Ollama's OpenAI-compatible endpoint needs no real key (a placeholder is accepted).
- `python3.12` present. Repo root: `<repo>`. The `agenda/` package and `tests/agenda/` are committed on `main`. `.venv/` and `__pycache__/` are gitignored.
- **`OPENCODE_CONFIG` is not honoured in OpenCode 1.15.0.** Config is discovered by directory-walk up from the current working directory; `cd` into `notes-mvp/` (for serve) or `notes-mvp/sample-notes/` (for `opencode run`) so the walk finds `notes-mvp/opencode.json`.

**No machine-specific data is committed.** The real `opencode.json` (absolute paths, model endpoint host) and `.env` (endpoint URL, model id) are **gitignored**; only a generic generator and a placeholder example are tracked.

**Files created by this plan:**
- `notes-mvp/gen_opencode_config.py` — **committed**, generic. Derives repo paths from its own location; reads `MODEL_ENDPOINT` / `MODEL_ID` (and optional `NOTES_ROOT`, `AGENDA_SERVER`) from the environment; writes the local `opencode.json`. Contains no hostnames or absolute paths.
- `notes-mvp/.env.example` — **committed**, placeholders only.
- `notes-mvp/opencode.json` — **gitignored** (generated locally; may contain real paths/URL).
- `notes-mvp/.env` — **gitignored** (real local values: your endpoint URL + model id).
- `notes-mvp/notes-agent.md` — **committed** system prompt (N1 TN1.2); generic, no local info.
- `notes-mvp/sample-notes/` — **committed** synthetic Ground Truth fixture.
- `notes-mvp/README.md` — **committed** launch + test commands.
- `.venv/` — repo-local runtime venv for the Agenda MCP server (gitignored).

---

### Task 0: Repo-local runtime venv for the Agenda MCP server

OpenCode must be able to spawn the Agenda server as a real executable. Plan 1's worktree venv was removed, so create a stable one at the repo root.

**Files:** none committed (venv is gitignored).

- [ ] **Step 1: Create the venv and install the agenda package**

Run from the repo root (`<repo>`):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ./agenda
```

Expected: installs `agenda-service` plus `mcp` and `pyyaml` without error.

- [ ] **Step 2: Verify the `agenda-server` entry point exists**

Run:

```bash
test -x .venv/bin/agenda-server && echo "agenda-server present"
```

Expected: prints `agenda-server present`.

- [ ] **Step 3: Verify the server starts and speaks MCP over stdio**

Send an MCP `initialize` + `tools/list` handshake and confirm exactly the three read tools, with no write tool. Run:

```bash
NOTES_ROOT=tests/agenda/fixtures/notes .venv/bin/python - <<'PY'
import json, subprocess, os
p = subprocess.Popen([".venv/bin/agenda-server"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     text=True, env={**os.environ})
def send(obj):
    p.stdin.write(json.dumps(obj) + "\n"); p.stdin.flush()
def recv():
    return json.loads(p.stdout.readline())
send({"jsonrpc":"2.0","id":1,"method":"initialize",
      "params":{"protocolVersion":"2024-11-05","capabilities":{},
                "clientInfo":{"name":"probe","version":"0"}}})
recv()
send({"jsonrpc":"2.0","method":"notifications/initialized"})
send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
tools = sorted(t["name"] for t in recv()["result"]["tools"])
p.terminate()
print("TOOLS:", tools)
assert tools == ["agenda_review","agenda_today","agenda_topic"], tools
assert not any(w in t for t in tools for w in ("create","write","update","delete")), tools
print("OK: exactly 3 read-only tools")
PY
```

Expected: `TOOLS: ['agenda_review', 'agenda_today', 'agenda_topic']` then `OK: exactly 3 read-only tools`. (This proves the server is launchable and MCP-correct before OpenCode is involved.)

- [ ] **Step 4: Confirm the venv is ignored, not committed**

Run:

```bash
git check-ignore .venv && echo ".venv ignored"
```

Expected: prints `.venv` then `.venv ignored`. (No commit in this task — it produces only the gitignored venv.)

---

### Task 1: The sample Ground Truth fixture

A small notes tree so the live agent has real content to query. Dates are chosen so the deterministic checks don't depend on the current date (uses an `(A)` do-now item, which is date-independent).

**Files:**
- Create: `notes-mvp/sample-notes/tasks.todo.txt`
- Create: `notes-mvp/sample-notes/topics/project-atlas.md`
- Create: `notes-mvp/sample-notes/meetings/2026-05-29/atlas-sync.md`

- [ ] **Step 1: Create the task list**

Create `notes-mvp/sample-notes/tasks.todo.txt`:

```
(A) Sign off Atlas security design +project-atlas @decision due:2026-06-02 upd:2026-05-29
(B) Draft Q3 governance proposal +governance t:2026-06-09 upd:2026-05-29
(C) Reply to vendor on licensing +procurement due:2026-06-01 upd:2026-05-29
```

- [ ] **Step 2: Create the topic file**

Create `notes-mvp/sample-notes/topics/project-atlas.md`:

```markdown
---
slug: project-atlas
title: Atlas Programme
tags: [technical, delivery]
status: active
---
## Overview
The Atlas programme.

## Current state
Security design under review.
```

- [ ] **Step 3: Create the meeting record**

Create `notes-mvp/sample-notes/meetings/2026-05-29/atlas-sync.md`:

```markdown
---
date: 2026-05-29
title: Atlas Sync
topics: [project-atlas]
---
## Summary
Reviewed the security design; sign-off pending.

## Actions
- Sign off Atlas security design (provenance — authority is tasks.todo.txt)
```

- [ ] **Step 4: Sanity-check the engine reads the sample**

Run:

```bash
.venv/bin/python -c "from agenda import engine; from datetime import date; import json; print(json.dumps(engine.today('notes-mvp/sample-notes', date(2026,5,30)), indent=2))" | head -20
```

Expected: JSON whose `do_now` contains `"Sign off Atlas security design"`.

- [ ] **Step 5: Commit**

```bash
git add notes-mvp/sample-notes/
git commit -m "feat(notes-mvp): sample Ground Truth fixture for wiring test"
```

---

### Task 2: The notes-assistant system prompt

The N1 system prompt encoding the data model, the loop verbs, and the conventions. It is referenced by the agent's `prompt` field (Task 3) by absolute path.

**Files:**
- Create: `notes-mvp/notes-agent.md`

- [ ] **Step 1: Write the prompt**

Create `notes-mvp/notes-agent.md`:

```markdown
You are a Chief-of-Staff notes assistant. You run entirely locally and are
sandboxed: you have no shell, no internet, and no subagents. You ground every
answer in the user's local notes — never invent facts.

# Your tools
- **Native file tools** (`read`, `write`, `edit`, `glob`, `grep`, `list`) operate
  ONLY inside the working directory (the notes tree). This is your Workspace.
- **Agenda tools** (read-only, always safe to call):
  - `agenda_today` — do-now / schedule / resurfacing / overdue / stale-important.
  - `agenda_review` — weekly review: per-topic staleness, ticklers this week.
  - `agenda_topic(slug)` — one topic's open actions, ticklers, recent meetings.
  Treat the Agenda tools as the authority for anything date-based; do not compute
  due/tickler/stale yourself.

# The notes (the Ground Truth) — layout
- `tasks.todo.txt` — the single source of truth for actions (todo.txt syntax).
- `topics/<slug>.md` — one living file per topic (the slug is immutable id; the
  `title` is the human label).
- `meetings/YYYY-MM-DD/<slug>.md` — dated meeting records (frozen provenance).
- `briefs/`, `archive/`, `documents/` — daily/weekly briefs, processed items,
  local copies of documents.

# tasks.todo.txt format
`[x ](A)-(D) <text> +topic @context due:YYYY-MM-DD t:YYYY-MM-DD upd:YYYY-MM-DD`
- Priority letter = Eisenhower quadrant: (A) urgent+important, (B) important not
  urgent, (C) urgent not important, (D) neither.
- `due:` deadline · `t:` tickler (resurface date) · `upd:` last-touched.
- **Always set `upd:` to today when you create or edit an action.**
- When you file a `(B)` action with no `t:`, set `t:` to one week out.

# Action authority
`tasks.todo.txt` is the ONLY authority for an action's existence and status. A
meeting's `## Actions` is frozen provenance (never edit it after filing). A
topic's `## Open actions` is a stamped snapshot you regenerate when you edit that
topic file. Never re-sync the copies back into authority.

# What you do (the loop)
- **Ingest**: when asked to process notes, read each raw note, segment it into
  zero-or-more meetings plus loose items, write meeting records, update/create
  topic files (by slug), and add actions to `tasks.todo.txt`. Auto-file the clear
  cases; ask only when a meeting's topic is genuinely ambiguous. Afterwards print
  a compact changelog (meetings filed, actions added, new topics created).
- **Daily brief**: call `agenda_today`, then write `briefs/<DATE>-daily.md` and
  present do-now / schedule / resurfacing.
- **Weekly review**: call `agenda_review`, propose re-prioritisation, resurface
  stale topics; apply changes only with the user's agreement.
- **Query**: answer from the topics/meetings/tasks, citing the topic or meeting.

# Boundaries
You have no access to Confluence, Jira, email, or any external system — only the
local notes. If asked for something outside the notes, say so plainly. Default
language: English.
```

- [ ] **Step 2: Verify the prompt names the real tools and conventions**

Run:

```bash
grep -q "agenda_today" notes-mvp/notes-agent.md && grep -q "upd:" notes-mvp/notes-agent.md && grep -q "tasks.todo.txt is the ONLY authority" notes-mvp/notes-agent.md && echo "prompt OK"
```

Expected: prints `prompt OK`.

- [ ] **Step 3: Commit**

```bash
git add notes-mvp/notes-agent.md
git commit -m "feat(notes-mvp): N1 notes-assistant system prompt"
```

---

### Task 3: The OpenCode config generator (no committed local info)

The real `opencode.json` is generated locally and gitignored. Only a generic
generator and a placeholder `.env.example` are committed.

**Files:**
- Modify: `.gitignore`
- Create: `notes-mvp/gen_opencode_config.py` (committed)
- Create: `notes-mvp/.env.example` (committed)
- Generated (gitignored): `notes-mvp/opencode.json`, `notes-mvp/.env`

- [ ] **Step 1: Ignore the local config and env**

Append to `<repo>/.gitignore`:

```
notes-mvp/opencode.json
notes-mvp/.env
```

- [ ] **Step 2: Write the committed example env**

Create `notes-mvp/.env.example` (placeholders only — never put real values here):

```bash
# Copy to notes-mvp/.env (gitignored) and fill in. Do NOT commit notes-mvp/.env.
# OpenAI-compatible model endpoint (e.g. ollama: http://YOUR_HOST:11434/v1)
MODEL_ENDPOINT=http://OLLAMA_HOST:11434/v1
# Model id exactly as the endpoint exposes it
MODEL_ID=your-model-id
# Optional: notes directory the agenda server reads (default: notes-mvp/sample-notes)
#NOTES_ROOT=/path/to/your/notes
# Optional: path to the agenda-server entry point (default: <repo>/.venv/bin/agenda-server)
#AGENDA_SERVER=/path/to/.venv/bin/agenda-server
```

- [ ] **Step 3: Write the generator**

Create `notes-mvp/gen_opencode_config.py`:

```python
#!/usr/bin/env python3
"""Generate notes-mvp/opencode.json from local environment values.

Committed and generic: contains no hostnames or absolute paths. Repo paths are
derived from this file's location; the model endpoint and id come from the
environment (e.g. notes-mvp/.env). The GENERATED opencode.json is gitignored and
may contain machine-specific values — those never enter git.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent            # notes-mvp/
REPO = HERE.parent                                 # repo root


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"Missing required env var: {name} (see notes-mvp/.env.example)")
    return val


def main() -> None:
    model_endpoint = _required("MODEL_ENDPOINT")
    model_id = _required("MODEL_ID")
    notes_root = os.environ.get("NOTES_ROOT", str(HERE / "sample-notes"))
    agenda_server = os.environ.get("AGENDA_SERVER", str(REPO / ".venv" / "bin" / "agenda-server"))

    config = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "workspace-llm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Workspace LLM",
                "options": {"baseURL": model_endpoint, "apiKey": "local"},
                "models": {model_id: {"name": model_id}},
            }
        },
        "model": f"workspace-llm/{model_id}",
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
            "agenda_*": "allow",
        },
        "agent": {
            "workspace-assistant": {
                "mode": "primary",
                "description": "Chief-of-Staff notes assistant (local-only)",
                "model": f"workspace-llm/{model_id}",
                "prompt": "{file:" + str(HERE / "notes-agent.md") + "}",
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
                    "agenda_*": "allow",
                },
            }
        },
        "mcp": {
            "agenda": {
                "type": "local",
                "command": [agenda_server],
                "enabled": True,
                "environment": {"NOTES_ROOT": notes_root},
            }
        },
    }
    out = HERE / "opencode.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Confirm the committed files contain no local info**

Run:

```bash
grep -rEi "<ollama-host>|<repo>|<email>|qwen3\.6" notes-mvp/gen_opencode_config.py notes-mvp/.env.example && echo "LEAK FOUND" || echo "clean: no local info in committed files"
```

Expected: `clean: no local info in committed files`.

- [ ] **Step 5: Generate the local config and verify invariants**

Create the local env from the example and fill in real values (this file is gitignored):

```bash
cp notes-mvp/.env.example notes-mvp/.env
# Edit notes-mvp/.env: set MODEL_ENDPOINT and MODEL_ID to the local endpoint/model.
set -a; . notes-mvp/.env; set +a
.venv/bin/python notes-mvp/gen_opencode_config.py
```

Then validate the generated config:

```bash
.venv/bin/python - <<'PY'
import json
c = json.load(open("notes-mvp/opencode.json"))
p = c["agent"]["workspace-assistant"]["permission"]
assert p["bash"]=="deny" and p["webfetch"]=="deny" and p["websearch"]=="deny" and p["task"]=="deny"
assert p["external_directory"]=="deny" and p["agenda_*"]=="allow"
assert c["permission"]["bash"]=="deny"
assert c["mcp"]["agenda"]["command"][0].endswith("agenda-server")
assert c["mcp"]["agenda"]["environment"]["NOTES_ROOT"]
assert c["model"].startswith("workspace-llm/")
print("generated opencode.json valid and invariants hold")
PY
```

Expected: prints `generated opencode.json valid and invariants hold`.

- [ ] **Step 6: Confirm git will not track the local files**

Run:

```bash
git check-ignore notes-mvp/opencode.json notes-mvp/.env && echo "local config + env ignored"
```

Expected: both paths echoed, then `local config + env ignored`.

- [ ] **Step 7: Commit only the generic files**

```bash
git add .gitignore notes-mvp/gen_opencode_config.py notes-mvp/.env.example
git commit -m "feat(notes-mvp): N1 config generator + env example (no local info committed)"
```

---

### Task 4: Deterministic wiring check — OpenCode spawns the server and registers the tools

This proves the wiring independent of model behaviour: OpenCode loads the config, spawns the Agenda MCP server, and exposes exactly the three `agenda_*` tools to the agent.

**Files:** none (verification task).

- [ ] **Step 1: Start the OpenCode server with the config**

Run (background it; capture logs). `cd` into `notes-mvp/` so OpenCode's directory-walk
finds `notes-mvp/opencode.json` (OpenCode 1.15.0 does not support `OPENCODE_CONFIG`):

```bash
cd "$(git rev-parse --show-toplevel)/notes-mvp"
opencode serve --hostname 127.0.0.1 --port 4123 \
  > /tmp/opencode-serve.log 2>&1 &
echo $! > /tmp/opencode-serve.pid
sleep 4
```

- [ ] **Step 2: Confirm health**

Run:

```bash
curl -s --max-time 5 http://127.0.0.1:4123/global/health && echo " <- health OK"
```

Expected: a health response (non-empty) then `health OK`. If it fails, read `/tmp/opencode-serve.log` for a config error and fix Task 3 before continuing.

- [ ] **Step 3: Confirm the agenda MCP server connected and its tools are registered**

OpenCode logs MCP server startup. Confirm the `agenda` server connected and the three tools are visible. First check the logs:

```bash
grep -iE "agenda|mcp" /tmp/opencode-serve.log | head -20
```

Then verify against the live API (the OpenAPI is at `/doc`; tool listing is exposed per session/config). Discover the exact endpoint, then assert all three tools are present:

```bash
# Discover the endpoint that lists tools (look for "tool" paths in the OpenAPI)
curl -s http://127.0.0.1:4123/doc | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin); print('\n'.join(p for p in d.get('paths',{}) if 'tool' in p.lower()))"
```

Using the discovered path (commonly `GET /experimental/tool` or `GET /config/providers`/`/tool`), fetch the registered tools and assert:

```bash
# Replace <TOOL_PATH> with the path discovered above:
curl -s "http://127.0.0.1:4123<TOOL_PATH>" | grep -o "agenda_[a-z]*" | sort -u
```

Expected: the three names `agenda_review`, `agenda_today`, `agenda_topic` appear. **If the OpenAPI exposes no tool-listing endpoint in 1.15.0**, fall back to the log assertion: confirm `/tmp/opencode-serve.log` shows the `agenda` MCP server connecting with 3 tools (grep for `agenda` + `tool`), which is sufficient proof of registration.

- [ ] **Step 4: Stop the server**

```bash
kill "$(cat /tmp/opencode-serve.pid)" 2>/dev/null; sleep 1; echo "stopped"
```

Expected: `stopped`, and `curl http://127.0.0.1:4123/global/health` now fails (port released).

---

### Task 5: End-to-end model check — qwen3.6 calls the tool and answers

This exercises the live model's tool-calling against the wired agenda tools.

**Files:** none (verification task).

- [ ] **Step 1: Drive a one-shot prompt through OpenCode**

From the notes directory so the agent's file tools and the agenda server share the same tree.
`cd` into `notes-mvp/sample-notes/` — OpenCode's directory-walk finds `notes-mvp/opencode.json`
one level up (OpenCode 1.15.0 does not support `OPENCODE_CONFIG`):

```bash
cd "$(git rev-parse --show-toplevel)/notes-mvp/sample-notes"
opencode run \
  --agent workspace-assistant \
  "What should I focus on today? Use your agenda tools, then answer." \
  2>&1 | tee /tmp/opencode-run.log
```

Expected: the run output shows an `agenda_today` tool invocation and the final answer names **"Sign off Atlas security design"** as the top do-now item. (`opencode run --agent workspace-assistant` is the correct invocation — `--agent` is confirmed valid in OpenCode 1.15.0. **Always pass `--agent workspace-assistant`** to ensure the sandboxed agent is selected; the default agent has no permission restrictions. A top-level `permission` block in the config denies `bash`/`webfetch`/`websearch`/`task` as defense-in-depth so the default agent is also restricted.)

- [ ] **Step 2: Confirm the tool was actually called (not hallucinated)**

```bash
grep -iE "agenda_today|tool" /tmp/opencode-run.log | head
```

Expected: evidence of an `agenda_today` tool call in the transcript. **If `<model-id>` answers without calling the tool**, record it as a finding (model tool-calling reliability), and retry once with a more explicit instruction ("Call the agenda_today tool first."). Wiring is already proven by Task 4; this step measures model behaviour, so a model miss is a model/prompt note, not a wiring failure.

- [ ] **Step 3: Confirm a note write works (native Workspace path)**

```bash
cd "$(git rev-parse --show-toplevel)/notes-mvp/sample-notes"
opencode run \
  --agent workspace-assistant \
  "Capture a note: spoke to Legal about the vendor licensing reply; add it under the procurement topic." \
  2>&1 | tee /tmp/opencode-note.log
# Then check the agent wrote into the notes tree (and nowhere else):
git -C "$(git rev-parse --show-toplevel)" status --porcelain notes-mvp/sample-notes/ | head
```

Expected: the agent used `write`/`edit` to record the note inside `notes-mvp/sample-notes/` (a changed/new file appears under that path); no file outside the tree is touched. Record the result regardless — this confirms the native Workspace write path under the live model.

---

### Task 6: README with launch + test commands

**Files:**
- Create: `notes-mvp/README.md`

- [ ] **Step 1: Write the README**

Create `notes-mvp/README.md`:

```markdown
# notes-mvp — OpenCode wiring for the Chief-of-Staff Notes assistant

A sandboxed notes agent driven by a local OpenAI-compatible model, with the
read-only Agenda MCP server wired in. The N1 wiring slice — no web frontend yet.

The OpenCode config is **generated locally and gitignored**; no machine-specific
data (paths, host, model) is committed. Only the generator and an env example
are tracked.

## One-time setup

    # 1. Runtime venv for the Agenda MCP server
    python3.12 -m venv .venv
    .venv/bin/pip install -e ./agenda          # provides `agenda-server`

    # 2. Local config: copy the example, fill in YOUR endpoint + model
    cp notes-mvp/.env.example notes-mvp/.env    # .env is gitignored
    #   edit notes-mvp/.env -> MODEL_ENDPOINT, MODEL_ID (and optional NOTES_ROOT)

    # 3. Generate the local opencode.json (gitignored)
    set -a; . notes-mvp/.env; set +a
    .venv/bin/python notes-mvp/gen_opencode_config.py

## Run the server

**OpenCode 1.15.0 note:** `OPENCODE_CONFIG` is not honoured; config is discovered
by directory-walk from the current working directory. Run from `notes-mvp/` (or
any subdirectory) so OpenCode finds `notes-mvp/opencode.json` automatically.

    cd notes-mvp
    opencode serve --hostname 127.0.0.1 --port 4123

Health: `curl http://127.0.0.1:4123/global/health`.

## One-shot prompt (headless)

    cd notes-mvp/sample-notes          # opencode walks up and finds notes-mvp/opencode.json
    opencode run --agent workspace-assistant "What should I focus on today?"

**Security note:** The sandbox binds to the `workspace-assistant` agent; a top-level
`permission` block denies `bash`/`webfetch`/`websearch`/`task` as defense-in-depth so
the default agent is also restricted.

## Notes

- The agent is sandboxed: `bash`/`webfetch`/`websearch`/`task` denied,
  `external_directory: deny`; native file tools + `agenda_*` allowed.
- The Agenda server reads its notes tree from `NOTES_ROOT` (set via `.env`,
  default `notes-mvp/sample-notes`).
- The agent sees the agenda tools as `agenda_today`, `agenda_review`, and
  `agenda_topic` (OpenCode prefixes the MCP server key `agenda` to the bare
  tool names `today`/`review`/`topic` advertised by the server).
- `notes-mvp/opencode.json` and `notes-mvp/.env` are gitignored — they hold the
  only machine-specific values. The future frontend (N3) will generate the
  config the same way, per install.
```

- [ ] **Step 2: Commit**

```bash
git add notes-mvp/README.md
git commit -m "docs(notes-mvp): launch and wiring-test instructions"
```

---

## Self-Review

**Spec coverage (design N1 + the wiring gap):**
- Restricted `opencode.json` (provider, model, agent, permission, mcp) → generated by Task 3 ✓ (matches design §8 permission set + appendix config shape).
- **No local info committed** → Task 3 gitignores `opencode.json` + `.env`, commits only the generic generator + placeholder example; Task 3 Step 4 greps the committed files for host/path/model leaks and fails closed ✓.
- Notes system prompt encoding data model + 6 loop verbs + conventions (`upd:`, action authority, segmentation, auto-tickler) → Task 2 ✓.
- Agenda MCP server actually spawned by OpenCode + exactly 3 read tools → Tasks 0/4 ✓.
- Real model (`<model-id>` on <ollama-host>) drives the agent end-to-end → Task 5 ✓.
- Native Workspace write path under the live model → Task 5 Step 3 ✓.

**Placeholder scan:** The only deliberately parameterised spots are (a) the tool-listing endpoint path in Task 4 Step 3, which the step *discovers* via `/doc` and provides a documented log-based fallback for (OpenCode 1.15.0's exact tool API is not assumed), and (b) the `opencode run --agent` flag with a stated fallback (single primary agent is selected by default). These are genuine runtime-discovery points, not skipped work — every command is concrete.

**Type/contract consistency:** Tool names (`agenda_today/review/topic`), the `agenda_*` permission glob, the `NOTES_ROOT` env var, and the `agenda-server` entry point all match Plan 1's delivered package and `mvp-chief-of-staff-notes-design.md` §5.3 / §8. The model id `<model-id>` and endpoint `http://<ollama-host>:11434/v1` match the verified pre-flight.

**Out of scope (later plans):** the Python web frontend, SSE proxy, chat UI, upload, and frontend-owned `notes/` git versioning (N3–N5, plan 3); the PowerShell launcher and the full smoke-test suite (N6–N7, plan 4); generating `opencode.json` per install (N3).
```
