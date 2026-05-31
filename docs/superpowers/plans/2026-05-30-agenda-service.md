# Agenda Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, read-only Agenda service for the Chief-of-Staff Notes MVP — a Python package that parses the `notes/` Ground Truth and computes `today` / `review` / `topic` agendas, exposed as a read-only MCP stdio server (`agenda_today`, `agenda_review`, `agenda_topic`).

**Architecture:** A pure-functional core (`parser` → `models` → `engine`) computes agendas from on-disk files with no side effects, wrapped by a thin MCP server (`server`). The engine never writes. All date/surfacing logic lives in code so date-based follow-ups can never silently drop (ADR-0001). The MCP server exposes only read tools (read-only by construction, design §5.3).

**Tech Stack:** Python 3.12 · official `mcp` SDK (FastMCP) · `pyyaml` (frontmatter) · `pytest` · stdlib `datetime`/`pathlib`. Hand-rolled todo.txt parser (no external parser dependency).

**Scope note:** This is **plan 1 of 4** for Milestone 1 (the Chief-of-Staff Notes MVP, spec `mvp-chief-of-staff-notes-design.md`, plan WP **N2** + the `tasks.todo.txt`/frontmatter parts of **N0**). It produces working, testable software on its own: a runnable MCP server you can query against a notes fixture. Follow-up plans: (2) OpenCode config + notes system prompt (N1), (3) frontend — proxy/SSE/UI/upload/git-versioning (N3–N5), (4) launcher + integration (N6–N7).

**Data model reference (frozen, design §4):**
- `tasks.todo.txt` line: `[x ]?(\([A-D]\) )?<text with +topic @context due:YYYY-MM-DD t:YYYY-MM-DD upd:YYYY-MM-DD>`
  - `x ` prefix → completed. `(A)`–`(D)` → Eisenhower quadrant (A=urgent+important, B=important-not-urgent, C=urgent-not-important, D=neither).
  - `+topic` → topic slug link · `@context` → free tag · `due:` deadline · `t:` tickler (resurface date) · `upd:` last-touched date (set on create and on every edit).
- Topic file frontmatter: `slug` (immutable id), `title`, `tags`, `status`.
- Meeting file frontmatter: `date`, `title`, `topics` (list of slugs).
- Thresholds (config constants): stale item = **7 days** since `upd:`; stale topic = **21 days** (3 weeks) since last meeting.

---

### Task 0: Project setup

**Files:**
- Create: `agenda/__init__.py`
- Create: `agenda/pyproject.toml`
- Create: `agenda/requirements-dev.txt`
- Create: `tests/agenda/__init__.py`

- [ ] **Step 1: Create the package skeleton and dev requirements**

Create `agenda/__init__.py`:

```python
"""Deterministic, read-only Agenda service for the Chief-of-Staff Notes MVP."""

__version__ = "0.1.0"
```

Create `agenda/pyproject.toml`:

```toml
[project]
name = "agenda-service"
version = "0.1.0"
description = "Read-only Agenda service over the local notes Ground Truth"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.2.0",
    "pyyaml>=6.0",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

Create `agenda/requirements-dev.txt`:

```
pytest>=8.0
```

Create empty `tests/agenda/__init__.py` (no content).

- [ ] **Step 2: Create a virtualenv and install deps**

Run (from the repo root):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ./agenda
.venv/bin/pip install -r agenda/requirements-dev.txt
```

Expected: installs `mcp`, `pyyaml`, `pytest` and the editable `agenda-service` package without error.

- [ ] **Step 3: Verify the package imports**

Run:

```bash
.venv/bin/python -c "import agenda; print(agenda.__version__)"
```

Expected: prints `0.1.0`.

- [ ] **Step 4: Commit**

```bash
git add agenda/ tests/agenda/__init__.py
git commit -m "feat(agenda): package skeleton + deps"
```

---

### Task 1: Action model and single-line parser

**Files:**
- Create: `agenda/models.py`
- Create: `agenda/parser.py`
- Test: `tests/agenda/test_parser_line.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agenda/test_parser_line.py`:

```python
from datetime import date

from agenda.parser import parse_task_line


def test_parses_full_action():
    line = "(A) Sign off Atlas design +project-atlas @decision due:2026-06-02 upd:2026-05-28"
    a = parse_task_line(line)
    assert a is not None
    assert a.done is False
    assert a.priority == "A"
    assert a.quadrant == "urgent_important"
    assert a.description == "Sign off Atlas design"
    assert a.topics == ["project-atlas"]
    assert a.contexts == ["decision"]
    assert a.due == date(2026, 6, 2)
    assert a.updated == date(2026, 5, 28)
    assert a.tickler is None


def test_parses_completed_b_item_with_tickler():
    a = parse_task_line("x (B) Draft Q3 proposal +governance t:2026-06-09")
    assert a.done is True
    assert a.priority == "B"
    assert a.quadrant == "important_not_urgent"
    assert a.tickler == date(2026, 6, 9)
    assert a.topics == ["governance"]


def test_blank_and_comment_lines_return_none():
    assert parse_task_line("") is None
    assert parse_task_line("   ") is None
    assert parse_task_line("# a comment") is None


def test_action_without_priority():
    a = parse_task_line("Buy bread +home")
    assert a.priority is None
    assert a.quadrant is None
    assert a.description == "Buy bread"
    assert a.topics == ["home"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_parser_line.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agenda.parser'` (or ImportError for `parse_task_line`).

- [ ] **Step 3: Write the model**

Create `agenda/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

QUADRANT_BY_PRIORITY = {
    "A": "urgent_important",
    "B": "important_not_urgent",
    "C": "urgent_not_important",
    "D": "neither",
}


@dataclass
class Action:
    raw: str
    done: bool = False
    priority: str | None = None
    description: str = ""
    topics: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    due: date | None = None
    tickler: date | None = None
    updated: date | None = None

    @property
    def quadrant(self) -> str | None:
        return QUADRANT_BY_PRIORITY.get(self.priority) if self.priority else None

    def to_dict(self) -> dict:
        return {
            "text": self.description,
            "priority": self.priority,
            "quadrant": self.quadrant,
            "topics": self.topics,
            "contexts": self.contexts,
            "due": self.due.isoformat() if self.due else None,
            "tickler": self.tickler.isoformat() if self.tickler else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "done": self.done,
        }
```

- [ ] **Step 4: Write the single-line parser**

Create `agenda/parser.py`:

```python
from __future__ import annotations

import re
from datetime import date, datetime

from agenda.models import Action

_PRIORITY_RE = re.compile(r"^\(([A-D])\)$")
_DATE_KEYS = {"due", "t", "upd"}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_task_line(line: str) -> Action | None:
    """Parse one todo.txt line into an Action, or None for blank/comment lines."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    tokens = stripped.split()
    action = Action(raw=stripped)

    if tokens and tokens[0] == "x":
        action.done = True
        tokens = tokens[1:]

    if tokens:
        m = _PRIORITY_RE.match(tokens[0])
        if m:
            action.priority = m.group(1)
            tokens = tokens[1:]

    words: list[str] = []
    for tok in tokens:
        if tok.startswith("+") and len(tok) > 1:
            action.topics.append(tok[1:])
        elif tok.startswith("@") and len(tok) > 1:
            action.contexts.append(tok[1:])
        elif ":" in tok and tok.split(":", 1)[0] in _DATE_KEYS:
            key, value = tok.split(":", 1)
            parsed = _parse_date(value)
            if key == "due":
                action.due = parsed
            elif key == "t":
                action.tickler = parsed
            elif key == "upd":
                action.updated = parsed
        else:
            words.append(tok)

    action.description = " ".join(words)
    return action
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_parser_line.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add agenda/models.py agenda/parser.py tests/agenda/test_parser_line.py
git commit -m "feat(agenda): Action model + todo.txt line parser"
```

---

### Task 2: Parse a whole tasks.todo.txt file

**Files:**
- Modify: `agenda/parser.py` (add `parse_task_file`)
- Test: `tests/agenda/test_parser_file.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agenda/test_parser_file.py`:

```python
from agenda.parser import parse_task_file


def test_parses_file_skipping_blanks_and_comments(tmp_path):
    f = tmp_path / "tasks.todo.txt"
    f.write_text(
        "# my tasks\n"
        "(A) Do thing +alpha\n"
        "\n"
        "x (C) Done thing +beta\n",
        encoding="utf-8",
    )
    actions = parse_task_file(f)
    assert len(actions) == 2
    assert actions[0].description == "Do thing"
    assert actions[1].done is True


def test_missing_file_returns_empty_list(tmp_path):
    actions = parse_task_file(tmp_path / "nope.txt")
    assert actions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_parser_file.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_task_file'`.

- [ ] **Step 3: Add `parse_task_file` to `agenda/parser.py`**

Append to `agenda/parser.py`:

```python
from pathlib import Path


def parse_task_file(path: Path) -> list[Action]:
    """Parse every action in a tasks.todo.txt file. Missing file → []."""
    p = Path(path)
    if not p.is_file():
        return []
    actions: list[Action] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        action = parse_task_line(line)
        if action is not None:
            actions.append(action)
    return actions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_parser_file.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agenda/parser.py tests/agenda/test_parser_file.py
git commit -m "feat(agenda): parse_task_file"
```

---

### Task 3: Frontmatter parser for topic and meeting files

**Files:**
- Modify: `agenda/parser.py` (add `parse_frontmatter`)
- Test: `tests/agenda/test_frontmatter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agenda/test_frontmatter.py`:

```python
from agenda.parser import parse_frontmatter


def test_parses_yaml_frontmatter(tmp_path):
    f = tmp_path / "project-atlas.md"
    f.write_text(
        "---\n"
        "slug: project-atlas\n"
        "title: Atlas Programme\n"
        "tags: [technical, delivery]\n"
        "status: active\n"
        "---\n"
        "## Overview\n",
        encoding="utf-8",
    )
    fm = parse_frontmatter(f)
    assert fm["slug"] == "project-atlas"
    assert fm["title"] == "Atlas Programme"
    assert fm["tags"] == ["technical", "delivery"]


def test_no_frontmatter_returns_empty_dict(tmp_path):
    f = tmp_path / "plain.md"
    f.write_text("just text, no frontmatter\n", encoding="utf-8")
    assert parse_frontmatter(f) == {}


def test_missing_file_returns_empty_dict(tmp_path):
    assert parse_frontmatter(tmp_path / "nope.md") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_frontmatter.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_frontmatter'`.

- [ ] **Step 3: Add `parse_frontmatter` to `agenda/parser.py`**

Add the import at the top of `agenda/parser.py` (with the other imports):

```python
import yaml
```

Append to `agenda/parser.py`:

```python
def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter of a markdown file as a dict ({} if absent)."""
    p = Path(path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1])
    return data if isinstance(data, dict) else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_frontmatter.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agenda/parser.py tests/agenda/test_frontmatter.py
git commit -m "feat(agenda): YAML frontmatter parser"
```

---

### Task 4: Engine — `today`

**Files:**
- Create: `agenda/engine.py`
- Test: `tests/agenda/test_engine_today.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agenda/test_engine_today.py`:

```python
from datetime import date

from agenda.engine import today

TODAY = date(2026, 5, 30)


def _write_tasks(root, body):
    (root / "tasks.todo.txt").write_text(body, encoding="utf-8")


def test_today_buckets(tmp_path):
    _write_tasks(
        tmp_path,
        "(A) Urgent important +alpha upd:2026-05-29\n"
        "(B) Important not urgent +beta upd:2026-05-29\n"
        "(B) Resurfaces today +beta t:2026-05-30 upd:2026-05-29\n"
        "(C) Overdue thing +gamma due:2026-05-28 upd:2026-05-29\n"
        "(A) Stale important +alpha upd:2026-05-10\n"
        "x (A) Done already +alpha upd:2026-05-29\n",
    )
    result = today(tmp_path, on=TODAY)

    do_now = [a["text"] for a in result["do_now"]]
    assert "Urgent important" in do_now
    assert "Overdue thing" in do_now          # due <= today
    assert "Done already" not in do_now        # completed excluded

    assert [a["text"] for a in result["schedule"]] == [
        "Important not urgent",
        "Resurfaces today",
    ]
    assert [a["text"] for a in result["resurfacing"]] == ["Resurfaces today"]
    assert [a["text"] for a in result["overdue"]] == ["Overdue thing"]
    assert [a["text"] for a in result["stale_important"]] == ["Stale important"]
    assert result["date"] == "2026-05-30"


def test_today_empty_when_no_tasks_file(tmp_path):
    result = today(tmp_path, on=TODAY)
    assert result["do_now"] == []
    assert result["stale_important"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_engine_today.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agenda.engine'`.

- [ ] **Step 3: Write the engine `today` function**

Create `agenda/engine.py`:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path

from agenda.models import Action
from agenda.parser import parse_task_file

STALE_ITEM_DAYS = 7
STALE_TOPIC_DAYS = 21


def _tasks(notes_root: Path) -> list[Action]:
    return parse_task_file(Path(notes_root) / "tasks.todo.txt")


def _is_stale_item(a: Action, on: date) -> bool:
    return (
        not a.done
        and a.priority in ("A", "B")
        and a.updated is not None
        and (on - a.updated).days > STALE_ITEM_DAYS
    )


def today(notes_root: Path, on: date | None = None) -> dict:
    on = on or date.today()
    actions = [a for a in _tasks(notes_root) if not a.done]

    do_now = [a for a in actions if a.priority == "A" or (a.due and a.due <= on)]
    schedule = [a for a in actions if a.priority == "B"]
    resurfacing = [a for a in actions if a.tickler and a.tickler <= on]
    overdue = [a for a in actions if a.due and a.due < on]
    stale_important = [a for a in actions if _is_stale_item(a, on)]

    return {
        "date": on.isoformat(),
        "do_now": [a.to_dict() for a in do_now],
        "schedule": [a.to_dict() for a in schedule],
        "resurfacing": [a.to_dict() for a in resurfacing],
        "overdue": [a.to_dict() for a in overdue],
        "stale_important": [a.to_dict() for a in stale_important],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_engine_today.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agenda/engine.py tests/agenda/test_engine_today.py
git commit -m "feat(agenda): engine.today (do-now/schedule/resurfacing/overdue/stale)"
```

---

### Task 5: Engine — topic helpers and `review`

**Files:**
- Modify: `agenda/engine.py` (add `_topics`, `_meetings`, `_last_meeting`, `review`)
- Test: `tests/agenda/test_engine_review.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agenda/test_engine_review.py`:

```python
from datetime import date

from agenda.engine import review

TODAY = date(2026, 5, 30)


def _seed(root):
    (root / "tasks.todo.txt").write_text(
        "(A) Open alpha thing +project-atlas upd:2026-05-29\n"
        "(B) Tickler this week +governance t:2026-06-02 upd:2026-05-29\n"
        "x (C) Closed +project-atlas upd:2026-05-20\n",
        encoding="utf-8",
    )
    (root / "topics").mkdir()
    (root / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas Programme\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (root / "topics" / "governance.md").write_text(
        "---\nslug: governance\ntitle: Governance\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (root / "meetings" / "2026-05-29").mkdir(parents=True)
    (root / "meetings" / "2026-05-29" / "atlas.md").write_text(
        "---\ndate: 2026-05-29\ntitle: Atlas Sync\ntopics: [project-atlas]\n---\n",
        encoding="utf-8",
    )
    # governance has no recent meeting → should be stale (>21 days / never)


def test_review_reports_topics_and_ticklers(tmp_path):
    _seed(tmp_path)
    result = review(tmp_path, on=TODAY)

    topics = {t["slug"]: t for t in result["topics"]}
    assert topics["project-atlas"]["last_meeting"] == "2026-05-29"
    assert topics["project-atlas"]["open_action_count"] == 1   # closed one excluded
    assert topics["project-atlas"]["stale"] is False
    assert topics["governance"]["last_meeting"] is None
    assert topics["governance"]["stale"] is True

    assert result["stale_topics"] == ["governance"]
    assert [a["text"] for a in result["ticklers_this_week"]] == ["Tickler this week"]
    assert result["date"] == "2026-05-30"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_engine_review.py -v`
Expected: FAIL with `ImportError: cannot import name 'review'`.

- [ ] **Step 3: Add topic/meeting helpers and `review` to `agenda/engine.py`**

Add to the imports at the top of `agenda/engine.py`:

```python
from datetime import timedelta

from agenda.parser import parse_frontmatter
```

Append to `agenda/engine.py`:

```python
def _topics(notes_root: Path) -> list[dict]:
    topics_dir = Path(notes_root) / "topics"
    if not topics_dir.is_dir():
        return []
    out = []
    for path in sorted(topics_dir.glob("*.md")):
        fm = parse_frontmatter(path)
        if fm.get("slug"):
            out.append(fm)
    return out


def _meeting_dates_by_topic(notes_root: Path) -> dict[str, list[date]]:
    meetings_dir = Path(notes_root) / "meetings"
    by_topic: dict[str, list[date]] = {}
    if not meetings_dir.is_dir():
        return by_topic
    for path in meetings_dir.rglob("*.md"):
        fm = parse_frontmatter(path)
        mdate = fm.get("date")
        if not isinstance(mdate, date):
            continue
        for slug in fm.get("topics", []) or []:
            by_topic.setdefault(slug, []).append(mdate)
    return by_topic


def review(notes_root: Path, on: date | None = None) -> dict:
    on = on or date.today()
    actions = [a for a in _tasks(notes_root) if not a.done]
    meeting_dates = _meeting_dates_by_topic(notes_root)

    topics_out = []
    stale_topics = []
    for fm in _topics(notes_root):
        slug = fm["slug"]
        dates = meeting_dates.get(slug, [])
        last = max(dates) if dates else None
        is_stale = last is None or (on - last).days > STALE_TOPIC_DAYS
        open_count = sum(1 for a in actions if slug in a.topics)
        topics_out.append(
            {
                "slug": slug,
                "title": fm.get("title", slug),
                "status": fm.get("status"),
                "last_meeting": last.isoformat() if last else None,
                "open_action_count": open_count,
                "stale": is_stale,
            }
        )
        if is_stale:
            stale_topics.append(slug)

    week_end = on + timedelta(days=7)
    ticklers = [
        a for a in actions if a.tickler and on <= a.tickler < week_end
    ]

    return {
        "date": on.isoformat(),
        "topics": topics_out,
        "stale_topics": stale_topics,
        "ticklers_this_week": [a.to_dict() for a in ticklers],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_engine_review.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add agenda/engine.py tests/agenda/test_engine_review.py
git commit -m "feat(agenda): engine.review (topic staleness + weekly ticklers)"
```

---

### Task 6: Engine — `topic`

**Files:**
- Modify: `agenda/engine.py` (add `topic`)
- Test: `tests/agenda/test_engine_topic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agenda/test_engine_topic.py`:

```python
from datetime import date

from agenda.engine import topic

TODAY = date(2026, 5, 30)


def _seed(root):
    (root / "tasks.todo.txt").write_text(
        "(A) Open atlas action +project-atlas upd:2026-05-29\n"
        "(B) Atlas tickler +project-atlas t:2026-06-09 upd:2026-05-29\n"
        "(A) Other topic +governance upd:2026-05-29\n",
        encoding="utf-8",
    )
    (root / "topics").mkdir()
    (root / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas Programme\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (root / "meetings" / "2026-05-29").mkdir(parents=True)
    (root / "meetings" / "2026-05-29" / "atlas.md").write_text(
        "---\ndate: 2026-05-29\ntitle: Atlas Sync\ntopics: [project-atlas]\n---\n",
        encoding="utf-8",
    )


def test_topic_returns_open_actions_ticklers_and_meetings(tmp_path):
    _seed(tmp_path)
    result = topic(tmp_path, "project-atlas", on=TODAY)

    assert result["slug"] == "project-atlas"
    assert result["title"] == "Atlas Programme"
    texts = [a["text"] for a in result["open_actions"]]
    assert texts == ["Open atlas action", "Atlas tickler"]
    assert "Other topic" not in texts
    assert [a["text"] for a in result["ticklers"]] == ["Atlas tickler"]
    assert result["recent_meetings"][0]["title"] == "Atlas Sync"


def test_unknown_topic_returns_empty_sections(tmp_path):
    _seed(tmp_path)
    result = topic(tmp_path, "does-not-exist", on=TODAY)
    assert result["open_actions"] == []
    assert result["recent_meetings"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_engine_topic.py -v`
Expected: FAIL with `ImportError: cannot import name 'topic'`.

- [ ] **Step 3: Add `topic` to `agenda/engine.py`**

Append to `agenda/engine.py`:

```python
def _recent_meetings(notes_root: Path, slug: str, limit: int = 5) -> list[dict]:
    meetings_dir = Path(notes_root) / "meetings"
    found = []
    if meetings_dir.is_dir():
        for path in meetings_dir.rglob("*.md"):
            fm = parse_frontmatter(path)
            if slug in (fm.get("topics", []) or []) and isinstance(fm.get("date"), date):
                found.append(
                    {
                        "date": fm["date"].isoformat(),
                        "title": fm.get("title", path.stem),
                        "path": str(path.relative_to(notes_root)),
                    }
                )
    found.sort(key=lambda m: m["date"], reverse=True)
    return found[:limit]


def topic(notes_root: Path, slug: str, on: date | None = None) -> dict:
    on = on or date.today()
    fm = next((t for t in _topics(notes_root) if t["slug"] == slug), {})
    actions = [a for a in _tasks(notes_root) if not a.done and slug in a.topics]
    ticklers = [a for a in actions if a.tickler]
    return {
        "slug": slug,
        "title": fm.get("title", slug),
        "open_actions": [a.to_dict() for a in actions],
        "ticklers": [a.to_dict() for a in ticklers],
        "recent_meetings": _recent_meetings(notes_root, slug),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_engine_topic.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agenda/engine.py tests/agenda/test_engine_topic.py
git commit -m "feat(agenda): engine.topic (per-topic open actions/ticklers/meetings)"
```

---

### Task 7: Determinism guard test

**Files:**
- Test: `tests/agenda/test_determinism.py`

- [ ] **Step 1: Write the test (it should pass immediately — the engine is pure)**

Create `tests/agenda/test_determinism.py`:

```python
from datetime import date

from agenda.engine import today

TODAY = date(2026, 5, 30)


def test_identical_input_yields_identical_output(tmp_path):
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) Alpha +x upd:2026-05-29\n(B) Beta +y t:2026-05-30 upd:2026-05-29\n",
        encoding="utf-8",
    )
    first = today(tmp_path, on=TODAY)
    second = today(tmp_path, on=TODAY)
    assert first == second
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_determinism.py -v`
Expected: PASS (1 passed). This locks ADR-0001's determinism contract.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest tests/agenda/ -v`
Expected: PASS — all tests across Tasks 1–7 green.

- [ ] **Step 4: Commit**

```bash
git add tests/agenda/test_determinism.py
git commit -m "test(agenda): determinism guard for engine.today"
```

---

### Task 8: Read-only MCP server

**Files:**
- Create: `agenda/server.py`
- Test: `tests/agenda/test_server.py`

- [ ] **Step 1: Write the failing test**

The server reads the notes root from the `NOTES_ROOT` env var and registers exactly three read tools. We test the tool callables and the registered tool set (no write tools).

Create `tests/agenda/test_server.py`:

```python
from datetime import date

import agenda.server as server


def _seed(root):
    (root / "tasks.todo.txt").write_text(
        "(A) Alpha +x upd:2026-05-29\n", encoding="utf-8"
    )


def test_today_tool_reads_notes_root(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
    result = server.agenda_today()
    assert [a["text"] for a in result["do_now"]] == ["Alpha"]


def test_topic_tool_passes_slug(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
    result = server.agenda_topic("x")
    assert result["slug"] == "x"


def test_only_read_tools_registered():
    tool_names = set(server.TOOL_NAMES)
    assert tool_names == {"agenda_today", "agenda_review", "agenda_topic"}
    assert not any("create" in n or "write" in n or "update" in n for n in tool_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agenda/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agenda.server'`.

- [ ] **Step 3: Write the MCP server**

Create `agenda/server.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agenda import engine

mcp = FastMCP("agenda")

# Exposed read-only tool set — asserted in tests; the server registers no writes.
TOOL_NAMES = ("agenda_today", "agenda_review", "agenda_topic")


def _notes_root() -> Path:
    return Path(os.environ.get("NOTES_ROOT", "."))


@mcp.tool()
def agenda_today() -> dict:
    """Today's agenda: do-now, schedule, resurfacing, overdue, stale-important."""
    return engine.today(_notes_root())


@mcp.tool()
def agenda_review() -> dict:
    """Weekly review: per-topic staleness, stale topics, ticklers landing this week."""
    return engine.review(_notes_root())


@mcp.tool()
def agenda_topic(slug: str) -> dict:
    """One topic's open actions, ticklers, and recent meetings."""
    return engine.topic(_notes_root(), slug)


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agenda/test_server.py -v`
Expected: PASS (3 passed). Note the tool functions are plain callables decorated by FastMCP, so they're directly invokable in tests.

- [ ] **Step 5: Add the console entry point**

Modify `agenda/pyproject.toml` — add this section:

```toml
[project.scripts]
agenda-server = "agenda.server:main"
```

Then reinstall to register the script:

```bash
.venv/bin/pip install -e ./agenda
```

Expected: `agenda-server` is now on the venv path.

- [ ] **Step 6: Commit**

```bash
git add agenda/server.py agenda/pyproject.toml tests/agenda/test_server.py
git commit -m "feat(agenda): read-only MCP stdio server (agenda_today/review/topic)"
```

---

### Task 9: Fixture notes tree + manual run instructions

**Files:**
- Create: `agenda/README.md`
- Create: `tests/agenda/fixtures/notes/tasks.todo.txt`
- Create: `tests/agenda/fixtures/notes/topics/project-atlas.md`
- Create: `tests/agenda/fixtures/notes/meetings/2026-05-29/atlas.md`

- [ ] **Step 1: Create a realistic fixture notes tree**

Create `tests/agenda/fixtures/notes/tasks.todo.txt`:

```
(A) Sign off Atlas security design +project-atlas @decision due:2026-06-02 upd:2026-05-29
(B) Draft Q3 governance proposal +governance t:2026-06-09 upd:2026-05-29
(C) Reply to vendor on licensing +procurement due:2026-06-01 upd:2026-05-29
x (A) Approve Atlas budget +project-atlas upd:2026-05-20
```

Create `tests/agenda/fixtures/notes/topics/project-atlas.md`:

```markdown
---
slug: project-atlas
title: Atlas Programme
tags: [technical, delivery]
status: active
---
## Overview
The Atlas programme.
```

Create `tests/agenda/fixtures/notes/meetings/2026-05-29/atlas.md`:

```markdown
---
date: 2026-05-29
title: Atlas Sync
topics: [project-atlas]
---
## Summary
Reviewed the security design.
```

- [ ] **Step 2: Write the run instructions**

Create `agenda/README.md`:

```markdown
# Agenda Service

Deterministic, read-only Agenda service over the local notes Ground Truth.
Exposes an MCP stdio server with three read tools: `agenda_today`,
`agenda_review`, `agenda_topic`. It never writes.

## Install

    python3.12 -m venv .venv
    .venv/bin/pip install -e ./agenda

## Test

    .venv/bin/pytest tests/agenda/ -v

## Run as an MCP server

The server reads the notes directory from the `NOTES_ROOT` environment variable
and speaks MCP over stdio (it is launched by OpenCode, not run standalone):

    NOTES_ROOT=/path/to/notes .venv/bin/agenda-server

OpenCode registers it under the server key `agenda`, exposing the tools as
`agenda_today`, `agenda_review`, `agenda_topic` (config delivered by plan N1).

## Thresholds (config constants, agenda/engine.py)

- `STALE_ITEM_DAYS = 7` — an incomplete A/B action whose `upd:` date is older
  than this is reported in `stale_important`.
- `STALE_TOPIC_DAYS = 21` — a topic with no meeting newer than this (or none at
  all) is reported as stale in the weekly review.
```

- [ ] **Step 3: Smoke-check the engine against the fixture**

Run:

```bash
.venv/bin/python -c "from agenda import engine; from datetime import date; import json; print(json.dumps(engine.today('tests/agenda/fixtures/notes', date(2026,5,30)), indent=2))"
```

Expected: JSON with `do_now` containing "Sign off Atlas security design", `schedule` containing "Draft Q3 governance proposal", and the completed "Approve Atlas budget" absent.

- [ ] **Step 4: Run the full suite one final time**

Run: `.venv/bin/pytest tests/agenda/ -v`
Expected: PASS — every test green.

- [ ] **Step 5: Commit**

```bash
git add agenda/README.md tests/agenda/fixtures/
git commit -m "docs(agenda): fixture notes tree + run instructions"
```

---

## Self-Review

**Spec coverage (design §5 + N2 acceptance gate):**
- `agenda_today` with do-now/schedule/resurfacing/overdue/stale@7d → Task 4 ✓
- `agenda_review` with per-topic last-touched, 3-week stale topics, ticklers this week → Task 5 ✓
- `agenda_topic` with open actions/ticklers/recent meetings → Task 6 ✓
- Read-only MCP server, zero write tools → Task 8 (`test_only_read_tools_registered`) ✓
- Determinism (ADR-0001) → Task 7 ✓
- todo.txt + extensions incl. quadrant mapping, `due:`/`t:`/`upd:` → Tasks 1–2 ✓
- `(B)` with `t:` ≤ today appears in `resurfacing` (N2 gate) → Task 4 `test_today_buckets` ✓

**Contract addition (done):** the `upd:` last-touched tag was added to design §4.1 and the N0 data-model contract to make staleness deterministic; the system prompt (plan N1) must instruct the agent to set `upd:` on create and on every edit.

**Placeholder scan:** none — every code/test step contains complete code; no TBD/TODO.

**Type consistency:** `Action.to_dict()` keys (`text`, `priority`, `quadrant`, `topics`, `contexts`, `due`, `tickler`, `updated`, `done`) are used consistently in all engine outputs and asserted by the tests. Engine function signatures `today(notes_root, on=None)`, `review(notes_root, on=None)`, `topic(notes_root, slug, on=None)` match their server wrappers and tests.

**Out of scope for this plan (later Milestone-1 plans):** OpenCode config + the `agenda` MCP registration and the notes system prompt (N1); the frontend, proxy, SSE, upload, and notes git versioning (N3–N5); the launcher and end-to-end smoke tests (N6–N7).
