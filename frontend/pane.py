"""SSR island rendering — HTML fragments for the Actions / Diary / Brief / Artifact panes.

Each function returns a complete HTML fragment (no <html>/<body> wrapper) designed
for htmx swapping into ``#pane-body``.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from agenda import engine
from frontend.render import MAX_DIARY_RENDER_BYTES, render_markdown

_BUCKET_LABEL = {
    "do_now": "Do Now",
    "overdue": "Overdue",
    "schedule": "Schedule",
    "resurfacing": "Resurfacing",
    "stale_important": "Stale & Important",
}
_BUCKET_ORDER = ["do_now", "overdue", "schedule", "resurfacing", "stale_important"]


def actions(notes_root: Path) -> str:
    view = engine.today(notes_root)
    parts: list[str] = []
    any_bucket = False
    for key in _BUCKET_ORDER:
        items = view[key]
        if not items:
            continue
        any_bucket = True
        label = _BUCKET_LABEL.get(key, key)
        parts.append(f'<div class="bucket bucket-{key}"><h4>{label}</h4>')
        for a in items:
            parts.append(_action_row(a))
        parts.append("</div>")
    if not any_bucket:
        parts.append('<p class="pane-empty">No open actions.</p>')
    return "".join(parts)


def _action_row(a: dict) -> str:
    text = a.get("text", "")
    pri = a.get("priority", "")
    label = f"({pri}) {text}" if pri else text
    aid = a.get("id")
    parts = [f'<div class="action-row"><span>{_esc(label)}</span>']
    if aid:
        parts.append('<div class="ops">')
        for p in ("A", "B", "C", "D"):
            parts.append(
                f'<button data-op="reprioritize" data-id="{_esc(aid)}" data-value="{p}"'
                f' class="task-op">{p}</button>'
            )
        parts.append(
            f'<button data-op="complete" data-id="{_esc(aid)}" data-value=""'
            f' class="task-op">\u2713</button>'
        )
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def diary(notes_root: Path) -> str:
    name = f"{datetime.date.today():%Y-%m-%d}.md"
    path = notes_root / "diary" / name
    if not path.is_file():
        return '<p class="pane-empty">No diary today.</p>'
    if path.stat().st_size > MAX_DIARY_RENDER_BYTES:
        return f'<p class="pane-empty">Today\'s diary is large — open <code>diary/{name}</code> from chat.</p>'
    text = path.read_text(encoding="utf-8", errors="replace")
    return render_markdown(text)


def brief(notes_root: Path) -> str:
    name = f"{datetime.date.today():%Y-%m-%d}-daily.md"
    path = notes_root / "briefs" / name
    if not path.is_file():
        return '<p class="pane-empty">No brief for today yet. Ask in chat or click <strong>Daily Brief</strong> above.</p>'
    text = path.read_text(encoding="utf-8", errors="replace")
    return render_markdown(text)


def artifact() -> str:
    return '<p class="pane-empty">Nothing presented yet.</p>'


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace("'", "&#39;")
