# Frontend — Chat UI, Notes Buttons & Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the browser chat UI for the Chief-of-Staff Notes assistant — an Open-WebUI-style page that streams the assistant turn over SSE, surfaces tool calls, offers one-click notes actions (process inbox / daily brief / weekly review), shows an inbox badge, and uploads documents (office→Markdown) into the notes tree.

**Architecture:** Two new backend endpoints on the existing FastAPI app (`POST /api/upload`, `GET /api/inbox`) plus a `GET /` that serves a static, dependency-free vanilla HTML/CSS/JS chat UI. The UI consumes the N3 contract: it opens `EventSource('/api/events')`, then `POST`s to `/api/message`, renders `message_delta`/`tool_call`/`done`/`error` events, and closes the stream on `done`. Upload storage+conversion lives in a small, injectable-converter module (`frontend/upload.py`) so it is unit-testable without real office files.

**Tech Stack:** Python 3.12 · FastAPI + uvicorn · `python-multipart` (FastAPI file uploads) · `markitdown` (office→Markdown) · vanilla HTML/CSS/JS (no framework, no CDN — offline). Backend endpoints TDD'd with httpx ASGITransport; UI verified by a page-structure test + a documented manual smoke.

**Scope note:** Plan **4 of 5** for Milestone 1 (design `mvp-chief-of-staff-notes-design.md` §7; plan WP **N4**; mirrors spec WP4/WP5 subset). Plans 1–3 merged on `main`. Follow-up: **plan 5 = N5** (frontend-owned `notes/` git versioning), then N6–N7 (launcher + integration).

**Consumes the N3 event contract (locked in plan 3 + bug-hunt):**
- `{"type":"message_delta","text":"<chunk>"}` — append to the current assistant bubble.
- `{"type":"tool_call","name":"agenda_today","status":"completed"}` — render a labeled chip.
- `{"type":"done"}` — finalise the turn, close the EventSource.
- `{"type":"error","kind":"upstream|busy","message":"<fixed text>"}` — render a system error line; on `busy`, the user must wait for the current turn. (`session_lost` is NOT an SSE kind — it surfaces as HTTP 503 from `POST /api/message`.)
- The proxy is **single-turn-at-a-time**: the UI disables the composer while a turn streams and re-enables on `done`/`error`.

**Security note (from the bug-hunt):** assistant text is rendered with `textContent` (never `innerHTML`) — the model output is untrusted. Rich Markdown rendering is deferred (would require a vendored sanitizer).

**Files:**
- Create: `frontend/upload.py` — `store_upload(notes_root, filename, data, convert)` storage+conversion.
- Modify: `frontend/app.py` — `GET /`, `POST /api/upload`, `GET /api/inbox`, static mount, `create_app(proxy, *, notes_root)`.
- Create: `frontend/ui/index.html`, `frontend/ui/app.js`, `frontend/ui/styles.css`.
- Modify: `frontend/pyproject.toml` (deps), `frontend/README.md`.
- Test: `tests/frontend/test_upload.py`, additions to `tests/frontend/test_app.py`.

---

### Task 0: Dependencies

**Files:** Modify `frontend/pyproject.toml`.

- [ ] **Step 1: Add the two runtime deps**

In `frontend/pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
    "httpx>=0.27,<1",
    "python-multipart>=0.0.9,<1",
    "markitdown>=0.0.1",
]
```

- [ ] **Step 2: Install + baseline**

```bash
cd /tmp/<worktree>            # the execution worktree
.venv/bin/pip install -e ./frontend
.venv/bin/python -c "import multipart, markitdown; print('deps ok')"
.venv/bin/pytest tests/ -q   # baseline green
```

- [ ] **Step 3: Commit**

```bash
git add frontend/pyproject.toml
git commit -m "feat(frontend): add python-multipart + markitdown for uploads"
```

---

### Task 1: Upload storage + conversion module

**Files:** Create `frontend/upload.py`; Test `tests/frontend/test_upload.py`.

- [ ] **Step 1: Write the failing tests**

`tests/frontend/test_upload.py`:

```python
from pathlib import Path

from frontend.upload import store_upload

CONVERT_EXTS = {".pdf", ".docx", ".pptx"}


def _fake_convert(data: bytes, suffix: str) -> str:
    return f"converted:{suffix}:{len(data)}"


def test_txt_stored_without_conversion(tmp_path):
    result = store_upload(tmp_path, "note.txt", b"hello", convert=_fake_convert)
    docs = tmp_path / "documents"
    assert (docs / "note.txt").read_bytes() == b"hello"
    assert not (docs / "note.txt.md").exists()
    assert result == {"stored": "documents/note.txt", "markdown": None}


def test_docx_stored_and_converted(tmp_path):
    result = store_upload(tmp_path, "deck.docx", b"\x50\x4b\x03\x04zip", convert=_fake_convert)
    docs = tmp_path / "documents"
    assert (docs / "deck.docx").exists()
    assert (docs / "deck.docx.md").read_text(encoding="utf-8") == "converted:.docx:7"
    assert result == {"stored": "documents/deck.docx", "markdown": "documents/deck.docx.md"}


def test_filename_is_sanitised(tmp_path):
    # path traversal / directory components stripped
    result = store_upload(tmp_path, "../../etc/passwd", b"x", convert=_fake_convert)
    docs = tmp_path / "documents"
    assert (docs / "passwd").exists()
    assert ".." not in result["stored"]


def test_empty_filename_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        store_upload(tmp_path, "", b"x", convert=_fake_convert)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_upload.py -v`
Expected: FAIL — `No module named 'frontend.upload'`.

- [ ] **Step 3: Implement**

`frontend/upload.py`:

```python
"""Store an uploaded document into the notes tree, converting office files to Markdown."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

CONVERT_EXTS = {".pdf", ".docx", ".pptx"}


def store_upload(
    notes_root: Path,
    filename: str,
    data: bytes,
    *,
    convert: Callable[[bytes, str], str],
) -> dict:
    """Store ``data`` under ``notes_root/documents/`` using a sanitised basename.

    For office files (.pdf/.docx/.pptx) also write a ``<name>.md`` sibling produced
    by ``convert(data, suffix)``. Returns repo-relative-ish paths under the notes tree.
    """
    base = os.path.basename(filename).strip()
    if not base:
        raise ValueError("upload filename is empty")
    docs = Path(notes_root) / "documents"
    docs.mkdir(parents=True, exist_ok=True)

    target = docs / base
    target.write_bytes(data)
    result = {"stored": f"documents/{base}", "markdown": None}

    suffix = target.suffix.lower()
    if suffix in CONVERT_EXTS:
        md = convert(data, suffix)
        md_path = docs / f"{base}.md"
        md_path.write_text(md, encoding="utf-8")
        result["markdown"] = f"documents/{base}.md"
    return result


def markitdown_convert(data: bytes, suffix: str) -> str:
    """Default converter: office bytes -> Markdown via markitdown (writes a temp file)."""
    import tempfile

    from markitdown import MarkItDown

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return MarkItDown().convert(tmp.name).text_content
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_upload.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/upload.py tests/frontend/test_upload.py
git commit -m "feat(frontend): document upload storage + office->md conversion (injectable converter)"
```

---

### Task 2: Backend endpoints — upload + inbox status

**Files:** Modify `frontend/app.py`; Test additions in `tests/frontend/test_app.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/frontend/test_app.py`:

```python
import httpx
import pytest

from frontend.app import create_app
from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy
from tests.frontend.fake_opencode import make_fake_opencode


def _app(tmp_path, script=None):
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode(script or [])),
                          base_url="http://oc"),
        agent="workspace-assistant",
    )
    return create_app(NotesProxy(oc), notes_root=tmp_path)


@pytest.mark.asyncio
async def test_inbox_counts_files(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.md").write_text("x", encoding="utf-8")
    (inbox / "b.md").write_text("y", encoding="utf-8")
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/inbox")
        assert r.json() == {"count": 2}


@pytest.mark.asyncio
async def test_inbox_zero_when_no_dir(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/inbox")).json() == {"count": 0}


@pytest.mark.asyncio
async def test_upload_stores_txt(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/upload", files={"file": ("n.txt", b"hello", "text/plain")})
        assert r.status_code == 200
        assert r.json() == {"stored": "documents/n.txt", "markdown": None}
        assert (tmp_path / "documents" / "n.txt").read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_index_served(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/")
        assert r.status_code == 200
        body = r.text
        for marker in ('id="chat"', 'id="composer"', 'id="send"', 'id="inbox-badge"',
                       'data-prompt', 'id="upload"', 'app.js'):
            assert marker in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_app.py -k "inbox or upload or index" -v`
Expected: FAIL — `create_app()` has no `notes_root` kwarg / routes 404.

- [ ] **Step 3: Implement the endpoints**

Rewrite `frontend/app.py` (keep the existing `/health`, `/api/message`, `/api/events`, `lifespan`, `MessageIn`, `SessionLost` handling; add the parts below):

```python
"""FastAPI app: the browser-facing API + static chat UI. The browser never reaches OpenCode."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from frontend.opencode_client import OpenCodeClient
from frontend.proxy import NotesProxy, SessionLost
from frontend.upload import markitdown_convert, store_upload

_UI_DIR = Path(__file__).resolve().parent / "ui"


class MessageIn(BaseModel):
    text: str


def create_app(proxy: NotesProxy, *, notes_root: Path | str = ".") -> FastAPI:
    notes_root = Path(notes_root)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await proxy.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/api/message")
    async def post_message(msg: MessageIn):
        try:
            await proxy.send(msg.text)
        except SessionLost:
            return JSONResponse(status_code=503, content={"ok": False, "error": "session lost"})
        return {"ok": True}

    @app.get("/api/events")
    async def events():
        async def gen():
            async for evt in proxy.relay():
                yield f"data: {json.dumps(evt)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/inbox")
    async def inbox():
        d = notes_root / "inbox"
        count = sum(1 for p in d.iterdir() if p.is_file()) if d.is_dir() else 0
        return {"count": count}

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        data = await file.read()
        try:
            result = store_upload(notes_root, file.filename or "", data, convert=markitdown_convert)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        return result

    @app.get("/")
    async def index():
        return FileResponse(_UI_DIR / "index.html")

    app.mount("/ui", StaticFiles(directory=_UI_DIR), name="ui")
    return app


def build_default_app() -> FastAPI:
    base = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
    notes_root = os.environ.get("NOTES_ROOT", ".")
    oc = OpenCodeClient.connect(base, agent="workspace-assistant")
    return create_app(NotesProxy(oc), notes_root=notes_root)
```

> Note: the `index()` route and the `/ui` mount require the `frontend/ui/` files (Task 3). Create Task 3's files in the same task as wiring if the index test fails for a missing file — or implement Task 3 first. The order below builds the endpoints (Task 2) then the assets (Task 3); run the full `test_app.py` after Task 3.

- [ ] **Step 4: Run the non-UI endpoint tests**

Run: `.venv/bin/pytest tests/frontend/test_app.py -k "inbox or upload" -v`
Expected: PASS (3 passed). (`test_index_served` needs Task 3's `index.html`.)

- [ ] **Step 5: Commit**

```bash
git add frontend/app.py tests/frontend/test_app.py
git commit -m "feat(frontend): upload + inbox endpoints, static UI mount, notes_root wiring"
```

---

### Task 3: The chat UI assets

**Files:** Create `frontend/ui/index.html`, `frontend/ui/styles.css`, `frontend/ui/app.js`.

- [ ] **Step 1: Create `frontend/ui/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chief-of-Staff Notes</title>
  <link rel="stylesheet" href="/ui/styles.css">
</head>
<body>
  <header>
    <h1>Chief-of-Staff Notes</h1>
    <span id="inbox-badge" class="badge" hidden>0 new</span>
  </header>

  <nav class="notes-buttons">
    <button class="action" data-prompt="Process the inbox.">Process inbox</button>
    <button class="action" data-prompt="Give me today's brief.">Daily brief</button>
    <button class="action" data-prompt="Run the weekly review.">Weekly review</button>
    <label class="upload-label">Upload
      <input id="upload" type="file" hidden>
    </label>
  </nav>

  <main id="chat" aria-live="polite"></main>

  <form id="composer">
    <textarea id="input" rows="2" placeholder="Message…"></textarea>
    <button id="send" type="submit">Send</button>
  </form>

  <script src="/ui/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `frontend/ui/styles.css`**

```css
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; }
header { display: flex; align-items: center; gap: .75rem; padding: .5rem 1rem; border-bottom: 1px solid #ddd; }
header h1 { font-size: 1rem; margin: 0; }
.badge { background: #e44; color: #fff; border-radius: 1rem; padding: .1rem .5rem; font-size: .8rem; }
.notes-buttons { display: flex; gap: .5rem; padding: .5rem 1rem; border-bottom: 1px solid #eee; align-items: center; }
.notes-buttons button, .upload-label { font: inherit; padding: .3rem .7rem; border: 1px solid #ccc; border-radius: .4rem; background: #f7f7f7; cursor: pointer; }
#chat { flex: 1; overflow-y: auto; padding: 1rem; display: flex; flex-direction: column; gap: .75rem; }
.msg { max-width: 70ch; padding: .5rem .75rem; border-radius: .6rem; white-space: pre-wrap; }
.msg.user { align-self: flex-end; background: #2563eb; color: #fff; }
.msg.assistant { align-self: flex-start; background: #f1f1f1; }
.msg.system { align-self: center; font-size: .85rem; color: #a00; }
.tool { align-self: flex-start; font-size: .8rem; color: #555; background: #eef; border-radius: 1rem; padding: .1rem .6rem; }
#composer { display: flex; gap: .5rem; padding: .75rem 1rem; border-top: 1px solid #ddd; }
#input { flex: 1; font: inherit; padding: .4rem; resize: vertical; }
#composer button { font: inherit; padding: 0 1rem; }
#composer[aria-disabled="true"] { opacity: .5; pointer-events: none; }
```

- [ ] **Step 3: Create `frontend/ui/app.js`**

```javascript
"use strict";
const chat = document.getElementById("chat");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const badge = document.getElementById("inbox-badge");
const upload = document.getElementById("upload");

function addMsg(kind, text) {
  const el = document.createElement("div");
  el.className = "msg " + kind;
  el.textContent = text;                 // textContent: untrusted model output, no HTML
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}
function addTool(name, status) {
  const el = document.createElement("div");
  el.className = "tool";
  el.textContent = `🔧 ${name} — ${status}`;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}
function setBusy(b) { composer.setAttribute("aria-disabled", b ? "true" : "false"); }

async function refreshInbox() {
  try {
    const r = await fetch("/api/inbox");
    const { count } = await r.json();
    badge.hidden = count === 0;
    badge.textContent = `${count} new`;
  } catch (_) { /* non-fatal */ }
}

// One turn: open SSE first, then POST the message; render until `done`.
function runTurn(text) {
  setBusy(true);
  addMsg("user", text);
  let bubble = null;
  const es = new EventSource("/api/events");
  const finish = () => { es.close(); setBusy(false); refreshInbox(); };

  es.onopen = () => {
    fetch("/api/message", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => {
      if (!r.ok) { addMsg("system", "Could not start the turn (session lost)."); finish(); }
    }).catch(() => { addMsg("system", "Network error."); finish(); });
  };

  es.onmessage = (e) => {
    let evt;
    try { evt = JSON.parse(e.data); } catch (_) { return; }
    if (evt.type === "message_delta") {
      if (!bubble) bubble = addMsg("assistant", "");
      bubble.textContent += evt.text;
      chat.scrollTop = chat.scrollHeight;
    } else if (evt.type === "tool_call") {
      addTool(evt.name, evt.status);
    } else if (evt.type === "error") {
      addMsg("system", `Error (${evt.kind}): ${evt.message}`);
      finish();
    } else if (evt.type === "done") {
      finish();
    }
  };
  es.onerror = () => { addMsg("system", "Connection lost."); finish(); };
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || composer.getAttribute("aria-disabled") === "true") return;
  input.value = "";
  runTurn(text);
});

document.querySelectorAll(".action").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (composer.getAttribute("aria-disabled") === "true") return;
    runTurn(btn.dataset.prompt);
  });
});

upload.addEventListener("change", async () => {
  const file = upload.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  addMsg("system", `Uploading ${file.name}…`);
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (r.ok) addMsg("system", `Stored ${j.stored}${j.markdown ? " (+ Markdown)" : ""}.`);
    else addMsg("system", `Upload failed: ${j.error || r.status}.`);
  } catch (_) { addMsg("system", "Upload network error."); }
  upload.value = "";
});

refreshInbox();
```

- [ ] **Step 4: Run the full app test (index now served)**

Run: `.venv/bin/pytest tests/frontend/test_app.py -v`
Expected: PASS — including `test_index_served`.

- [ ] **Step 5: Commit**

```bash
git add frontend/ui/
git commit -m "feat(frontend): Open-WebUI-style chat UI — streaming, tool chips, notes buttons, upload, inbox badge"
```

---

### Task 4: Manual smoke + README

**Files:** Modify `frontend/README.md`.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS (agenda + frontend, including the new upload/inbox/index tests).

- [ ] **Step 2: Manual UI smoke (documented; run once)**

Start a real serve + the app (against the fast A3B model), open the browser, and verify the checklist. Add this section to `frontend/README.md`:

```markdown
## Chat UI (manual smoke)

1. One-time: `pip install -e ./frontend` (pulls python-multipart + markitdown).
2. Start OpenCode from the notes dir and the app pointed at it:

       cd notes-mvp/sample-notes
       opencode serve --hostname 127.0.0.1 --port 4096 &
       OPENCODE_BASE_URL=http://127.0.0.1:4096 NOTES_ROOT="$PWD" \
         "$(git rev-parse --show-toplevel)/.venv/bin/uvicorn" \
         --factory frontend.app:build_default_app --port 8000

3. Open http://127.0.0.1:8000/ and verify:
   - Typing a message + Send streams the assistant reply token-by-token; the
     composer disables while streaming and re-enables on completion.
   - "Daily brief" button streams a brief and a `agenda_today` tool chip appears.
   - Uploading a .docx/.pdf shows "Stored documents/…(+ Markdown)" and the file
     lands in `notes-mvp/sample-notes/documents/`.
   - The inbox badge shows the count of files in `inbox/` (drop a file there and
     reload, or click Process inbox).
   - A second action while a turn is streaming is ignored (single-turn).

Assistant text is rendered as plain text (untrusted-output safety); Markdown
styling is a future enhancement.
```

- [ ] **Step 3: Commit**

```bash
git add frontend/README.md
git commit -m "docs(frontend): chat UI run + manual smoke instructions"
```

---

## Self-Review

**Spec coverage (design §7):**
- Open-WebUI-style chat, streaming, visible tool calls → Task 3 (`runTurn`, `addTool`) ✓
- Inbox status + Process-inbox / Daily-brief / Weekly-review buttons → Task 2 (`/api/inbox`) + Task 3 (`.action[data-prompt]`, `refreshInbox`) ✓
- Upload with office→Markdown into `documents/` → Tasks 1+2 (`store_upload`, `/api/upload`) ✓
- Consumes the N3 contract incl. `error` kinds + single-turn (composer disabled while streaming) → Task 3 ✓
- Per-ingest changelog: the agent's changelog is plain assistant text and renders in the chat; an inbox refresh fires after each turn (`finish → refreshInbox`) ✓

**Placeholder scan:** every code/asset block is complete; the UI is dependency-free. The one ordering caveat (Task 2 `index()` needs Task 3 files) is called out explicitly with the run order, not left implicit. `markitdown` conversion is exercised in tests via an injected fake converter (no real office file needed); the real `markitdown_convert` is covered by the Task-4 manual smoke.

**Type/contract consistency:** `create_app(proxy, *, notes_root)` is used identically in tests, `build_default_app`, and the UI test helper. `store_upload(notes_root, filename, data, *, convert)` returns `{"stored","markdown"}` consistently across `upload.py`, the `/api/upload` endpoint, and `app.js`. The event types consumed by `app.js` (`message_delta`/`tool_call`/`done`/`error`) match the N3 contract verbatim.

**Out of scope (later):** frontend-owned `notes/` git versioning (N5, plan 5); launcher that starts serve+app together (N6); rich Markdown rendering with a vendored sanitizer; the per-turn "file available" note injected into the agent's context (design §5.4 — deferred; upload currently just stores + the user references the file in chat). Full browser E2E (Playwright) — deferred; the UI is covered by a page-structure test + the manual smoke.
```
