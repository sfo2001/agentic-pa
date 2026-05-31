from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import yaml

from agenda.models import Action

_PRIORITY_RE = re.compile(r"^\(([A-D])\)$")
_DATE_KEYS = {"due", "t", "upd"}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_task_line(line: str) -> Action | None:
    """Parse one todo.txt line into an Action, or None for blank/comment lines.

    Note: todo.txt completion-date prefixes (e.g. ``x 2026-05-28 ...``) are NOT
    supported; a date immediately after ``x`` will be treated as description text.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    tokens = stripped.split()
    action = Action()

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
            if parsed is None:
                words.append(tok)
            elif key == "due":
                action.due = parsed
            elif key == "t":
                action.tickler = parsed
            elif key == "upd":
                action.updated = parsed
        else:
            words.append(tok)

    action.description = " ".join(words)
    return action


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


def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter of a markdown file as a dict ({} if absent)."""
    p = Path(path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}
    # BH-14: anchor the split on lines that are exactly "---" so that "---"
    # embedded inside a frontmatter value (e.g. title: Atlas --- Q2 push) does
    # not corrupt the block boundaries.
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return {}
    # BH-03: malformed YAML must return {} rather than propagating YAMLError.
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
