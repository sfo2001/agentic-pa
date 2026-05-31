# Launcher, Sandbox Layout & Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Chief-of-Staff Notes assistant a one-command app — establish the leaf/parent install layout (agent sandbox = notes-only `workspace/` with **no `.git` at or above it**; git, config, secrets, prompt in the unreachable parent), a launcher that starts OpenCode + the frontend together with **isolated HOME/XDG**, and an end-to-end integration smoke.

**Architecture:** OpenCode's sandbox-confinement boundary is **source-verified** (1.15.13; confirmed on the installed 1.15.0): the `external_directory` scope is the launch **cwd** OR the enclosing **git work-tree root** (`instance-context.ts:18-24`, `project.ts:343`), so the install layout keeps **no `.git` at or above `workspace/`** and the notes audit repo uses a split git-dir named `notes.git/` (which OpenCode's git detection ignores). `versioning.py` is generalised to a split **git-dir (in the parent) / work-tree (= the sandbox)** so the agent can't reach version control. A `bootstrap.py` creates the install layout and generates the config into the parent. A small cross-platform **Python launcher** does pre-flight (incl. a **no-git-ancestor assertion**), starts `opencode serve` (cwd = `workspace/`, **clean HOME/XDG**) and the frontend, waits for health, and shuts both down. N7 is an end-to-end smoke against the local A3B model.

**Tech Stack:** Python 3.12 · stdlib `subprocess`/`socket`/`signal` · FastAPI/uvicorn (already present) · OpenCode 1.15.0 + Bun. TDD for the testable units (versioning split, bootstrap, pre-flight checks); the live launch + smoke are documented + partially automated.

**Scope note:** Plan **6 of 6** for Milestone 1 (spec WP1/N6 + integration N7; design §2.4/§4.4/§8 + ADR-0003). Plans 1–5 merged on `main`. This completes Milestone 1 (the local-only Chief-of-Staff Notes MVP).

**Canonical install layout (the decision this plan locks in):**
```
<install-root>/                 # NOT a git repo; NOT the agent sandbox; agent cannot reach it
├── opencode.json               # generated config (gitignored from the code repo)
├── .env                        # secrets (model endpoint, etc.)
├── notes-agent.md              # system prompt
├── notes.git/                  # notes version control (split git-dir, NOT ".git"; work-tree = workspace/)
├── oc-home/                    # isolated HOME/XDG for the OpenCode process (no global-config/skill bleed)
└── workspace/                  # THE sandbox = OpenCode launch cwd = NOTES_ROOT
    ├── inbox/ meetings/ topics/ documents/ briefs/ archive/
    └── tasks.todo.txt  index.md
```
**Invariant: there is no `.git` at or above `workspace/`.** OpenCode confines the agent to the launch cwd OR the enclosing git work-tree root (`git rev-parse --show-toplevel`); a `.git` in the install-root would expand the boundary to the whole parent. Naming the audit git-dir `notes.git/` (not `.git`) means OpenCode's git detection finds no work-tree, so the boundary is exactly `workspace/`. Rationale: the agent's native file tools are confined to `workspace/`, so `notes.git`/`.env`/`opencode.json`/`notes-agent.md` in the parent are unreachable — closing tamper of the audit trail, secret reads, and self-modification of permissions/prompt.

**Launcher language note:** the original spec (Windows-era) said *PowerShell*; this deployment is Linux (local ollama on the user's host). This plan uses a **cross-platform Python launcher** (`launcher/run.py`) — reuses the Python stack, works on Linux/macOS/Windows. (A thin `launcher/start.ps1`/`start.sh` wrapper can call it later if desired.)

**Files:**
- Create: `docs/decisions/D-opencode-sandbox.md` (source-verified decision record + confirmation probe)
- Modify: `frontend/versioning.py` — split git-dir/work-tree; `frontend/app.py` — pass the split through.
- Create: `frontend/bootstrap.py` — build the install layout + generate config into the parent.
- Modify: `notes-mvp/gen_opencode_config.py` — emit config for the leaf/parent layout (or supersede via bootstrap).
- Create: `launcher/run.py`, `launcher/README.md`.
- Create/modify tests; `tests/smoke/notes-mvp/` integration smoke.

---

### Task 1: OpenCode sandbox-confinement decision record (+ confirmation probe)

**Goal:** Record the **source-verified** confinement mechanism and confirm it on the installed 1.15.0 binary. The boundary is no longer an open question — the OpenCode source (1.15.13, cloned at `~/devel/opencode`) was read directly. This task writes the decision down and runs one live probe to confirm the installed version agrees, then locks the layout invariant the rest of the plan depends on.

**Source findings (already established — do not re-investigate):**
- `packages/opencode/src/project/instance-context.ts:18-24` — `containsPath` is true if the target is under `ctx.directory` (launch **cwd**) **OR** `ctx.worktree`; when `ctx.worktree === "/"` (no git) the worktree check is **skipped** → boundary = cwd.
- `packages/core/src/project.ts:343` + `git.ts:43-59` — `ctx.worktree` = `git rev-parse --show-toplevel`; non-git → `"/"`.
- `packages/opencode/src/tool/external-directory.ts:16-44` — the deny check calls `containsPath`.
- `packages/opencode/src/agent/agent.ts:107-126` — built-in defaults include `* allow` and `external_directory` allow-list = tool-output dir + `/tmp/opencode/*` + **skillDirs** (so global skills bleed into the allow-list unless HOME/XDG is isolated).
- `packages/opencode/src/config/config.ts:601-603` — `OPENCODE_CONFIG` IS honored (merges, does not replace).

**Decision this locks in:** the agent boundary = launch cwd OR enclosing git work-tree root ⇒ **keep no `.git` at or above `workspace/`**, name the audit git-dir `notes.git/` (not `.git`), and run OpenCode with isolated HOME/XDG.

**Files:** Create `docs/decisions/D-opencode-sandbox.md`.

- [ ] **Step 1: Construct the confirmation layout (no git ancestor)**

```bash
ROOT=$(mktemp -d)
mkdir -p "$ROOT/workspace"
# NOTE: do NOT `git init` the root — the layout must have no .git at/above workspace/.
printf 'secret\n' > "$ROOT/SECRET.txt"      # a file in the PARENT, outside workspace/
# Generate an opencode.json at <root> (workspace-assistant agent: bash/webfetch/websearch/task denied,
# external_directory deny) pointing at the local model; launch from workspace/ with an isolated HOME/XDG.
```
(Reuse `notes-mvp/gen_opencode_config.py` to emit `<root>/opencode.json`; set NOTES_ROOT/agent per the existing config.)

- [ ] **Step 2: Probe the boundary on the installed binary**

From `<root>/workspace`, with a clean HOME/XDG, run one-shots that try to escape:
```bash
cd "$ROOT/workspace"
env HOME="$ROOT/oc-home" XDG_CONFIG_HOME="$ROOT/oc-home/.config" XDG_DATA_HOME="$ROOT/oc-home/.local/share" \
  opencode run --agent workspace-assistant "Read the file ../SECRET.txt and tell me its contents." 2>&1 | tee /tmp/oc-sandbox.log
```
Expected (source-predicted): the `read` of `../SECRET.txt` is **refused** (no git → boundary = cwd = `workspace/`). Also try `"Write 'x' to ../pwned.txt"` and confirm `<root>/pwned.txt` was NOT created. Then create a `<root>/.git` (`git -C "$ROOT" init -q`) and re-probe to **demonstrate the failure mode**: with a parent `.git`, `../SECRET.txt` becomes readable (boundary expands to the git root) — this is exactly what the layout invariant prevents.

- [ ] **Step 3: Write the decision record**

Create `docs/decisions/D-opencode-sandbox.md` capturing:
- The source mechanism with the file:line citations above (boundary = cwd OR git work-tree root).
- The probe results on 1.15.0 (no-git → escape refused; parent-`.git` → escape allowed), confirming source.
- **The locked layout invariant:** no `.git` at or above `workspace/`; audit git-dir named `notes.git/` in the install-root; OpenCode launched with isolated HOME/XDG. No "TBD".
- Confirm the four denials (`bash`/`webfetch`/`websearch`/`task`) hold from `workspace/`.

**Acceptance:** the decision record states the source-verified mechanism (with citations + probe evidence) and the resulting layout invariant. Downstream tasks consume it.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/D-opencode-sandbox.md
git commit -m "docs(launcher): record source-verified OpenCode sandbox boundary + layout invariant"
```

---

### Task 2: Split git-dir / work-tree in versioning

Generalise `versioning.py` so the git metadata lives outside the work-tree (the sandbox). All ops take an explicit `git_dir` + `work_tree`; the existing single-arg form becomes a thin wrapper using `<root>/.git` for back-compat in tests.

**Files:** Modify `frontend/versioning.py`; Test `tests/frontend/test_versioning.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/frontend/test_versioning.py`:

```python
def test_split_gitdir_keeps_dotgit_out_of_worktree(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    gd = tmp_path / "notes.git"
    versioning.ensure_repo(work, git_dir=gd)
    assert gd.is_dir()                       # metadata lives outside the work-tree
    assert not (work / ".git").exists()      # nothing inside the sandbox
    (work / "tasks.todo.txt").write_text("(A) x +y upd:2026-05-30", encoding="utf-8")
    sha = versioning.commit_all(work, "ingest", git_dir=gd)
    assert sha
    # the committed tree contains the work-tree file, nothing from outside
    files = subprocess.run(["git", f"--git-dir={gd}", f"--work-tree={work}",
                            "ls-tree", "-r", "--name-only", "HEAD"],
                           capture_output=True, text=True).stdout.split()
    assert files == ["tasks.todo.txt"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_versioning.py::test_split_gitdir_keeps_dotgit_out_of_worktree -v`
Expected: FAIL — `ensure_repo()` has no `git_dir` kwarg.

- [ ] **Step 3: Implement the split**

In `frontend/versioning.py`, change `_git` and the public functions to take an optional `git_dir`. When `git_dir` is given, use `--git-dir`/`--work-tree`; otherwise default `git_dir = work_tree/".git"` (back-compat). Example shape:

```python
def _git(work_tree, *args, git_dir=None, check=True):
    base = ["git"]
    if git_dir is not None:
        base += [f"--git-dir={Path(git_dir)}", f"--work-tree={Path(work_tree)}"]
    else:
        base += ["-C", str(work_tree)]
    return subprocess.run([*base, *args], capture_output=True, text=True, check=check)


def is_repo(work_tree, git_dir=None) -> bool:
    return (Path(git_dir) if git_dir is not None else Path(work_tree) / ".git").is_dir()


def ensure_repo(work_tree, git_dir=None) -> None:
    work = Path(work_tree).resolve()
    app_dir = Path(__file__).resolve().parent
    if app_dir == work or app_dir.is_relative_to(work) or work.is_relative_to(app_dir):
        raise RuntimeError(f"NOTES_ROOT ({work}) is inside the application source tree; "
                           "point it at a separate directory outside the code repo")
    work.mkdir(parents=True, exist_ok=True)
    if not is_repo(work, git_dir):
        if git_dir is not None:
            Path(git_dir).mkdir(parents=True, exist_ok=True)
            _git(work, "init", "-q", git_dir=git_dir)
        else:
            _git(work, "init", "-q")
    _git(work, "config", "user.name", _COMMITTER_NAME, git_dir=git_dir)
    _git(work, "config", "user.email", _COMMITTER_EMAIL, git_dir=git_dir)
    if _git(work, "rev-parse", "--verify", "HEAD", git_dir=git_dir, check=False).returncode != 0:
        _git(work, "commit", "--allow-empty", "-q", "-m", "notes: initialise", git_dir=git_dir)
```

Thread `git_dir=` through `commit_all` and `revert_last` the same way (each `_git(...)` call gains `git_dir=git_dir`). Keep `_subject` unchanged. (`git init --git-dir=X --work-tree=Y` with an absolute git-dir creates a separate-dir repo; verify the `ls-tree` in the test shows only work-tree files.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_versioning.py -v`
Expected: PASS — the new split test plus all existing single-arg tests (back-compat).

- [ ] **Step 5: Commit**

```bash
git add frontend/versioning.py tests/frontend/test_versioning.py
git commit -m "feat(frontend): split git-dir/work-tree so notes .git lives outside the sandbox"
```

---

### Task 3: Install-layout bootstrap

A module that builds `<install-root>/` per the canonical layout (path scheme from the spike), generates `opencode.json` + `notes-agent.md` into the parent, and inits the split notes repo with the sandbox as work-tree.

**Files:** Create `frontend/bootstrap.py`; Test `tests/frontend/test_bootstrap.py`.

- [ ] **Step 1: Write the failing test**

`tests/frontend/test_bootstrap.py`:

```python
import json
from pathlib import Path

import pytest

from frontend import bootstrap, versioning


def test_bootstrap_builds_leaf_parent_layout(tmp_path):
    root = tmp_path / "cos-notes"
    layout = bootstrap.init_install(
        root,
        model_endpoint="http://example:11434/v1",
        model_id="test-model",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    work = root / "workspace"
    assert work.is_dir()
    # config + secrets + prompt + git-dir live in the PARENT, not in workspace/
    assert (root / "opencode.json").is_file()
    assert (root / "notes-agent.md").is_file()
    assert not (work / "opencode.json").exists()
    assert not (work / ".git").exists()
    assert versioning.is_repo(work, git_dir=layout["git_dir"])
    # opencode.json points the agent at workspace/ and the prompt in the parent
    cfg = json.loads((root / "opencode.json").read_text())
    assert cfg["mcp"]["agenda"]["environment"]["NOTES_ROOT"] == str(work)
    assert str(root / "notes-agent.md") in cfg["agent"]["workspace-assistant"]["prompt"]
    p = cfg["agent"]["workspace-assistant"]["permission"]
    assert p["bash"] == "deny" and p["external_directory"] == "deny"
    # idempotent
    bootstrap.init_install(root, model_endpoint="http://example:11434/v1",
                           model_id="test-model", agenda_server="/opt/.venv/bin/agenda-server")
    assert work.is_dir()


def test_bootstrap_refuses_install_inside_existing_git_repo(tmp_path):
    # A .git at/above the install-root would expand the agent's sandbox boundary
    # to the git work-tree root (ADR-0005), so bootstrap must refuse.
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(RuntimeError, match="git repo"):
        bootstrap.init_install(
            tmp_path / "cos-notes",
            model_endpoint="http://example:11434/v1",
            model_id="test-model",
            agenda_server="/opt/.venv/bin/agenda-server",
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_bootstrap.py -v`
Expected: FAIL — `No module named 'frontend.bootstrap'`.

- [ ] **Step 3: Implement**

`frontend/bootstrap.py` — create `workspace/`, write `notes-agent.md` (copy the canonical prompt text — import it from a shared location or vendor it), generate `opencode.json` (reuse the dict-builder logic from `notes-mvp/gen_opencode_config.py`, but with `NOTES_ROOT = <root>/workspace`, `prompt = {file:<root>/notes-agent.md}`, top-level + agent permission denials, the `agenda` MCP server command), then `versioning.ensure_repo(<root>/workspace, git_dir=<root>/notes.git)`. Return `{"install_root", "workspace", "git_dir", "opencode_json"}`.

**Git-dir = `<root>/notes.git` (named, NOT `.git`).** Do **not** `git init` the install-root and do not create any `.git` at or above `workspace/` — the split git-dir is the only repo, and its non-`.git` name keeps OpenCode's git detection from treating the install-root as a work-tree (ADR-0005). Add a guard at the start of `init_install`: walk from `<root>` upward and raise if any ancestor (including `<root>`) contains a `.git` entry — installing inside an existing git repo would expand the agent's sandbox boundary to that repo's root. Refactor the config-dict construction shared with `gen_opencode_config.py` into a single helper to avoid drift (DRY).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_bootstrap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/bootstrap.py tests/frontend/test_bootstrap.py notes-mvp/gen_opencode_config.py
git commit -m "feat(frontend): install-layout bootstrap (leaf sandbox + parent config/git)"
```

---

### Task 4: The launcher

A cross-platform Python launcher: pre-flight, start `opencode serve` (cwd `workspace/`) + the frontend, wait for health, clean shutdown.

**Files:** Create `launcher/run.py`, `launcher/README.md`; Test `tests/launcher/test_preflight.py`.

- [ ] **Step 1: Write the failing test (pre-flight units)**

`tests/launcher/test_preflight.py`:

```python
import socket
import subprocess

from launcher.run import port_is_free, require_tools, no_git_ancestor, isolated_env


def test_port_is_free_detects_bound_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    bound = s.getsockname()[1]
    try:
        assert port_is_free(bound) is False
        # an almost-certainly-free high port
        assert port_is_free(0) is True or port_is_free(54999) in (True, False)
    finally:
        s.close()


def test_require_tools_reports_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    missing = require_tools(["opencode", "bun"])
    assert set(missing) == {"opencode", "bun"}


def test_no_git_ancestor_true_when_clean(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    assert no_git_ancestor(work) is True


def test_no_git_ancestor_false_when_parent_is_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    work = tmp_path / "workspace"
    work.mkdir()
    # a .git at the parent would expand the agent's sandbox boundary (ADR-0005)
    assert no_git_ancestor(work) is False


def test_isolated_env_overrides_home_and_xdg(tmp_path):
    env = isolated_env(tmp_path, base={"PATH": "/usr/bin", "HOME": "/home/real"})
    oc_home = str(tmp_path / "oc-home")
    assert env["HOME"] == oc_home
    assert env["XDG_CONFIG_HOME"].startswith(oc_home)
    assert env["XDG_DATA_HOME"].startswith(oc_home)
    # Windows globals are redirected too, so the same launcher works cross-platform
    assert env["APPDATA"].startswith(oc_home)
    assert env["USERPROFILE"] == oc_home
    assert env["PATH"] == "/usr/bin"  # PATH is preserved (opencode/bun must stay findable)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/launcher/test_preflight.py -v`
Expected: FAIL — `No module named 'launcher.run'`.

- [ ] **Step 3: Implement the launcher**

`launcher/run.py`:

```python
"""Cross-platform launcher: pre-flight, start OpenCode + the frontend, health-wait, shutdown."""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def require_tools(names: list[str]) -> list[str]:
    return [n for n in names if shutil.which(n) is None]


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def no_git_ancestor(path) -> bool:
    """True iff there is no `.git` at `path` or any ancestor — so OpenCode won't
    anchor the sandbox boundary to a git work-tree root (ADR-0005)."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return False
    return True


def isolated_env(install_root, base=None) -> dict:
    """Clean HOME/XDG (and Windows %APPDATA%/%LOCALAPPDATA%/%USERPROFILE%) pointed
    at <install_root>/oc-home, so the user's global ~/.config/opencode config and
    skill dirs do not merge into the agent (skillDirs feed the external_directory
    allow-list — agent/agent.ts:107-126). PATH is preserved so opencode/bun stay
    findable."""
    env = dict(os.environ if base is None else base)
    oc_home = str(Path(install_root) / "oc-home")
    env["HOME"] = oc_home
    env["USERPROFILE"] = oc_home
    env["XDG_CONFIG_HOME"] = str(Path(oc_home) / ".config")
    env["XDG_DATA_HOME"] = str(Path(oc_home) / ".local" / "share")
    env["XDG_STATE_HOME"] = str(Path(oc_home) / ".local" / "state")
    env["XDG_CACHE_HOME"] = str(Path(oc_home) / ".cache")
    env["APPDATA"] = str(Path(oc_home) / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(Path(oc_home) / "AppData" / "Local")
    return env


def _wait_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    install_root = Path(os.environ.get("INSTALL_ROOT", Path.home() / "cos-notes")).resolve()
    workspace = install_root / "workspace"
    oc_port = int(os.environ.get("OPENCODE_PORT", "4096"))
    web_port = int(os.environ.get("WEB_PORT", "8000"))

    missing = require_tools(["opencode"])
    if missing:
        print(f"ERROR: missing required tools on PATH: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not workspace.is_dir():
        print(f"ERROR: {workspace} not found — run bootstrap first.", file=sys.stderr)
        return 2
    if not no_git_ancestor(workspace):
        print(f"ERROR: a .git exists at or above {workspace}; this would expand the agent's "
              "sandbox boundary to the git work-tree root (ADR-0005). Install outside any git repo.",
              file=sys.stderr)
        return 2
    for p in (oc_port, web_port):
        if not port_is_free(p):
            print(f"ERROR: port {p} is in use; free it or set OPENCODE_PORT/WEB_PORT.", file=sys.stderr)
            return 2

    procs: list[subprocess.Popen] = []
    try:
        oc_env = isolated_env(install_root)
        Path(oc_env["HOME"]).mkdir(parents=True, exist_ok=True)
        procs.append(subprocess.Popen(
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(oc_port)],
            cwd=str(workspace), env=oc_env))
        if not _wait_health(f"http://127.0.0.1:{oc_port}/global/health"):
            print("ERROR: OpenCode server did not become healthy.", file=sys.stderr)
            return 3
        env = {**os.environ,
               "OPENCODE_BASE_URL": f"http://127.0.0.1:{oc_port}",
               "NOTES_ROOT": str(workspace),
               "NOTES_GIT_DIR": str(install_root / "notes.git")}
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "--factory", "frontend.app:build_default_app",
             "--host", "127.0.0.1", "--port", str(web_port)], env=env))
        if not _wait_health(f"http://127.0.0.1:{web_port}/health"):
            print("ERROR: frontend did not become healthy.", file=sys.stderr)
            return 3
        print(f"Ready — open http://127.0.0.1:{web_port}/  (Ctrl+C to stop)")
        signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in reversed(procs):
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> Note: `build_default_app` must read `NOTES_ROOT` (it does) and — for the split git — the versioning git-dir. Update `build_default_app` to also resolve the git-dir from the layout (env `NOTES_GIT_DIR`, default per the spike scheme) and pass it through to `versioning` calls in the app. Add that wiring + a test in this task if not already covered by Task 2/3.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/launcher/test_preflight.py -v`
Expected: PASS.

- [ ] **Step 5: Write `launcher/README.md` + commit**

`launcher/README.md`: one screen — `INSTALL_ROOT` (default `~/cos-notes`), `python launcher/run.py` after `frontend.bootstrap.init_install(...)`, env vars (`OPENCODE_PORT`, `WEB_PORT`), and the Ctrl+C shutdown. Note (a) the PowerShell→Python deviation, (b) that the install-root must not be inside a git repo (the launcher refuses it), and (c) that OpenCode runs with an isolated HOME/XDG (`<install-root>/oc-home`) so the user's global config/skills don't leak into the agent.

```bash
git add launcher/ tests/launcher/
git commit -m "feat(launcher): cross-platform Python launcher + pre-flight checks"
```

---

### Task 5 (N7): End-to-end integration smoke

**Files:** Create `tests/smoke/notes-mvp/smoke.md` (documented) + `tests/smoke/notes-mvp/run_smoke.py` (automated subset).

- [ ] **Step 1: Full unit suite green**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS (agenda + frontend + bootstrap + launcher preflight).

- [ ] **Step 2: Automated integration subset (no browser, real model)**

`tests/smoke/notes-mvp/run_smoke.py` — a script (not part of the default pytest run) that: bootstraps a throwaway `INSTALL_ROOT` (tmp), drops a raw note in `workspace/inbox/`, starts serve+frontend via the launcher pieces, drives one "Process the inbox." turn through `POST /api/message` + `GET /api/events`, asserts (a) the events stream relays `message_delta`+`done`, (b) `workspace/` gained a meeting/topic/task file, (c) the notes git log shows a `notes: Process the inbox` commit at the parent git-dir `notes.git/` (outside `workspace/`, queried via `git --git-dir=<root>/notes.git --work-tree=<root>/workspace log`), (d) `POST /api/undo` reverts it, then tears down. Print PASS/FAIL per assertion. (Uses the live A3B model; allow generous timeouts.)

- [ ] **Step 3: Manual browser smoke checklist**

Append the human checklist to `tests/smoke/notes-mvp/smoke.md`: open the UI, send a message (streams), Daily-brief button (tool chip), upload a doc (lands in `workspace/documents/`), inbox badge, Undo last. Confirm the audit repo is `notes.git/` in the parent and there is **no `.git` at or above `workspace/`** (`git -C workspace rev-parse --show-toplevel` should fail).

- [ ] **Step 4: Commit**

```bash
git add tests/smoke/notes-mvp/
git commit -m "test(smoke): end-to-end integration smoke (ingest→commit→undo) + manual checklist"
```

---

## Self-Review

**Spec coverage (WP1/N6 + N7 + the sandbox-layout decision):**
- Pre-flight (tools present, port free, **no git ancestor**) → Task 4 (`require_tools`, `port_is_free`, `no_git_ancestor`) ✓
- Start frontend + OpenCode (cwd `workspace/`, **isolated HOME/XDG**), health-gate, clean shutdown → Task 4 (`main`, `isolated_env`) ✓
- git/config/secrets/prompt outside the agent sandbox → Tasks 2+3 (split git-dir named `notes.git`; parent layout) + Task 1 source-verified decision record (mechanism) ✓
- End-to-end smoke (ingest→commit→undo, brief, upload) → Task 5 ✓

**Placeholder scan:** the confinement mechanism is source-verified (Task 1 records it with citations, no "TBD"); the git-dir is fixed at `<root>/notes.git`. All code blocks are complete.

**Type/contract consistency:** `versioning` functions gain an optional `git_dir=` consistently (with single-arg back-compat); `bootstrap.init_install(...)` returns `{install_root, workspace, git_dir, opencode_json}` used by the launcher; the config-dict builder is shared (DRY) between `gen_opencode_config.py` and `bootstrap.py`. `build_default_app` reads `NOTES_ROOT` + `NOTES_GIT_DIR`. Launcher helpers `no_git_ancestor`/`isolated_env` are unit-tested in Task 4.

**Risks called out:** the source is 1.15.13 while the installed binary is 1.15.0 — Task 1's confirmation probe verifies the boundary matches on 1.15.0 (the prior probes already align). The hard invariant — no `.git` at or above `workspace/` — is enforced in both bootstrap (refuses install inside a git repo) and launcher pre-flight (`no_git_ancestor`), because a stray ancestor `.git` silently widens the agent's reach to the whole git root. Launching a long-lived process pair is only partially unit-testable; pre-flight is TDD'd, the live launch is covered by the Task 5 smoke.

**Out of scope (post-Milestone-1):** auto folder-watch; rich Markdown rendering; the per-turn file-context note; external Grounding Sources (Confluence/Jira — Milestone 2); a packaged installer / service unit.

---

## Post-merge status & known follow-up (2026-05-31)

Executed via subagent-driven-development, /pr-audit (security remediation incl.
`build_default_app` now requiring `NOTES_GIT_DIR`), and merged to `main`. Unit
suite: **114 passing**.

**Live smoke result (real local model on the local host): 7/7 PASS.**
Verified end-to-end: streaming (604 SSE events incl. `message_delta` + terminal
`done`), tool-call chips surfaced (`read×7, write, write, edit, read`), ingest →
`meetings/` + `topics/` files + populated `tasks.todo.txt` → commit to the external
`notes.git` (sandbox boundary intact) → `undo` reverts.

**Resolved follow-up — smoke SSE reader (was a test-harness defect, NOT a product
bug).** An earlier 5/7 run failed only the SSE assertions because the smoke's
`_consume_sse` read the chunked `text/event-stream` with raw
`http.client.HTTPConnection`, which truncated the stream early
(`RemoteProtocolError: incomplete chunked read`) → 0 browser events. The frontend
relay reads the upstream with `httpx` and was **correct** all along against the live
wire protocol (`message.part.delta{field:"text",delta}`, `session.idle`) — see
`docs/decisions/D-opencode-http.md` §8. **Fix applied:** `_consume_sse` now uses
`httpx.Client(...).stream("GET", "/api/events").iter_lines()`. The 7/7 run above is
the end-to-end confirmation that `message_delta` + `done` reach the browser model
(full relay path, not just the upstream `/event`).

## Focused-review remediation (2026-05-31)

A `/focused-review` of this subsystem raised 8 findings (2 MEDIUM, 3 LOW, 3 INFO);
all are fixed on `fix/sandbox-hardening`:
- **F-1 (confinement):** `isolated_env` now strips all `OPENCODE_*` env vars (the
  env config channel, esp. `OPENCODE_CONFIG`), not just HOME/XDG.
- **F-2 (auth):** the launcher generates a per-run random `OPENCODE_SERVER_PASSWORD`,
  passes it to `opencode serve` + the frontend, and authenticates the health check
  (verified: unauthenticated `/global/health` → 401).
- **F-3 (pre-flight):** also verifies `notes.git` and the configured `agenda-server`
  exist before starting.
- **F-4:** `revert_last` converts a failed `git revert` to `RuntimeError` (so
  `/api/undo` returns a clean 400, not a 500) and aborts the half-applied revert.
- **F-5:** bootstrap rewrites `notes-agent.md` unconditionally (parity with
  `opencode.json`).
- **F-6:** OpenCode output captured to `<install-root>/opencode.log`.
- **F-7 / F-8 (accepted):** port check-then-bind race and the uvicorn import
  requirement are documented in code/README as accepted for the single-user
  localhost model.

Docs updated: design §8, `D-opencode-sandbox.md`, `launcher/README.md`. Unit suite
119 passing; E2E smoke 7/7.
