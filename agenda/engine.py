from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from agenda.models import Action
from agenda.parser import parse_frontmatter, parse_task_file

STALE_ITEM_DAYS = 7
STALE_TOPIC_DAYS = 21


def _as_date(value) -> date | None:
    """Coerce a YAML date/datetime to a plain date; None for anything else."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _as_topic_list(value) -> list[str]:
    """Normalise a frontmatter topics value to a list of slug strings.

    YAML may parse ``topics: project-atlas`` as a plain string rather than a
    list.  Iterating a string gives characters, not slugs (BH-09, BH-10).
    """
    if isinstance(value, list):
        return [s.strip() if isinstance(s, str) else s for s in value]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


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
    """Return agenda buckets for the given date.

    Buckets are **non-exclusive by design** — e.g. an overdue A-item appears in
    both ``do_now`` and ``overdue``; consumers should de-duplicate if rendering a
    flat list.
    """
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


def _topics(notes_root: Path) -> list[dict]:
    topics_dir = Path(notes_root) / "topics"
    if not topics_dir.is_dir():
        return []
    out = []
    for path in sorted(topics_dir.glob("*.md")):
        fm = parse_frontmatter(path)
        if isinstance(fm.get("slug"), str) and fm["slug"]:
            out.append(fm)
    return out


def _meeting_dates_by_topic(notes_root: Path) -> dict[str, list[date]]:
    meetings_dir = Path(notes_root) / "meetings"
    by_topic: dict[str, list[date]] = {}
    if not meetings_dir.is_dir():
        return by_topic
    for path in meetings_dir.rglob("*.md"):
        fm = parse_frontmatter(path)
        mdate = _as_date(fm.get("date"))
        if mdate is None:
            continue
        for slug in _as_topic_list(fm.get("topics")):
            by_topic.setdefault(slug, []).append(mdate)
    return by_topic


def review(notes_root: Path, on: date | None = None) -> dict:
    """Return the weekly review dict for the given date.

    Keys returned:
    - ``date``: ISO-formatted review date.
    - ``topics``: list of per-topic dicts, each carrying ``open_action_count``
      (a count, not the list — callers wanting the full list use ``topic(slug)``).
    - ``stale_topics``: slugs of topics not met in >21 days.
    - ``ticklers_this_week``: actions whose tickler date falls in the coming 7 days.
    - ``suggested_promotions``: deferred (returns ``[]`` for now — see design §5.1).
    """
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
        "suggested_promotions": [],
    }


def _recent_meetings(notes_root: Path, slug: str, limit: int = 5) -> list[dict]:
    meetings_dir = Path(notes_root) / "meetings"
    found = []
    if meetings_dir.is_dir():
        for path in meetings_dir.rglob("*.md"):
            fm = parse_frontmatter(path)
            mdate = _as_date(fm.get("date"))
            if slug in _as_topic_list(fm.get("topics")) and mdate is not None:
                try:
                    found.append(
                        {
                            "date": mdate.isoformat(),
                            "title": fm.get("title", path.stem),
                            "path": str(path.relative_to(notes_root)),
                        }
                    )
                except ValueError:
                    continue
    found.sort(key=lambda m: m["date"], reverse=True)
    return found[:limit]


def topic(notes_root: Path, slug: str, on: date | None = None) -> dict:
    # `on` is accepted for signature symmetry with today()/review() and reserved for
    # future date-filtered topic views; current topic views are date-agnostic.
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
