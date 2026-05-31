# Frontend-Owned Notes Git Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every agent operation on the notes tree reversible — the frontend versions `notes/` as its own git repo, commits after each chat turn, and exposes an `undo` that reverts the last commit (ADR-0003).

**Architecture:** A small `frontend/versioning.py` wraps `subprocess git -C <notes_root>` with three operations — `ensure_repo` (init + generic committer identity + initial commit, idempotent), `commit_all` (stage everything, commit a one-line subject, no-op on a clean tree), `revert_last` (undo = `git revert --no-edit HEAD`). The FastAPI app calls `ensure_repo` on startup, commits after each completed `/api/message` turn (the agent's writes are on disk because `proxy.send` blocks until the turn finishes), and exposes `POST /api/undo`. The notes repo is **separate from the application code repo** and never carries the user's git identity (a fixed `Notes Assistant <notes@localhost>` committer).

**Tech Stack:** Python 3.12 · stdlib `subprocess` (git CLI) · FastAPI. TDD against real throwaway git repos in `tmp_path`.

**Scope note:** Plan **5 of 5** for Milestone 1 (design `mvp-chief-of-staff-notes-design.md` §8 + ADR-0003; plan WP **N5**). Plans 1–4 merged on `main`. After this, Milestone 1 frontend is complete; remaining: N6–N7 (PowerShell launcher + end-to-end integration smoke).

**Key constraints (from the design + bug-hunt):**
- The agent is sandboxed (no shell); **only the frontend** commits — confirmed in plan 2's sandbox verification.
- The notes repo must be a **separate repo** (not the code repo). For dev/smoke, `NOTES_ROOT` must point at a directory **outside** this code repo — a nested `.git` inside `notes-mvp/sample-notes/` would make the code repo stop tracking the fixture. Tests use `tmp_path`.
- Committer identity is a fixed generic `Notes Assistant <notes@localhost>` — never the user's identity (no-leak principle).

**Files:**
- Create: `frontend/versioning.py`
- Modify: `frontend/app.py` — `ensure_repo` on startup, commit after `/api/message`, `POST /api/undo`.
- Modify: `frontend/ui/index.html`, `frontend/ui/app.js` — an "Undo last" control.
- Modify: `frontend/README.md` — versioning behaviour + the separate-repo caveat.
- Test: `tests/frontend/test_versioning.py`, additions to `tests/frontend/test_app.py`.

---

### Task 1: The versioning module

**Files:** Create `frontend/versioning.py`; Test `tests/frontend/test_versioning.py`.

- [ ] **Step 1: Write the failing tests**

`tests/frontend/test_versioning.py`:

```python
import subprocess

import pytest

from frontend import versioning


def _count(root):
    return int(subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                              capture_output=True, text=True).stdout.strip())


def test_ensure_repo_inits_with_head_and_is_idempotent(tmp_path):
    versioning.ensure_repo(tmp_path)
    assert (tmp_path / ".git").is_dir()
    assert _count(tmp_path) == 1                      # initial commit exists
    versioning.ensure_repo(tmp_path)                  # idempotent
    assert _count(tmp_path) == 1
    cfg = subprocess.run(["git", "-C", str(tmp_path), "config", "user.email"],
                         capture_output=True, text=True).stdout.strip()
    assert cfg == "notes@localhost"                   # generic identity, not the user's


def test_commit_all_commits_changes_and_noops_when_clean(tmp_path):
    versioning.ensure_repo(tmp_path)
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text("x", encoding="utf-8")
    sha = versioning.commit_all(tmp_path, "Process the inbox")
    assert sha and _count(tmp_path) == 2
    subj = subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
                          capture_output=True, text=True).stdout.strip()
    assert subj == "notes: Process the inbox"
    assert versioning.commit_all(tmp_path, "again") is None   # clean tree -> no-op
    assert _count(tmp_path) == 2


def test_revert_last_undoes_the_last_commit(tmp_path):
    versioning.ensure_repo(tmp_path)
    f = tmp_path / "note.md"
    f.write_text("hello", encoding="utf-8")
    versioning.commit_all(tmp_path, "add note")
    assert f.exists()
    versioning.revert_last(tmp_path)
    assert not f.exists()                             # revert removed the added file
    assert _count(tmp_path) == 3                      # revert is a new commit


def test_revert_last_raises_when_nothing_to_undo(tmp_path):
    versioning.ensure_repo(tmp_path)                  # only the initial commit
    with pytest.raises(RuntimeError):
        versioning.revert_last(tmp_path)


def test_subject_truncates_and_defaults():
    assert versioning._subject("a" * 100).startswith("notes: ")
    assert len(versioning._subject("a" * 100)) <= len("notes: ") + 72
    assert versioning._subject("   ") == "notes: agent turn"
    assert versioning._subject("line1\nline2") == "notes: line1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_versioning.py -v`
Expected: FAIL — `No module named 'frontend.versioning'`.

- [ ] **Step 3: Implement**

`frontend/versioning.py`:

```python
"""Frontend-owned git versioning of the notes tree (ADR-0003).

The agent is sandboxed (no shell), so the *frontend* commits the notes tree after
each operation, making changes reversible (undo = revert). The notes tree is its
OWN git repo, separate from the application code repo, and commits use a fixed
generic identity (never the user's).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_COMMITTER_NAME = "Notes Assistant"
_COMMITTER_EMAIL = "notes@localhost"


def _git(notes_root, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(notes_root), *args],
        capture_output=True, text=True, check=check,
    )


def is_repo(notes_root) -> bool:
    return (Path(notes_root) / ".git").is_dir()


def ensure_repo(notes_root) -> None:
    """Initialise ``notes_root`` as its own git repo (idempotent). Sets a generic
    committer identity and makes an initial commit so HEAD always exists."""
    root = Path(notes_root)
    root.mkdir(parents=True, exist_ok=True)
    if is_repo(root):
        return
    _git(root, "init", "-q")
    _git(root, "config", "user.name", _COMMITTER_NAME)
    _git(root, "config", "user.email", _COMMITTER_EMAIL)
    _git(root, "commit", "--allow-empty", "-q", "-m", "notes: initialise")


def _subject(message: str) -> str:
    stripped = (message or "").strip()
    line = stripped.splitlines()[0][:72] if stripped else "agent turn"
    return f"notes: {line or 'agent turn'}"


def commit_all(notes_root, message: str) -> str | None:
    """Stage everything and commit a one-line subject derived from ``message``.
    Returns the new commit sha, or ``None`` if the tree was clean."""
    root = Path(notes_root)
    _git(root, "add", "-A")
    if not _git(root, "status", "--porcelain").stdout.strip():
        return None
    _git(root, "commit", "-q", "-m", _subject(message))
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def revert_last(notes_root) -> str:
    """Undo the most recent commit via ``git revert``. Returns the revert commit's
    sha. Raises ``RuntimeError`` if only the initial commit exists."""
    root = Path(notes_root)
    count = int(_git(root, "rev-list", "--count", "HEAD").stdout.strip())
    if count <= 1:
        raise RuntimeError("nothing to undo")
    _git(root, "revert", "--no-edit", "-q", "HEAD")
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def recent_subjects(notes_root, n: int = 5) -> list[str]:
    out = _git(notes_root, "log", f"-{n}", "--format=%s", check=False).stdout.strip()
    return out.splitlines() if out else []
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_versioning.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/versioning.py tests/frontend/test_versioning.py
git commit -m "feat(frontend): notes git versioning module (init/commit/revert, ADR-0003)"
```

---

### Task 2: Wire versioning into the app

**Files:** Modify `frontend/app.py`; Test additions in `tests/frontend/test_app.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/frontend/test_app.py`:

```python
import subprocess

from frontend import versioning


def _last_subject(root):
    return subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%s"],
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.asyncio
async def test_startup_inits_notes_repo(tmp_path):
    app = _app(tmp_path)                       # _app helper from earlier tests
    from asgi_lifespan import LifespanManager
    async with LifespanManager(app):
        assert versioning.is_repo(tmp_path)


@pytest.mark.asyncio
async def test_message_commits_notes_changes(tmp_path):
    versioning.ensure_repo(tmp_path)
    # simulate an agent write that happened during the (fake) turn
    (tmp_path / "tasks.todo.txt").write_text("(A) do it +x upd:2026-05-30", encoding="utf-8")
    app = _app(tmp_path, script=[{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/message", json={"text": "Process the inbox"})
        assert r.status_code == 200
        assert r.json()["committed"] is not None        # a sha
    assert _last_subject(tmp_path) == "notes: Process the inbox"


@pytest.mark.asyncio
async def test_undo_reverts_last(tmp_path):
    versioning.ensure_repo(tmp_path)
    (tmp_path / "f.md").write_text("x", encoding="utf-8")
    versioning.commit_all(tmp_path, "add f")
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/undo")
        assert r.status_code == 200 and r.json()["reverted"]
    assert not (tmp_path / "f.md").exists()


@pytest.mark.asyncio
async def test_undo_400_when_nothing_to_undo(tmp_path):
    versioning.ensure_repo(tmp_path)
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/undo")
        assert r.status_code == 400 and r.json()["ok"] is False
```

> The `_app(tmp_path, script=...)` helper exists in `test_app.py` from plan 4. If its signature differs, adapt these tests to construct the app the same way the other `test_app.py` tests do, passing `notes_root=tmp_path`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_app.py -k "commit or undo or startup_inits" -v`
Expected: FAIL — `/api/undo` 404; `committed` key absent; repo not inited on startup.

- [ ] **Step 3: Implement the wiring**

In `frontend/app.py`: import versioning, init on startup, commit after a turn, add `/api/undo`.

Add the import near the others:

```python
from frontend import versioning
```

Replace the `lifespan` so startup initialises the repo (keep the shutdown `aclose`):

```python
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        versioning.ensure_repo(notes_root)
        yield
        await proxy.aclose()
```

Replace the `post_message` handler to commit after the (completed) turn:

```python
    @app.post("/api/message")
    async def post_message(msg: MessageIn):
        try:
            await proxy.send(msg.text)
        except SessionLost:
            return JSONResponse(status_code=503, content={"ok": False, "error": "session lost"})
        committed = versioning.commit_all(notes_root, msg.text)
        return {"ok": True, "committed": committed}
```

Add the undo endpoint (next to the others):

```python
    @app.post("/api/undo")
    async def undo():
        try:
            sha = versioning.revert_last(notes_root)
        except RuntimeError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        return {"ok": True, "reverted": sha}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_app.py -v`
Expected: PASS (all, including the 4 new versioning-wiring tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/app.py tests/frontend/test_app.py
git commit -m "feat(frontend): commit notes per turn + /api/undo; init repo on startup"
```

---

### Task 3: Undo control in the UI

**Files:** Modify `frontend/ui/index.html`, `frontend/ui/app.js`; assert in `tests/frontend/test_app.py`.

- [ ] **Step 1: Add the button to `index.html`**

In the `<nav class="notes-buttons">` block, add an undo button after the three action buttons (before the upload label):

```html
    <button id="undo" type="button">Undo last</button>
```

- [ ] **Step 2: Add the handler to `app.js`**

Append to `frontend/ui/app.js` (before the final `refreshInbox();` line):

```javascript
const undoBtn = document.getElementById("undo");
undoBtn.addEventListener("click", async () => {
  if (composer.getAttribute("aria-disabled") === "true") return;
  try {
    const r = await fetch("/api/undo", { method: "POST" });
    const j = await r.json();
    if (r.ok) addMsg("system", `Undid the last change (${j.reverted.slice(0, 7)}).`);
    else addMsg("system", `Nothing to undo.`);
  } catch (_) { addMsg("system", "Undo network error."); }
  refreshInbox();
});
```

- [ ] **Step 3: Extend the index-structure test**

In `tests/frontend/test_app.py`, the `test_index_served` test asserts marker strings. Add `'id="undo"'` to its marker list.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_app.py -k index -v`
Expected: PASS (`test_index_served` finds the `id="undo"` marker).

- [ ] **Step 5: Commit**

```bash
git add frontend/ui/index.html frontend/ui/app.js tests/frontend/test_app.py
git commit -m "feat(frontend): Undo last control in the chat UI"
```

---

### Task 4: README + manual smoke

**Files:** Modify `frontend/README.md`.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS (agenda + frontend, including the new versioning + wiring + UI tests).

- [ ] **Step 2: Document versioning + the separate-repo caveat**

Add a section to `frontend/README.md`:

```markdown
## Notes versioning & undo (ADR-0003)

The frontend versions the notes tree in git (the agent is sandboxed and cannot run
git itself). On startup it initialises `NOTES_ROOT` as **its own git repo** (committer
`Notes Assistant <notes@localhost>`); after each chat turn it commits any changes with
a `notes: <your prompt>` subject; the "Undo last" button (or `POST /api/undo`) reverts
the most recent commit.

**Important:** point `NOTES_ROOT` at a directory **outside this code repo** (e.g.
`~/cos-notes`). A nested `.git` inside `notes-mvp/sample-notes/` would make the code
repo stop tracking that fixture. History: `git -C "$NOTES_ROOT" log --oneline`.
```

- [ ] **Step 3: Manual smoke (run once, documented)**

With `NOTES_ROOT` pointed at a fresh dir outside the repo, start serve + app, send "Process the inbox", confirm `git -C "$NOTES_ROOT" log --oneline` shows a `notes: Process the inbox` commit, click "Undo last", confirm a new `Revert "notes: …"` commit appears and the change is gone. Record the result.

- [ ] **Step 4: Commit**

```bash
git add frontend/README.md
git commit -m "docs(frontend): notes versioning + undo, separate-repo caveat"
```

---

## Self-Review

**Spec coverage (design §8 / ADR-0003):**
- `notes/` is its own git repo, separate from the code repo → Task 1 (`ensure_repo`) + Task 4 caveat ✓
- Frontend commits after each agent operation (agent can't git) → Task 2 (`post_message` → `commit_all`, after the blocking turn) ✓
- Undo = revert → Task 1 (`revert_last`) + Task 2 (`/api/undo`) + Task 3 (UI) ✓
- Generic committer identity (no user-identity leak) → Task 1 (`_COMMITTER_*`) ✓
- Commit message mirrors the operation → `_subject(prompt)` → `notes: <prompt>` ✓

**Placeholder scan:** none — all code is complete. The one external assumption (the `_app(tmp_path, script=...)` helper from plan 4's `test_app.py`) is called out with an adaptation note; every git operation is concrete.

**Type/contract consistency:** `ensure_repo`/`commit_all`/`revert_last`/`is_repo`/`_subject`/`recent_subjects` signatures match across `versioning.py`, the app wiring, and the tests. `/api/message` now returns `{"ok", "committed"}` and `/api/undo` returns `{"ok", "reverted"}` / `{"ok": False, "error"}` — consistent between app and tests; the UI reads `j.reverted`.

**Out of scope (later):** per-ingest changelog → commit-message richness (currently the user's prompt is the subject; mapping the agent's structured changelog is a future nicety); branch/history browsing UI; conflict handling if the user hand-edits during a turn; the PowerShell launcher (N6) that starts serve+app; end-to-end integration smoke (N7). Markdown rendering and the per-turn file-context note remain deferred from N4.
