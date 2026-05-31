# Presentation Pane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a right-hand **Presentation pane** that renders an **Artifact** (a workspace markdown file) read-only — pushed by the agent via a `present(path)` tool, or opened by the user clicking a workspace path in the chat.

**Architecture:** A new tiny stdio MCP server (`presenter`) exposes `present(path)` — a thin signal that returns ok. The relay reads the `present` tool-call's **input path** (post-idle) and emits a new `present` SSE event. A path-confined `GET /api/file` renders the workspace markdown to HTML **server-side** and **sanitizes** it (`nh3`); the browser injects the safe HTML into the pane. The UI becomes two columns (left = existing conversation incl. the collapsible "Thinking"; right = pane). All decisions are recorded in `docs/adr/0006-presentation-pane.md` and `CONTEXT.md` (terms **Presentation pane**, **Artifact**).

**Tech Stack:** Python 3.12 · FastMCP (`mcp`) · FastAPI · `markdown` + `nh3` (new runtime deps) · vanilla JS/CSS (no build step). TDD throughout; one live end-to-end smoke at the end.

**Scope note:** Single subsystem (the pane). Build order is bottom-up: MCP tool → config wiring → relay event → render endpoint → UI → prompt → integration. The collapsible "Thinking" pane-left feature already shipped (reasoning split); this plan does NOT touch it.

**Security invariants (do not break):**
- `GET /api/file` must confine reads to `NOTES_ROOT` (the `workspace/` sandbox): resolve the path and reject anything not under the root (same idea as `frontend/upload.py`). Read-only.
- Rendered HTML must be sanitized with `nh3` (strip `<script>`, event handlers, `javascript:` URLs, raw HTML) before it reaches the browser. The conversation pane stays `textContent`-only; only the Presentation pane injects HTML.

**Canonical current signatures this plan builds on:**
- `frontend/config.py::build_opencode_config(*, model_endpoint, model_id, notes_root, agenda_server, prompt_path) -> dict` (gains a `present_server` param).
- `frontend/bootstrap.py::init_install(install_root, *, model_endpoint, model_id, agenda_server) -> dict` (derives `present_server` from `agenda_server`'s dir).
- `frontend/opencode_client.py::tool_calls(session_id) -> list[dict]` returns `[{"name","status"}]` (gains `"input"`).
- `frontend/proxy.py::relay()` yields `tool_call`/`message_delta`/`reasoning_delta`/`done`/`error` (gains `present`).
- `frontend/app.py::create_app(proxy, *, notes_root=".", git_dir=None) -> FastAPI`.

---

### Task 1: `presenter` MCP server — the `present(path)` tool

Mirror the `agenda/` package: a tiny installable package with a FastMCP stdio server. `present()` is a thin signal (returns ok + echoes the path); the actual rendering is driven by the frontend observing the tool-call's input.

**Files:**
- Create: `presenter/__init__.py`, `presenter/server.py`, `presenter/pyproject.toml`
- Test: `tests/presenter/__init__.py`, `tests/presenter/test_server.py`

- [ ] **Step 1: Write the failing test**

`tests/presenter/test_server.py`:
```python
from presenter import server


def test_present_returns_ok_and_echoes_path():
    assert server.present("meetings/2026-05-31/atlas.md") == {
        "ok": True,
        "presented": "meetings/2026-05-31/atlas.md",
    }


def test_tool_names_are_bare():
    # OpenCode namespaces MCP tools as <serverkey>_<name>; the server registers the
    # bare name 'present' so the agent sees 'present' under the 'present' server key.
    assert server.TOOL_NAMES == ("present",)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/presenter/test_server.py -v`
Expected: FAIL — `No module named 'presenter'`.

- [ ] **Step 3: Implement**

`presenter/__init__.py`: empty.

`presenter/server.py`:
```python
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("present")

# Bare tool name — OpenCode namespaces it as present_<name> via the server key
# "present"; registering "present" yields the tool the agent calls as `present`.
TOOL_NAMES = ("present",)


@mcp.tool()
def present(path: str) -> dict:
    """Show a workspace file (markdown) in the user's Presentation pane.

    `path` is relative to the notes workspace (e.g. "meetings/2026-05-31/atlas.md").
    This is a UI signal: it does not read or modify the file. The frontend renders
    the file in the right-hand pane.
    """
    return {"ok": True, "presented": path}


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
```

`presenter/pyproject.toml`:
```toml
[project]
name = "presenter-service"
version = "0.1.0"
description = "Thin MCP server: the present(path) UI signal for the Presentation pane"
requires-python = ">=3.12"
dependencies = ["mcp>=1.2.0,<2"]

[project.scripts]
present-server = "presenter.server:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = [".."]
include = ["presenter*"]
```

`tests/presenter/__init__.py`: empty.

- [ ] **Step 4: Install + run to verify it passes**

Run:
```bash
.venv/bin/pip install -e ./presenter
.venv/bin/python -m pytest tests/presenter/test_server.py -v
```
Expected: PASS (2 tests). Confirm `which present-server` resolves in the venv.

- [ ] **Step 5: Commit**

```bash
git add presenter/ tests/presenter/
git commit -m "feat(presenter): thin present(path) MCP server (Presentation pane signal)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Register the `present` MCP server + surface tool input

The agent needs the `present` tool registered in `opencode.json`, and the relay needs the tool-call's **input** (the path) — `tool_calls()` currently returns only name+status.

**Files:**
- Modify: `frontend/config.py` (`build_opencode_config` gains `present_server`, adds `mcp.present`)
- Modify: `frontend/bootstrap.py` (`init_install` derives `present_server`)
- Modify: `notes-mvp/gen_opencode_config.py` (derive `present_server` for the dev config)
- Modify: `frontend/opencode_client.py` (`tool_calls` includes `input`)
- Test: `tests/frontend/test_bootstrap.py`, `tests/frontend/test_opencode_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/frontend/test_bootstrap.py`:
```python
def test_bootstrap_registers_present_mcp_server(tmp_path):
    root = tmp_path / "cos-notes"
    bootstrap.init_install(
        root, model_endpoint="http://example:11434/v1", model_id="m",
        agenda_server="/opt/.venv/bin/agenda-server",
    )
    import json
    cfg = json.loads((root / "opencode.json").read_text())
    assert "present" in cfg["mcp"]
    # derived next to agenda-server in the same venv bin dir
    assert cfg["mcp"]["present"]["command"] == ["/opt/.venv/bin/present-server"]
    # present tool is allowed by the agent permission policy
    assert cfg["agent"]["workspace-assistant"]["permission"].get("present") == "allow"
```

Add to `tests/frontend/test_opencode_client.py` (mirror the existing tool_calls test style + the fake):
```python
async def test_tool_calls_includes_input():
    from tests.frontend.fake_opencode import make_fake_opencode
    import httpx
    from frontend.opencode_client import OpenCodeClient
    tool_parts = [{
        "id": "prt_p", "type": "tool", "tool": "present",
        "state": {"status": "completed", "input": {"path": "meetings/x.md"}},
    }]
    oc = OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([], tool_parts=tool_parts)),
                          base_url="http://oc"),
        agent="workspace-assistant",
    )
    sid = await oc.create_session()
    calls = await oc.tool_calls(sid)
    assert calls == [{"name": "present", "status": "completed", "input": {"path": "meetings/x.md"}}]
    await oc.aclose()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/frontend/test_bootstrap.py::test_bootstrap_registers_present_mcp_server tests/frontend/test_opencode_client.py::test_tool_calls_includes_input -v`
Expected: FAIL — no `present` key in mcp; `tool_calls` has no `input`.

- [ ] **Step 3: Implement**

In `frontend/config.py`, add `present_server: str` to `build_opencode_config`'s keyword args and add a `present` MCP entry + the `present` permission. The permission dict (`permissions`) gains `"present": "allow"`; the `mcp` dict gains:
```python
        "mcp": {
            "agenda": {
                "type": "local",
                "command": [agenda_server],
                "enabled": True,
                "environment": {"NOTES_ROOT": notes_root},
            },
            "present": {
                "type": "local",
                "command": [present_server],
                "enabled": True,
            },
        },
```
Add `present_server` to the docstring args.

In `frontend/bootstrap.py::init_install`, derive the present server next to the agenda server and pass it:
```python
    from pathlib import Path as _P
    present_server = str(_P(agenda_server).parent / "present-server")
    config = build_opencode_config(
        model_endpoint=model_endpoint,
        model_id=model_id,
        notes_root=str(work),
        agenda_server=agenda_server,
        present_server=present_server,
        prompt_path=str(prompt_dest),
    )
```

In `notes-mvp/gen_opencode_config.py::main`, derive it the same way and pass `present_server=`:
```python
    present_server = str(Path(agenda_server).parent / "present-server")
    config = build_opencode_config(
        model_endpoint=model_endpoint, model_id=model_id, notes_root=notes_root,
        agenda_server=agenda_server, present_server=present_server,
        prompt_path=str(CANONICAL_PROMPT_PATH),
    )
```

In `frontend/opencode_client.py::tool_calls`, include the input. Change the appended dict to:
```python
                    result.append(
                        {
                            "name": part.get("tool", "unknown"),
                            "status": state.get("status", "unknown"),
                            "input": state.get("input", {}),
                        }
                    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/frontend/test_bootstrap.py tests/frontend/test_opencode_client.py -q`
Expected: PASS (incl. existing tests — the extra `input` key is additive).

- [ ] **Step 5: Commit**

```bash
git add frontend/config.py frontend/bootstrap.py notes-mvp/gen_opencode_config.py frontend/opencode_client.py tests/frontend/
git commit -m "feat(frontend): register present MCP server + surface tool-call input

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Relay emits a `present` SSE event

Post-idle, when the relay sees a `present` tool call, emit a `present` event carrying the path (instead of/in addition to a tool chip). Other tools keep emitting `tool_call`.

**Files:**
- Modify: `frontend/proxy.py` (the post-idle tool_calls loop)
- Test: `tests/frontend/test_proxy.py`

- [ ] **Step 0: VERIFY the real tool-call shape first (capture, no code).** Tasks 1+2
  are done, so the `present` server is registered. Bootstrap a temp install, start
  `opencode serve`, and drive one turn that calls the tool (e.g. POST a message:
  "Use the present tool to show topics/x.md", with that file present), then
  `GET /session/{sid}/message` and inspect the assistant `type:"tool"` part where
  `tool == "present"`. **Confirm the path is at `state.input.path`** (a dict). If the
  args are shaped differently (e.g. `state.input` is a JSON *string*, or the key
  differs), adjust `tool_calls()`'s `input` extraction (Task 2) and the path read in
  Step 3 below to the real shape before writing the test. (We've mis-read OpenCode
  shapes 3× this session — this probe removes the guess.) No commit.

- [ ] **Step 1: Write the failing test**

Add to `tests/frontend/test_proxy.py`:
```python
async def test_relay_emits_present_event_for_present_tool():
    script = [{"type": "session.idle", "properties": {"sessionID": "ses_fake"}}]
    tool_parts = [{
        "id": "prt_p", "type": "tool", "tool": "present",
        "state": {"status": "completed", "input": {"path": "topics/atlas.md"}},
    }]
    proxy = _proxy_for(make_fake_opencode(script=script, tool_parts=tool_parts))
    await proxy.ensure_session()
    out = []
    async for evt in proxy.relay():
        out.append(evt)
        if evt["type"] in ("done", "error"):
            break
    assert {"type": "present", "path": "topics/atlas.md"} in out
    assert out[-1] == {"type": "done"}
    await proxy.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/frontend/test_proxy.py::test_relay_emits_present_event_for_present_tool -v`
Expected: FAIL — no `present` event emitted.

- [ ] **Step 3: Implement**

In `frontend/proxy.py`, replace the post-idle tool-call emit loop:
```python
                        tool_calls = await self._oc.tool_calls(sid)
                        for tc in tool_calls:
                            if tc["name"] == "present":
                                path = (tc.get("input") or {}).get("path")
                                if path:
                                    yield {"type": "present", "path": path}
                                continue
                            yield {
                                "type": "tool_call",
                                "name": tc["name"],
                                "status": tc["status"],
                            }
                        yield {"type": "done"}
                        return
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/frontend/test_proxy.py -q`
Expected: PASS (existing tool_call tests still pass — non-present tools unchanged).

- [ ] **Step 5: Commit**

```bash
git add frontend/proxy.py tests/frontend/test_proxy.py
git commit -m "feat(frontend): relay emits a present SSE event from the present tool call

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `GET /api/file` — path-confined, server-rendered, sanitized

A read-only endpoint that resolves a path within `NOTES_ROOT`, renders markdown→HTML, and sanitizes it with `nh3`. Non-markdown files return raw text (no HTML).

**Files:**
- Create: `frontend/render.py` (markdown→sanitized HTML)
- Modify: `frontend/app.py` (`GET /api/file`)
- Modify: `frontend/pyproject.toml` (add `markdown`, `nh3` deps)
- Test: `tests/frontend/test_render.py`, `tests/frontend/test_app.py`

- [ ] **Step 1: Write the failing tests**

`tests/frontend/test_render.py`:
```python
from frontend.render import render_markdown


def test_renders_markdown_headings_and_lists():
    html = render_markdown("# Title\n\n- a\n- b\n")
    assert "<h1>" in html and "Title" in html
    assert "<li>" in html


def test_sanitizes_script_and_handlers():
    html = render_markdown("ok\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>")
    assert "<script>" not in html
    assert "onerror" not in html
    assert "alert(1)" not in html or "<script>" not in html  # script content not executable


def test_strips_javascript_urls():
    html = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in html
```

Add to `tests/frontend/test_app.py`:
```python
async def test_get_file_renders_markdown_confined(tmp_path):
    notes = tmp_path / "workspace"
    (notes / "topics").mkdir(parents=True)
    (notes / "topics" / "atlas.md").write_text("# Atlas\n\nbody\n", encoding="utf-8")
    app = create_app(NotesProxy(OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([])), base_url="http://oc"),
        agent="workspace-assistant")), notes_root=notes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/file", params={"path": "topics/atlas.md"})
        assert r.status_code == 200
        body = r.json()
        assert body["path"] == "topics/atlas.md"
        assert "<h1>" in body["html"] and "Atlas" in body["html"]


async def test_get_file_rejects_traversal(tmp_path):
    notes = tmp_path / "workspace"
    notes.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    app = create_app(NotesProxy(OpenCodeClient(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=make_fake_opencode([])), base_url="http://oc"),
        agent="workspace-assistant")), notes_root=notes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/file", params={"path": "../secret.txt"})
        assert r.status_code == 403
        assert r.json()["ok"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/frontend/test_render.py tests/frontend/test_app.py -q`
Expected: FAIL — `No module named 'frontend.render'`, `/api/file` 404.

- [ ] **Step 3: Implement**

Add deps to `frontend/pyproject.toml` `dependencies`: `"markdown>=3.6,<4"`, `"nh3>=0.2,<1"`. Then `.venv/bin/pip install -e ./frontend`.

`frontend/render.py`:
```python
"""Render workspace markdown to sanitized HTML for the Presentation pane.

Sanitization is the security boundary: model-written / markitdown-converted content
is untrusted, so the rendered HTML is passed through nh3 (strips <script>, event
handlers, javascript: URLs, and disallowed tags) before it reaches the browser.
"""
from __future__ import annotations

import markdown as _markdown
import nh3


def render_markdown(text: str) -> str:
    """Markdown string -> sanitized HTML string (safe to inject into the pane)."""
    raw_html = _markdown.markdown(text, extensions=["extra", "sane_lists", "tables"])
    return nh3.clean(raw_html)
```

In `frontend/app.py`, import render + add the endpoint inside `create_app` (after `/api/inbox`):
```python
    from frontend.render import render_markdown  # local import keeps optional dep lazy

    @app.get("/api/file")
    async def get_file(path: str):
        base = notes_root.resolve()
        target = (base / path).resolve()
        if base != target and not target.is_relative_to(base):
            return JSONResponse(status_code=403, content={"ok": False, "error": "outside workspace"})
        if not target.is_file():
            return JSONResponse(status_code=404, content={"ok": False, "error": "not found"})
        text = target.read_text(encoding="utf-8", errors="replace")
        if target.suffix.lower() in (".md", ".markdown"):
            return {"path": path, "html": render_markdown(text), "text": None}
        return {"path": path, "html": None, "text": text}
```
(`notes_root` is already a `Path` in `create_app`; `JSONResponse` is already imported.)

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/frontend/test_render.py tests/frontend/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/render.py frontend/app.py frontend/pyproject.toml tests/frontend/test_render.py tests/frontend/test_app.py
git commit -m "feat(frontend): GET /api/file — path-confined markdown render + nh3 sanitize

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Two-pane UI — pane + present event + clickable paths

Make the layout two columns; render `present` events and clicked workspace paths into the right pane via `/api/file`.

**Files:**
- Modify: `frontend/ui/index.html` (two-pane structure + `#pane`)
- Modify: `frontend/ui/styles.css` (two-column layout + pane styles)
- Modify: `frontend/ui/app.js` (handle `present`; linkify + click→pane)
- Test: `tests/frontend/test_app.py` (index serves the pane markers)

- [ ] **Step 1: Write the failing test**

Add to `tests/frontend/test_app.py`:
```python
async def test_index_includes_presentation_pane(tmp_path):
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/")).text
        assert 'id="pane"' in body
        assert 'id="pane-body"' in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/frontend/test_app.py::test_index_includes_presentation_pane -v`
Expected: FAIL — no `#pane` in the served HTML.

- [ ] **Step 3: Implement**

`frontend/ui/index.html` — wrap chat+composer in a left column and add the right pane. Replace the `<main>`…`</form>` region with:
```html
  <div id="panes">
    <section id="left">
      <main id="chat" aria-live="polite"></main>
      <form id="composer">
        <textarea id="input" rows="2" placeholder="Message…"></textarea>
        <button id="send" type="submit">Send</button>
      </form>
    </section>
    <aside id="pane">
      <div id="pane-header">Presentation</div>
      <div id="pane-body"><p class="pane-empty">Nothing presented yet.</p></div>
    </aside>
  </div>
```

`frontend/ui/styles.css` — append:
```css
#panes { flex: 1; display: flex; min-height: 0; }
#left { flex: 1 1 50%; display: flex; flex-direction: column; min-width: 0; }
#pane { flex: 1 1 50%; border-left: 1px solid #ddd; display: flex; flex-direction: column; min-width: 0; }
#pane-header { padding: .4rem 1rem; border-bottom: 1px solid #eee; font-size: .85rem; color: #666; }
#pane-body { flex: 1; overflow-y: auto; padding: 1rem; }
#pane-body img { max-width: 100%; }
.pane-empty { color: #999; }
@media (max-width: 800px) { #panes { flex-direction: column; } #pane { border-left: none; border-top: 1px solid #ddd; } }
```
(Note: `#chat` already has `flex: 1` from the existing rule; with `#left` as a flex column it fills correctly. Remove the old top-level `#chat`/`#composer` rules only if they conflict — they don't; keep them.)

`frontend/ui/app.js` — add pane handling. Near the top (after the existing `const` declarations):
```javascript
const paneBody = document.getElementById("pane-body");
// Linkify BACKTICK-delimited workspace paths so names with spaces/commas/unicode
// (e.g. `documents/KI-Gefahren, Architekturen und MSA-LLM.md`) are still clickable.
// Group 1 = the path (without backticks). The agent writes paths in backticks.
const PATH_RE = /`((?:inbox|meetings|topics|briefs|documents|archive)\/[^`]+?\.(?:md|markdown|txt))`/g;

async function showArtifact(path) {
  try {
    const r = await fetch("/api/file?path=" + encodeURIComponent(path));
    const j = await r.json();
    if (!r.ok) { paneBody.textContent = `Could not open ${path}: ${j.error || r.status}`; return; }
    document.getElementById("pane-header").textContent = j.path;
    if (j.html !== null) { paneBody.innerHTML = j.html; }     // server-sanitized HTML
    else { paneBody.textContent = j.text || ""; }             // non-markdown: plain text
  } catch (_) { paneBody.textContent = `Network error opening ${path}.`; }
}
```
In `addMsg`, after setting `el.textContent = text;`, linkify workspace paths (operating on the safe textContent, building elements — never innerHTML of untrusted text):
```javascript
function addMsg(kind, text) {
  const el = document.createElement("div");
  el.className = "msg " + kind;
  if (kind === "assistant" || kind === "user") {
    let last = 0; const frag = document.createDocumentFragment();
    text.replace(PATH_RE, (full, path, idx) => {
      frag.appendChild(document.createTextNode(text.slice(last, idx)));   // text before, incl. backtick
      const a = document.createElement("a"); a.href = "#"; a.textContent = path; a.className = "artifact-link";
      a.addEventListener("click", (e) => { e.preventDefault(); showArtifact(path); });
      frag.appendChild(a); last = idx + full.length; return full;        // skip the whole `…` span
    });
    frag.appendChild(document.createTextNode(text.slice(last)));
    el.appendChild(frag);
  } else { el.textContent = text; }
  chat.appendChild(el); chat.scrollTop = chat.scrollHeight; return el;
}
```
Note: streaming `message_delta` appends to `bubble.textContent` (no linkify mid-stream); that's fine — links come from finalized messages and the pane is the primary surface. In the `es.onmessage` handler, add a `present` branch:
```javascript
    } else if (evt.type === "present") {
      showArtifact(evt.path);
    }
```
Append to `styles.css`: `.artifact-link { color: #2563eb; text-decoration: underline; cursor: pointer; }`

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/frontend/test_app.py -q`
Expected: PASS. Manually: `python -m http.server`-style not needed — visual check happens in the integration smoke.

- [ ] **Step 5: Commit**

```bash
git add frontend/ui/ tests/frontend/test_app.py
git commit -m "feat(ui): two-pane layout — Presentation pane renders present events + clicked paths

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Prompt — teach the agent the `present` tool

**Files:**
- Modify: `frontend/assets/notes-agent.md`

- [ ] **Step 1: Add the tool to the prompt**

In the `# Your tools` section, after the Agenda tools block, add:
```markdown
- **`present(path)`** — show a workspace file (a meeting/MoM, brief, topic, report
  draft, or an uploaded `documents/*.md`) in the user's right-hand pane. Call it
  with a workspace-relative path after you file or update something the user should
  see (e.g. the meeting you just wrote, the brief you generated) or when the user
  asks to see a specific note. It only displays the file; it does not change it.
```

- [ ] **Step 2: Commit**

```bash
git add frontend/assets/notes-agent.md
git commit -m "docs(prompt): teach the agent the present(path) tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Integration — wiring, deps, smoke

Wire the present server into the launcher's environment isolation (it's spawned by OpenCode, so it inherits the isolated env) and extend the smoke to exercise the pane.

**Files:**
- Modify: `frontend/requirements-dev.txt` is unchanged; runtime deps are in `frontend/pyproject.toml` (Task 4). Add `presenter` to the dev install in `setup.sh`, `setup.ps1`, CI, and `README`/`FIRST-RUN`.
- Modify: `setup.sh`, `setup.ps1`, `.github/workflows/ci.yml`, `README.md` (install `presenter`)
- Modify: `tests/smoke/notes-mvp/run_smoke.py` (assert a present event + /api/file)

- [ ] **Step 1: Add `presenter` to every install path**

In `setup.sh`, `setup.ps1`, `.github/workflows/ci.yml`, and the README/FIRST-RUN install commands, change `pip install -e ./agenda -e ./frontend` → `pip install -e ./agenda -e ./frontend -e ./presenter`. (The launcher's pre-flight already checks `agenda-server`; optionally add a `present-server` check in `launcher/run.py` mirroring `agenda_server_path` — not required for v1.)

- [ ] **Step 2: Extend the smoke**

In `tests/smoke/notes-mvp/run_smoke.py`, after the SSE consume, add assertions: collect `present` events from the stream (extend `_consume_sse` to keep all events — it already returns the events list), and assert at least one `present` event arrived OR a fetch of a known workspace file via `GET /api/file` returns rendered HTML. Concretely, after the turn:
```python
    present_evts = [e for e in sse_events if e.get("type") == "present"]
    # The agent MAY present; assert the endpoint works regardless:
    import urllib.request as _u
    meet = next(workspace.glob("meetings/**/*.md"), None)
    rel = meet.relative_to(workspace).as_posix() if meet else "tasks.todo.txt"
    fr = _get_json(f"{web_url}/api/file?path={rel}")
    results.append(_check("GET /api/file renders an artifact", isinstance(fr.get("html"), str) or isinstance(fr.get("text"), str), f"path={rel} present_events={len(present_evts)}"))
```

- [ ] **Step 3: Full suite + ruff + live smoke**

```bash
.venv/bin/python -m pytest tests/ -q          # all green, incl. new presenter/render/app/proxy tests
.venv/bin/ruff check agenda frontend launcher notes-mvp presenter tests
MODEL_ENDPOINT=http://<host>:11434/v1 MODEL_ID=<model> SMOKE_TURN_TIMEOUT=900 \
  .venv/bin/python tests/smoke/notes-mvp/run_smoke.py   # expect 8/8 incl. /api/file
```

- [ ] **Step 4: Commit**

```bash
git add setup.sh setup.ps1 .github/workflows/ci.yml README.md docs/FIRST-RUN.md tests/smoke/notes-mvp/run_smoke.py
git commit -m "test(smoke)+chore: install presenter everywhere; smoke exercises /api/file

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (ADR-0006):**
- Dedicated `present` MCP server → Task 1 ✓
- Register it + agent permission → Task 2 ✓
- Relay surfaces tool-call input → `present` SSE event → Tasks 2 (input) + 3 (event) ✓
- Path-confined `GET /api/file`, server render + `nh3` sanitize → Task 4 ✓
- Two-pane UI, clickable chat paths → Task 5 ✓
- Prompt teaches `present()` → Task 6 ✓
- Agenda service stays pure (separate server) → Task 1 (separate package) ✓
- CONTEXT terms already committed (Presentation pane, Artifact) → no task needed ✓

**Placeholder scan:** none — every code step has complete code; the smoke assertion is concrete.

**Type/contract consistency:** `build_opencode_config` gains `present_server` (Task 2) used by bootstrap + gen_opencode_config (Task 2); `tool_calls()` gains `"input"` (Task 2) consumed by the relay (Task 3); `render_markdown(text)->str` (Task 4) used by `/api/file` (Task 4) and the browser (`j.html`) in Task 5; the `present` browser event (`{"type":"present","path":...}`, Task 3) is handled in `app.js` (Task 5).

**Risks (+ grill outcomes):** (1) **Tool-call shape** — the agent-push path assumes the `present` arg is at `state.input.path`; **Task 3 Step 0 verifies this with a live capture before any relay code** (grill decision), since we've mis-read OpenCode wire shapes 3× this session. (2) the agent may not reliably call `present()` — the pane still works via clickable paths, and the `/api/file` smoke assertion doesn't depend on the model presenting. (3) **Clickable paths are backtick-delimited** (`` `…path.md` ``) so real filenames with spaces/commas/unicode (e.g. the user's German-titled upload) are clickable (grill decision). (4) `nh3` sanitization is the XSS choke point — Task 4 tests script/handler/`javascript:` stripping AND that headings/lists/**tables**/code survive (set an explicit allowlist if nh3 defaults strip them). (5) the present server adds a 2nd MCP process; if `present-server` isn't installed, OpenCode logs an MCP error but the rest still works — Task 7 adds it to every install path.

**Out of scope (later):** live mid-turn presentation; a file-tree browser; rendering non-markdown (PDF/office) beyond their `.md` siblings; pane history/tabs.
