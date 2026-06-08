"""SSR island rendering — HTML fragments for the Actions / Diary / Brief / Artifact panes.

Each function returns a complete HTML fragment (no <html>/<body> wrapper) designed
for htmx swapping into ``#pane-body``.
"""
from __future__ import annotations

import datetime
import html
from pathlib import Path

from agenda import engine
from frontend.render import MAX_DIARY_RENDER_BYTES, render_markdown

# Single source of truth for the agenda bucket order/labels and the render cap.
# ``frontend.app`` imports these so the JSON ``/api/actions`` endpoint and the
# SSR ``/api/pane/actions`` fragment can never drift apart.
BUCKET_LABEL = {
    "do_now": "Do Now",
    "overdue": "Overdue",
    "schedule": "Schedule",
    "resurfacing": "Resurfacing",
    "stale_important": "Stale & Important",
}
BUCKET_ORDER = ["do_now", "overdue", "schedule", "resurfacing", "stale_important"]
MAX_ACTIONS_RENDER = 500


def cap_buckets(view: dict) -> tuple[dict, bool]:
    """Slice the agenda view down to ``MAX_ACTIONS_RENDER`` total actions.

    Returns ``(buckets, truncated)`` preserving ``BUCKET_ORDER``. Shared by the
    JSON endpoint and the SSR fragment so both apply the identical cap.
    """
    buckets = {k: view[k] for k in BUCKET_ORDER}
    total = sum(len(v) for v in buckets.values())
    truncated = total > MAX_ACTIONS_RENDER
    if truncated:
        seen = 0
        for k in BUCKET_ORDER:
            room = max(0, MAX_ACTIONS_RENDER - seen)
            buckets[k] = buckets[k][:room]
            seen += len(buckets[k])
    return buckets, truncated


def actions(notes_root: Path) -> str:
    view = engine.today(notes_root)
    buckets, truncated = cap_buckets(view)
    parts: list[str] = []
    any_bucket = False
    for key in BUCKET_ORDER:
        items = buckets[key]
        if not items:
            continue
        any_bucket = True
        label = BUCKET_LABEL.get(key, key)
        parts.append(f'<div class="bucket bucket-{_esc(key)}"><h4>{_esc(label)}</h4>')
        for a in items:
            parts.append(_action_row(a))
        parts.append("</div>")
    if not any_bucket:
        parts.append('<p class="pane-empty">No open actions.</p>')
    if truncated:
        parts.append(
            f'<p class="pane-empty">Showing the first {MAX_ACTIONS_RENDER} actions.</p>'
        )
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
            f' class="task-op">✓</button>'
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
        return f'<p class="pane-empty">Today\'s diary is large — open <code>diary/{_esc(name)}</code> from chat.</p>'
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
    """Full HTML escape for text and double-quoted-attribute contexts.

    Delegates to ``html.escape`` (escapes ``& < > " '``) rather than a partial
    hand-rolled replacer — the previous version omitted ``>``.
    """
    return html.escape(s, quote=True)
