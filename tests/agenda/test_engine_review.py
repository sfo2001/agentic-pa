from datetime import date

import pytest

from agenda.engine import review, topic

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
    assert result["suggested_promotions"] == []


def test_datetime_frontmatter_does_not_crash(tmp_path):
    """Regression: YAML timestamps parse as datetime objects (subclass of date).

    _as_date() must coerce them to plain date so date arithmetic does not crash
    and the ISO string contains no time component.
    """
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "dt-topic.md").write_text(
        "---\nslug: dt-topic\ntitle: DT Topic\nstatus: active\n---\n",
        encoding="utf-8",
    )
    # Write the meeting date with a time component so YAML parses it as datetime
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "dt-meeting.md").write_text(
        "---\ndate: 2026-05-29 10:00:00\ntitle: DT Meeting\ntopics: [dt-topic]\n---\n",
        encoding="utf-8",
    )

    # Must not raise
    result = review(tmp_path, on=TODAY)

    topics = {t["slug"]: t for t in result["topics"]}
    assert topics["dt-topic"]["last_meeting"] == "2026-05-29"

    # Also verify topic() strips the time from recent_meetings entries
    t_result = topic(tmp_path, "dt-topic", on=TODAY)
    assert t_result["recent_meetings"][0]["date"] == "2026-05-29"


def test_non_date_meeting_skipped(tmp_path):
    """A meeting with date: 'not a date' (string) is skipped; topic last_meeting is None."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "bad-date-topic.md").write_text(
        "---\nslug: bad-date-topic\ntitle: Bad Date Topic\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "bad.md").write_text(
        '---\ndate: "not a date"\ntitle: Bad Meeting\ntopics: [bad-date-topic]\n---\n',
        encoding="utf-8",
    )

    result = review(tmp_path, on=TODAY)
    topics = {t["slug"]: t for t in result["topics"]}
    assert topics["bad-date-topic"]["last_meeting"] is None


def test_stale_boundary_exactly_21_days(tmp_path):
    """A topic whose only meeting is exactly 21 days before TODAY is NOT stale."""
    # TODAY = 2026-05-30; 21 days before = 2026-05-09
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "boundary-topic.md").write_text(
        "---\nslug: boundary-topic\ntitle: Boundary Topic\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "boundary.md").write_text(
        "---\ndate: 2026-05-09\ntitle: Boundary Meeting\ntopics: [boundary-topic]\n---\n",
        encoding="utf-8",
    )

    result = review(tmp_path, on=TODAY)
    topics = {t["slug"]: t for t in result["topics"]}
    assert topics["boundary-topic"]["last_meeting"] == "2026-05-09"
    assert topics["boundary-topic"]["stale"] is False


# ---------------------------------------------------------------------------
# BH-28: Pattern I — list-valued slug crashes review() on unhashable type
# ---------------------------------------------------------------------------


def test_bh28_list_slug_does_not_crash_review(tmp_path):
    """BH-28: _topics() accepts any truthy ``slug`` value, including YAML
    lists. If a topic file has ``slug: [a, b]`` (a YAML list), ``fm["slug"]``
    is ``["a", "b"]`` (a list). Then ``review()`` uses this as a dict key in
    ``meeting_dates.get(slug, [])``, raising ``TypeError: unhashable type: 'list'``.

    _topics() should validate that ``slug`` is a string."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "bad-slug.md").write_text(
        "---\nslug: [a, b]\ntitle: Bad Slug\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()

    # Must not raise TypeError
    try:
        result = review(tmp_path, on=TODAY)
    except TypeError as exc:
        pytest.fail(f"review() crashed with TypeError due to list slug: {exc}")

    # The topic with bad slug should be handled gracefully
    slugs = [t["slug"] for t in result["topics"]]
    assert "a" not in slugs or "b" not in slugs, (
        "List slug should not be accepted as a topic"
    )


# ---------------------------------------------------------------------------
# BH-09 regression: scalar `topics: project-atlas` in meeting frontmatter
# must be treated as a single-item list, not iterated over as characters.
# ---------------------------------------------------------------------------

def test_scalar_topics_in_meeting_populates_last_meeting(tmp_path):
    """BH-09: topics: project-atlas (scalar) must register the meeting date."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas Programme\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    # Scalar string, NOT a YAML list
    (tmp_path / "meetings" / "scalar-meeting.md").write_text(
        "---\ndate: 2026-05-28\ntitle: Atlas Scalar Sync\ntopics: project-atlas\n---\n",
        encoding="utf-8",
    )

    result = review(tmp_path, on=TODAY)
    topics = {t["slug"]: t for t in result["topics"]}

    # Before fix: chars of "project-atlas" are iterated → slug never matched
    # → last_meeting is None and stale is True.
    assert topics["project-atlas"]["last_meeting"] == "2026-05-28"
    assert topics["project-atlas"]["stale"] is False
