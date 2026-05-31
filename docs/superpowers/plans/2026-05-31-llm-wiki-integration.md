# llm-wiki-tools Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add document ingest (with traceability), BM25 `notes_search`, and frontend-push structural lint to the Chief-of-Staff Notes Assistant by consuming `llm-wiki-tools` (`lwt`) as a library — without changing the topic/meeting/task model or the sandbox boundary.

**Architecture:** `lwt` is imported (not shelled out). Ingest runs in the frontend on upload (`upload.py`). Search becomes a read-only MCP tool on the broadened **Ground Truth service** (the former agenda server, server key renamed `agenda` → `notes`). Index regeneration + lint run as a deterministic frontend housekeeping pass at the existing per-turn commit point; lint auto-fixes mechanical issues and surfaces only judgment findings.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, `rank-bm25` (via `lwt`), PyYAML, pytest. Design: `docs/superpowers/specs/2026-05-31-llm-wiki-integration-design.md`. Decision: `docs/adr/0007-wiki-conventions-and-ground-truth-service.md`.

**Working tree:** a feature branch (`feat/llm-wiki-integration`), ideally in a temporary worktree. `llm-wiki-tools` is a sibling checkout at `../llm-wiki-tools` (not part of this repo).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `frontend/pyproject.toml` | Declare the `llm-wiki-tools` dependency | Modify |
| `agenda/pyproject.toml` | Declare `llm-wiki-tools` (search import lives in the server) | Modify |
| `frontend/upload.py` | `lwt`-backed bytes→markdown converter behind the `convert` seam | Modify |
| `frontend/app.py` | Wire the new converter; run housekeeping at the commit point | Modify |
| `frontend/wiki.py` | NEW — deterministic housekeeping: index regeneration + lint pass | Create |
| `agenda/server.py` | Rename server key → `notes`; add `notes_search` tool | Modify |
| `frontend/config.py` | MCP key `agenda`→`notes`; permission `agenda_*`→`notes_*` | Modify |
| `frontend/assets/notes-agent.md` | Rename tools; teach `[[link]]`, frontmatter, `notes_search`, generated index | Modify |
| `frontend/bootstrap.py` | Scaffold notes-tree `.gitignore` (`.lwt_cache/`, `.tmp/`) | Modify |
| `tests/frontend/test_upload.py` | Cover the `lwt` converter | Modify |
| `tests/frontend/test_wiki.py` | NEW — index regen + lint surfacing + newline autofix | Create |
| `tests/agenda/test_server.py` | Cover `notes_search` + renamed server | Modify |
| `tests/frontend/test_config.py` | NEW/extend — `notes_*` perms + `notes` MCP key | Create/Modify |

**Build order rationale:** dependency first (everything imports `lwt`), then the two leaf capabilities (ingest, search) that have no cross-deps, then housekeeping (index+lint) and its wiring, then the prompt/scaffold/doc-facing changes, then full verification.

---

### Task 0: Add the `llm-wiki-tools` dependency

**Files:**
- Modify: `frontend/pyproject.toml`
- Modify: `agenda/pyproject.toml`

- [ ] **Step 1: Inspect both pyproject dependency blocks**

Run: `sed -n '1,40p' frontend/pyproject.toml agenda/pyproject.toml`
Expected: see each `[project] dependencies = [...]` list.

- [ ] **Step 2: Add the dependency to both**

Add `"llm-wiki-tools",` to the `dependencies` list in **both** `frontend/pyproject.toml` and `agenda/pyproject.toml` (no version pin yet — local sibling install).

- [ ] **Step 3: Install editable into the venv**

Run: `.venv/bin/pip install -e ../llm-wiki-tools`
Expected: `Successfully installed llm-wiki-tools-<version>`.

- [ ] **Step 4: Verify the imports resolve**

Run: `.venv/bin/python -c "from llm_wiki.search import search; from llm_wiki.lint import lint_structural, check_newlines; from llm_wiki.ingest import ingest_source; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add frontend/pyproject.toml agenda/pyproject.toml
git commit -m "build: depend on llm-wiki-tools (library integration)"
```

---

### Task 1: `lwt`-backed upload converter

Replace `markitdown_convert` with an `lwt`-backed converter behind the existing `convert(data: bytes, suffix: str) -> str` seam in `store_upload`. `lwt`'s handlers (`EXTENSION_MAP`) take a path and return `(backend, md_body)`; we write bytes to a temp file, dispatch, and prepend traceability frontmatter.

**Files:**
- Modify: `frontend/upload.py`
- Test: `tests/frontend/test_upload.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/frontend/test_upload.py — add
from frontend.upload import lwt_convert

def test_lwt_convert_pdf_returns_markdown_with_traceability(tmp_path):
    # a minimal real PDF via fpdf2 (already a dev dep of lwt)
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(40, 10, "Atlas migration kickoff")
    data = bytes(pdf.output())

    md = lwt_convert(data, ".pdf")

    assert "Atlas migration kickoff" in md
    assert md.startswith("---\n")          # traceability frontmatter present
    assert "ingest-backend:" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_upload.py::test_lwt_convert_pdf_returns_markdown_with_traceability -v`
Expected: FAIL — `ImportError: cannot import name 'lwt_convert'`.

- [ ] **Step 3: Implement `lwt_convert`**

```python
# frontend/upload.py — add (keep markitdown_convert for now; app.py switches over in Task 6)
def lwt_convert(data: bytes, suffix: str) -> str:
    """Convert office/markdown bytes to markdown via llm-wiki-tools, with
    traceability frontmatter. Writes bytes to a temp file (the lwt handlers are
    path-based) and uses ingest_source's stdout mode to get frontmatter + body."""
    import io
    import tempfile
    from contextlib import redirect_stdout
    from pathlib import Path

    from llm_wiki.ingest import ingest_source

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"upload{suffix}"
        src.write_bytes(data)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ingest_source(
                source=src,
                wiki_dir=Path(td),          # .tmp/ lives under the throwaway dir
                ingest_command=f"upload {suffix}",
                output="-",                 # write "---\n<frontmatter>---\n\n<body>" to stdout
            )
        return buf.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_upload.py::test_lwt_convert_pdf_returns_markdown_with_traceability -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/upload.py tests/frontend/test_upload.py
git commit -m "feat(upload): lwt-backed converter with traceability frontmatter"
```

---

### Task 2: `notes_search` tool + rename server key to `notes`

Rename the FastMCP server key `agenda` → `notes` (so OpenCode exposes `notes_today/review/topic`) and add a `search` tool → `notes_search`, backed by `llm_wiki.search`.

**Files:**
- Modify: `agenda/server.py`
- Test: `tests/agenda/test_server.py`

- [ ] **Step 1: Read the current server test to match its harness**

Run: `sed -n '1,60p' tests/agenda/test_server.py`
Expected: see how it constructs/inspects the FastMCP instance and calls tools.

- [ ] **Step 2: Write the failing test**

```python
# tests/agenda/test_server.py — add
def test_search_tool_returns_ranked_paths(tmp_path, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\n## Overview\nAtlas migration to Postgres.\n",
        encoding="utf-8",
    )
    (tmp_path / "topics" / "hiring.md").write_text(
        "---\nslug: hiring\ntitle: Hiring\n---\n## Overview\nBackend hiring plan.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))

    import importlib
    from agenda import server
    importlib.reload(server)

    results = server.search("atlas migration")

    assert results, "expected at least one hit"
    assert results[0]["path"].endswith("topics/atlas.md")
    assert results[0]["score"] > 0


def test_server_key_is_notes():
    import importlib
    from agenda import server
    importlib.reload(server)
    assert server.mcp.name == "notes"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_server.py::test_search_tool_returns_ranked_paths tests/agenda/test_server.py::test_server_key_is_notes -v`
Expected: FAIL — `AttributeError: module 'agenda.server' has no attribute 'search'` and the name assert fails (`'agenda' != 'notes'`).

- [ ] **Step 4: Implement the rename + search tool**

```python
# agenda/server.py — replace the FastMCP construction + comment, and add the tool
mcp = FastMCP("notes")

# Bare tool names — OpenCode namespaces these as notes_<name> (server key "notes"),
# so the agent sees notes_today / notes_review / notes_topic / notes_search. The
# server is the read-only Ground Truth service (CONTEXT.md): deterministic reads
# over the Ground Truth — agenda views plus BM25 search. It never writes.
TOOL_NAMES = ("today", "review", "topic", "search")
```

```python
# agenda/server.py — add alongside the other @mcp.tool() functions
@mcp.tool()
def search(query: str, n: int = 10) -> list[dict]:
    """BM25 keyword search over the Ground Truth. Returns ranked
    {path, score, snippet}. Pull this when you need to find topics/meetings by
    content; then read the top hits and cite them."""
    from llm_wiki.search import search as _search

    root = _notes_root()
    return [
        {"path": str(r.path.relative_to(root)) if r.path.is_relative_to(root) else str(r.path),
         "score": round(r.score, 2),
         "snippet": r.snippet}
        for r in _search(root, query, n=n)
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_server.py::test_search_tool_returns_ranked_paths tests/agenda/test_server.py::test_server_key_is_notes -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agenda/server.py tests/agenda/test_server.py
git commit -m "feat(notes-service): rename server key to notes; add notes_search (BM25)"
```

---

### Task 3: Config — `notes_*` permissions + `notes` MCP key

**Files:**
- Modify: `frontend/config.py`
- Test: `tests/frontend/test_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/frontend/test_config.py
from frontend.config import build_opencode_config

def _cfg():
    return build_opencode_config(
        model_endpoint="http://x/v1", model_id="m", notes_root="/n",
        agenda_server="/bin/agenda-server", prompt_path="/p.md",
    )

def test_mcp_key_is_notes():
    assert "notes" in _cfg()["mcp"]
    assert "agenda" not in _cfg()["mcp"]

def test_permission_allows_notes_tools():
    perms = _cfg()["permission"]
    assert perms["notes_*"] == "allow"
    assert "agenda_*" not in perms
    assert perms["bash"] == "deny"   # sandbox unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_config.py -v`
Expected: FAIL — `KeyError: 'notes'` / `assert 'notes_*' in perms`.

- [ ] **Step 3: Implement**

```python
# frontend/config.py — in build_opencode_config:
# 1) permissions dict: rename the key
#      "agenda_*": "allow",   ->   "notes_*": "allow",
# 2) mcp dict: rename the server key
#      "agenda": { ... }      ->   "notes": { ... }   (command/env unchanged)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/config.py tests/frontend/test_config.py
git commit -m "feat(config): notes MCP key + notes_* permission (Ground Truth service)"
```

---

### Task 4: Housekeeping — deterministic `index.md` regeneration

New `frontend/wiki.py`. `regenerate_index` walks `topics/*.md` and `meetings/**/*.md`, reads YAML frontmatter, and writes `index.md` with **plain markdown links** (`[title](path)`) — NOT `[[wikilinks]]`, so lint's orphan detection still measures genuine inter-topic linking (see ADR-0007 / spec).

**Files:**
- Create: `frontend/wiki.py`
- Test: `tests/frontend/test_wiki.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/frontend/test_wiki.py
from pathlib import Path
from frontend.wiki import regenerate_index

def _topic(root: Path, slug: str, title: str):
    (root / "topics").mkdir(parents=True, exist_ok=True)
    (root / "topics" / f"{slug}.md").write_text(
        f"---\nslug: {slug}\ntitle: {title}\nstatus: active\n---\n## Overview\n", encoding="utf-8")

def test_regenerate_index_lists_topics_with_plain_links(tmp_path):
    _topic(tmp_path, "atlas", "Atlas Migration")
    _topic(tmp_path, "hiring", "Backend Hiring")

    regenerate_index(tmp_path)

    idx = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "[Atlas Migration](topics/atlas.md)" in idx
    assert "[Backend Hiring](topics/hiring.md)" in idx
    assert "[[" not in idx          # never wikilinks (would neuter orphan lint)

def test_regenerate_index_is_deterministic(tmp_path):
    _topic(tmp_path, "b", "Bee")
    _topic(tmp_path, "a", "Ay")
    regenerate_index(tmp_path); first = (tmp_path / "index.md").read_text()
    regenerate_index(tmp_path); second = (tmp_path / "index.md").read_text()
    assert first == second
    assert first.index("(topics/a.md)") < first.index("(topics/b.md)")  # sorted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_wiki.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'frontend.wiki'`.

- [ ] **Step 3: Implement `regenerate_index`**

```python
# frontend/wiki.py
"""Deterministic notes-tree housekeeping: index regeneration + structural lint.

The agent never maintains these — the frontend (sole writer, ADR-0003) regenerates
index.md and runs lint after a structural turn, so structure cannot silently drift.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}


def _entries(notes_root: Path) -> list[tuple[str, str]]:
    """Return sorted (title, relpath) for every topic and meeting page."""
    out: list[tuple[str, str]] = []
    for sub in ("topics", "meetings"):
        base = notes_root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            fm = _frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            title = str(fm.get("title") or p.stem)
            out.append((title, p.relative_to(notes_root).as_posix()))
    return sorted(out, key=lambda e: e[1])


def regenerate_index(notes_root: Path | str) -> Path:
    """Write index.md: one plain-markdown link per topic/meeting page. Plain links
    (not [[wikilinks]]) so lint orphan detection measures real inter-topic links."""
    root = Path(notes_root)
    lines = ["# Index", "", "_Generated — do not hand-edit._", ""]
    lines += [f"- [{title}]({rel})" for title, rel in _entries(root)]
    out = root / "index.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_wiki.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/wiki.py tests/frontend/test_wiki.py
git commit -m "feat(wiki): deterministic code-owned index.md regeneration"
```

---

### Task 5: Housekeeping — lint pass (auto-fix mechanical, surface judgment)

Add `run_housekeeping(notes_root)` to `frontend/wiki.py`: regenerate index, auto-fix mechanical lint (trailing newlines) silently, run structural lint, and return only the **judgment** findings as plain dicts.

**Files:**
- Modify: `frontend/wiki.py`
- Test: `tests/frontend/test_wiki.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/frontend/test_wiki.py — add
from frontend.wiki import run_housekeeping

def test_housekeeping_autofixes_newlines_silently(tmp_path):
    (tmp_path / "topics").mkdir()
    p = tmp_path / "topics" / "atlas.md"
    p.write_text("---\nslug: atlas\ntitle: Atlas\n---\n## Overview\nno newline", encoding="utf-8")  # missing trailing \n

    findings = run_housekeeping(tmp_path)

    assert p.read_text(encoding="utf-8").endswith("\n")          # fixed in place
    assert all(f["type"] != "newline" for f in findings)         # mechanical, not surfaced

def test_housekeeping_surfaces_broken_link(tmp_path):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\nSee [[ghost]].\n", encoding="utf-8")

    findings = run_housekeeping(tmp_path)

    assert any(f["type"] == "broken_link" and "ghost" in f["message"] for f in findings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_wiki.py -k housekeeping -v`
Expected: FAIL — `ImportError: cannot import name 'run_housekeeping'`.

- [ ] **Step 3: Implement `run_housekeeping`**

```python
# frontend/wiki.py — add
from llm_wiki.lint import check_newlines, lint_structural


def _autofix_newlines(notes_root: Path) -> None:
    """Silently normalise every page to exactly one trailing newline (mechanical)."""
    for finding in check_newlines(notes_root):
        p = Path(finding.path)
        text = p.read_text(encoding="utf-8", errors="replace")
        p.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


def run_housekeeping(notes_root: Path | str) -> list[dict]:
    """Regenerate index, auto-fix mechanical lint silently, return judgment findings.

    Judgment findings (broken links, orphans, missing-index) are returned as
    {type, path, line, message} for the caller to surface to the agent/user.
    """
    root = Path(notes_root)
    _autofix_newlines(root)
    regenerate_index(root)
    return [
        {"type": f.issue_type, "path": Path(f.path).relative_to(root).as_posix(),
         "line": f.line, "message": f.message}
        for f in lint_structural(root)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_wiki.py -k housekeeping -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/wiki.py tests/frontend/test_wiki.py
git commit -m "feat(wiki): lint pass — auto-fix mechanical, surface judgment findings"
```

---

### Task 6: Wire housekeeping + new converter into the request path

Run housekeeping inside the existing `git_lock` in `/api/message` **before** `commit_all` (so index + autofix land in the same turn's commit), return the judgment findings in the response, and switch the upload route to `lwt_convert`.

**Files:**
- Modify: `frontend/app.py`
- Test: `tests/frontend/test_app.py`

- [ ] **Step 1: Read the app test harness**

Run: `sed -n '1,80p' tests/frontend/test_app.py`
Expected: see how it builds the app/proxy fake and posts to `/api/message`.

- [ ] **Step 2: Write the failing test**

```python
# tests/frontend/test_app.py — add (adapt fixture names to the file's existing harness)
def test_message_returns_lint_findings(tmp_app):     # tmp_app: (client, notes_root) per existing harness
    client, notes_root = tmp_app
    (notes_root / "topics").mkdir(parents=True, exist_ok=True)
    (notes_root / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\nSee [[ghost]].\n", encoding="utf-8")

    resp = client.post("/api/message", json={"text": "process notes"})

    body = resp.json()
    assert body["ok"] is True
    assert any(f["type"] == "broken_link" for f in body["lint"])
    assert (notes_root / "index.md").exists()        # housekeeping ran
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_app.py::test_message_returns_lint_findings -v`
Expected: FAIL — `KeyError: 'lint'` (and no index.md).

- [ ] **Step 4: Implement the wiring**

```python
# frontend/app.py
# (a) imports
from frontend.upload import lwt_convert, store_upload   # drop markitdown_convert
from frontend import wiki

# (b) /api/message — inside `async with git_lock:`, before commit_all:
        async with git_lock:
            subject = changelog_subject(await proxy.final_agent_text()) or msg.text
            findings = wiki.run_housekeeping(notes_root)      # index + lint, deterministic
            committed = versioning.commit_all(notes_root, subject, git_dir=_git_dir)
        return {"ok": True, "committed": committed, "lint": findings}

# (c) /api/upload — switch the converter:
        result = store_upload(notes_root, file.filename or "", data, convert=lwt_convert)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_app.py::test_message_returns_lint_findings -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/app.py tests/frontend/test_app.py
git commit -m "feat(app): per-turn housekeeping (index+lint) + lwt upload converter"
```

---

### Task 7: System prompt — teach the conventions and renamed tools

**Files:**
- Modify: `frontend/assets/notes-agent.md`

- [ ] **Step 1: Rename the agenda tools**

In `frontend/assets/notes-agent.md`, replace every `agenda_today` → `notes_today`, `agenda_review` → `notes_review`, `agenda_topic` → `notes_topic`. Rename the "# Agenda tools" heading to "# Ground Truth service tools (read-only)".

- [ ] **Step 2: Add the search tool**

Under that heading add:
```markdown
  - `notes_search(query, n)` — BM25 keyword search over the notes. Pull it when
    you need to find topics/meetings by content rather than by date. Read the top
    hits before answering, and cite them. (Do not guess paths — search.)
```

- [ ] **Step 3: Add the conventions block**

Add a new section:
```markdown
# Wiki conventions
- **Cross-link** related pages with `[[slug]]` (the page's immutable slug). You
  *author* links by judgment; a structural check validates them — fix any broken
  `[[link]]` it reports (typo, or create the missing page).
- **index.md is generated** from page frontmatter and is **read-only to you** —
  never hand-edit it. There is no log file; the turn's `CHANGELOG:` line is the log.
- Uploaded documents arrive with **traceability frontmatter** (source-sha, backend,
  ingested-at) already filled in by ingest — never invent or edit those fields.
```

- [ ] **Step 4: Verify no stale references remain**

Run: `grep -n "agenda_" frontend/assets/notes-agent.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/assets/notes-agent.md
git commit -m "docs(prompt): notes_* tools, notes_search, wiki conventions"
```

---

### Task 8: Scaffold notes-tree `.gitignore`

The BM25 cache (`.lwt_cache/`) and ingest temp (`.tmp/`) are written into the notes tree; they must not be committed by the frontend's per-turn git.

**Files:**
- Modify: `frontend/bootstrap.py`
- Test: `tests/frontend/test_bootstrap.py`

- [ ] **Step 1: Read where bootstrap writes the workspace/notes tree**

Run: `grep -n "workspace\|gitignore\|ensure_repo\|mkdir" frontend/bootstrap.py`
Expected: locate where the notes/workspace dir is created (near `versioning.ensure_repo`, ~line 126-128).

- [ ] **Step 2: Write the failing test**

```python
# tests/frontend/test_bootstrap.py — add (use the file's existing init_install harness)
def test_install_gitignores_lwt_caches(tmp_path):
    from frontend.bootstrap import init_install
    init_install(str(tmp_path / "inst"), model_endpoint="http://x/v1",
                 model_id="m", agenda_server="/bin/agenda-server")
    gi = (tmp_path / "inst" / "workspace" / ".gitignore").read_text(encoding="utf-8")
    assert ".lwt_cache/" in gi
    assert ".tmp/" in gi
```
(Adjust the workspace path to match `init_install`'s actual layout seen in Step 1.)

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/frontend/test_bootstrap.py::test_install_gitignores_lwt_caches -v`
Expected: FAIL — file/needle missing.

- [ ] **Step 4: Implement**

In `init_install`, after the workspace dir is created and before/after `ensure_repo`, write the notes-tree `.gitignore`:
```python
    workspace = work  # the notes/workspace leaf used for ensure_repo
    gitignore = Path(workspace) / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".lwt_cache/\n.tmp/\n", encoding="utf-8")
```
(Use the same `work`/workspace variable `ensure_repo` is called with at ~line 126-128.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/frontend/test_bootstrap.py::test_install_gitignores_lwt_caches -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/bootstrap.py tests/frontend/test_bootstrap.py
git commit -m "feat(bootstrap): gitignore .lwt_cache/ and .tmp/ in the notes tree"
```

---

### Task 9: Full verification + regression canary

**Files:**
- Modify: `tests/frontend/test_wiki.py` (canary)

- [ ] **Step 1: Add the search+lint regression canary**

```python
# tests/frontend/test_wiki.py — add
def test_canary_search_finds_topic_and_lint_catches_broken_link(tmp_path):
    from llm_wiki.search import search
    from frontend.wiki import run_housekeeping
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\n## Overview\nAtlas migration to Postgres.\nSee [[ghost]].\n",
        encoding="utf-8")

    hits = search(tmp_path, "postgres migration")
    assert hits and hits[0].path.name == "atlas.md"

    findings = run_housekeeping(tmp_path)
    assert any(f["type"] == "broken_link" and "ghost" in f["message"] for f in findings)
```

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass (the live smoke under `tests/smoke/` is excluded by `pytest.ini`).

- [ ] **Step 3: Lint-diff gate**

Run: `.venv/bin/ruff check agenda frontend launcher notes-mvp tests`
Expected: no new errors introduced by this branch (compare against `main` if unsure).

- [ ] **Step 4: Manual smoke note (informational — needs a live model)**

Run: `python tests/smoke/notes-mvp/run_smoke.py`
Expected: ingest → file → `notes_search` recall works end-to-end. (Skip if no live endpoint; note it as untested.)

- [ ] **Step 5: Commit**

```bash
git add tests/frontend/test_wiki.py
git commit -m "test: search+lint regression canary for the wiki integration"
```

---

## Self-Review

- **Spec coverage:** ingest swap (Task 1, 6) · `notes_search` MCP (Task 2) · config/perms (Task 3) · code-owned index (Task 4) · frontend-push lint with mechanical autofix + judgment surfacing (Task 5, 6) · conventions in prompt (Task 7) · cache gitignore (Task 8) · testing + canary (Task 9). Deferred items (deploy, update/manifest, qmd, M2 grounding) intentionally have no tasks.
- **Open questions resolved:** tool prefix → `notes_*` (single server, Task 2/3); ingest frontmatter → full `lwt` traceability via stdout mode (Task 1); search scope → `BM25Index` already skips dotted dirs; excluding `archive/`/`briefs/` is deferred (advisory only — note in Task 2 if recall noise appears, add an upstream `exclude` arg to `lwt`). 
- **Type consistency:** `run_housekeeping` returns `list[dict]` with keys `type/path/line/message`; `app.py` returns it under `"lint"`; tests assert the same keys. `regenerate_index` returns `Path`. `notes_search` returns `list[dict]` with `path/score/snippet`.
- **Naming:** server key `notes`; tools `notes_today/review/topic/search`; permission `notes_*`; MCP key `notes` — consistent across Tasks 2, 3, 7.

## Notes for the implementer

- The agenda **Python package** stays named `agenda/` and the `agenda-server` entry point is unchanged — only the MCP **server key** (what the agent sees) becomes `notes`. Renaming the package/entry point is out of scope (YAGNI; it would churn bootstrap/launcher/config for no agent-visible gain).
- `lwt`'s `BM25Index` writes its cache to `<notes_root>/.lwt_cache/`; Task 8's gitignore keeps it out of the per-turn commit. The cache auto-rebuilds on page mtime change, so no explicit reindex call is needed.
- Keep `markitdown_convert` in `upload.py` until Task 6 swaps the call site, so no test references a deleted symbol mid-plan; remove it in a follow-up once `lwt_convert` is proven in real use.
