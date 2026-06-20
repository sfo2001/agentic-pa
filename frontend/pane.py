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

# Human-readable gloss for the cryptic (A)–(D) priority codes (the Eisenhower
# quadrant each maps to). Surfaced as a hover title so the letter stays compact
# but its meaning is one hover away.
_PRIORITY_TITLE = {
    "A": "Urgent & important",
    "B": "Important, not urgent",
    "C": "Urgent, not important",
    "D": "Neither urgent nor important",
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

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
# "done" is excluded — it is rendered separately after the cap (see actions())
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
    # "Done today" — actions completed today, each offering a reopen button so an
    # accidental complete can be undone without a global git revert.
    done = view.get("done", [])
    if done:
        parts.append('<div class="bucket bucket-done"><h4>Done Today</h4>')
        for a in done:
            parts.append(_action_row(a, done=True))
        parts.append("</div>")
    return "".join(parts)


def _chip(text: str, cls: str) -> str:
    return f'<span class="chip {_esc(cls)}">{_esc(text)}</span>'


def _action_row(a: dict, *, done: bool = False) -> str:
    text = a.get("text", "")
    pri = a.get("priority") or ""
    aid = a.get("id")

    parts = ['<div class="action-row' + (" is-done" if done else "") + '">']
    # Priority badge — the letter stays, but its meaning is in the hover title
    # (and a colour class) instead of a bare "(A)" prefix.
    if pri:
        title = _PRIORITY_TITLE.get(pri, "")
        parts.append(
            f'<span class="pri pri-{_esc(pri)}" title="{_esc(title)}">{_esc(pri)}</span>'
        )
    parts.append(f'<span class="action-text">{_esc(text)}</span>')

    # Re-surface the structured fields the parser already extracted as readable
    # chips instead of leaving them invisible (due date, topics).
    due = a.get("due")
    if due:
        parts.append(_chip(f"Due {_human_date(due)}", "chip-due"))
    for topic in a.get("topics", []) or []:
        parts.append(_chip(topic, "chip-topic"))

    if aid:
        parts.append('<div class="ops">')
        if done:
            parts.append(
                f'<button data-op="reopen" data-id="{_esc(aid)}" data-value=""'
                f' class="task-op" title="Re-open this action">↺ Reopen</button>'
            )
        else:
            for p in ("A", "B", "C", "D"):
                parts.append(
                    f'<button data-op="reprioritize" data-id="{_esc(aid)}" data-value="{p}"'
                    f' class="task-op" title="Set priority {p} — {_esc(_PRIORITY_TITLE[p])}">{p}</button>'
                )
            parts.append(
                f'<button data-op="complete" data-id="{_esc(aid)}" data-value=""'
                f' class="task-op" title="Mark done">✓</button>'
            )
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _human_date(iso: str) -> str:
    """Format an ISO date (YYYY-MM-DD) as e.g. 'Jun 9'. Falls back to the raw
    string if it doesn't parse (cross-platform: no strftime %-d)."""
    try:
        d = datetime.date.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso
    return f"{_MONTHS[d.month - 1]} {d.day}"


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
