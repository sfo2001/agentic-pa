from datetime import date

from agenda.engine import _as_date, topic

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
    assert result["ticklers"] == []


def test_recent_meetings_capped_at_five(tmp_path):
    """With 6 meeting files for a topic, only the 5 newest are returned, newest first."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "cap-topic.md").write_text(
        "---\nslug: cap-topic\ntitle: Cap Topic\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    dates = [
        "2026-05-01",
        "2026-05-05",
        "2026-05-10",
        "2026-05-15",
        "2026-05-20",
        "2026-05-25",  # newest
    ]
    for d in dates:
        f = tmp_path / "meetings" / f"{d}.md"
        f.write_text(
            f"---\ndate: {d}\ntitle: Meeting {d}\ntopics: [cap-topic]\n---\n",
            encoding="utf-8",
        )

    result = topic(tmp_path, "cap-topic", on=TODAY)
    meetings = result["recent_meetings"]
    assert len(meetings) == 5
    # Newest first
    assert meetings[0]["date"] == "2026-05-25"
    assert meetings[4]["date"] == "2026-05-05"
    # Oldest (2026-05-01) must be excluded
    dates_returned = [m["date"] for m in meetings]
    assert "2026-05-01" not in dates_returned


# ---------------------------------------------------------------------------
# BH-10 regression: scalar `topics: project-atlas` in meeting frontmatter
# must use list membership, not substring containment.
# ---------------------------------------------------------------------------

# ── BH-32: Pattern I — _as_topic_list drops bool YAML (true/false) ────────────


def test_bh32_bool_topic_value_silently_excludes_meeting(tmp_path):
    """BH-32: A meeting with ``topics: true`` (YAML bool) is silently
    excluded from all topic views because ``_as_topic_list(True)``
    returns ``[]``. No error or log is generated."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "m.md").write_text(
        "---\ndate: 2026-05-28\ntitle: M\ntopics: true\n---\n",
        encoding="utf-8",
    )

    result = topic(tmp_path, "project-atlas", on=date(2026, 5, 30))
    assert len(result["recent_meetings"]) == 0, (
        "Meeting with topics: true was not matched (expected — bool is silently dropped)"
    )


# ── BH-35: Pattern I — _as_topic_list preserves non-str items silently ────────


def test_bh35_topic_list_with_numeric_item_silently_excluded(tmp_path):
    """BH-35: When meeting frontmatter has ``topics: [42, project-atlas]``,
    the entry ``42`` is preserved by ``_as_topic_list`` (no type filtering).
    In subsequent matching, integer 42 never matches string slug
    ``"project-atlas"`` — the meeting IS found (it does match) because
    the list also contains ``"project-atlas"``. This documents the
    permissive behavior: non-string items pass through silently."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "m.md").write_text(
        "---\ndate: 2026-05-28\ntitle: M\ntopics: [42, \"project-atlas\"]\n---\n",
        encoding="utf-8",
    )

    result = topic(tmp_path, "project-atlas", on=date(2026, 5, 30))
    assert len(result["recent_meetings"]) == 1, (
        "Meeting with mixed-type topics list should still match string slugs"
    )


def test_scalar_topics_meeting_appears_in_correct_slug(tmp_path):
    """BH-10 (a): a meeting with scalar topics: project-atlas shows in recent_meetings."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas Programme\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "scalar.md").write_text(
        "---\ndate: 2026-05-28\ntitle: Atlas Scalar\ntopics: project-atlas\n---\n",
        encoding="utf-8",
    )

    result = topic(tmp_path, "project-atlas", on=TODAY)
    # Before fix: slug "project-atlas" in "project-atlas" is True (str in str)
    # but this is accidental — the real issue surfaces in (b) below.
    # This assertion confirms the meeting IS present for the correct slug.
    assert len(result["recent_meetings"]) == 1
    assert result["recent_meetings"][0]["title"] == "Atlas Scalar"


# ── BH-27: Pattern O — _as_date() AttributeError on unexpected types ─────────


def test_bh27_as_date_handles_non_date_types():
    """BH-27: _as_date() calls ``value.date()`` and ``isinstance(value, date)``
    in that order. For objects that have a ``.date()`` method but are NOT
    ``datetime`` (e.g. a pandas Timestamp or a custom class), ``isinstance(value, datetime)``
    is False, but ``isinstance(value, date)`` is also False if it doesn't inherit
    from ``date`` — so the function falls through to ``return None``.

    The actual risk: a type that IS ``datetime`` but also not (e.g. sqlalchemy's
    ``DateTime`` types) — but the REAL Pattern O bug is that the function accepts
    ANY value (no type guard) and silently returns None for all unexpected types.
    This means a YAML frontmatter ``date: not-really-a-date`` is silently skipped
    with no log."""
    # Note: the existing test_non_date_meeting_skipped already covers scalar strings
    # This test documents the behavior: unexpected types → None (no crash, no log)
    assert _as_date(42) is None
    assert _as_date("2026-01-01") is None  # string not coerced
    assert _as_date([2026, 1, 1]) is None
    assert _as_date(None) is None


# ── BH-20: Pattern I — _as_topic_list() doesn't strip whitespace on slug ─────


def test_bh20_whitespace_in_topic_value_causes_slug_mismatch(tmp_path):
    """BH-20: When frontmatter has ``topics: " project-atlas "`` (with leading
    or trailing whitespace), ``_as_topic_list()`` returns ``[" project-atlas "]``
    with the spaces preserved. The slug lookup in ``_filter_topics`` uses exact
    string matching (``slug == candidate``), so the meeting never matches the
    topic."""

    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    # topics value has leading whitespace — _as_topic_list keeps it
    (tmp_path / "meetings" / "m.md").write_text(
        "---\ndate: 2026-05-28\ntitle: M\ntopics: \" project-atlas\"\n---\n",
        encoding="utf-8",
    )

    result = topic(tmp_path, "project-atlas", on=date(2026, 5, 30))
    # CORRECT behavior: " project-atlas" should be treated as "project-atlas"
    # Current bug: _as_topic_list(" project-atlas") → [" project-atlas"]
    # and " project-atlas" != "project-atlas" → no match
    assert len(result["recent_meetings"]) == 1, (
        "Meeting with whitespace in topics value was silently excluded"
    )


def test_scalar_topics_meeting_absent_for_substring_slug(tmp_path):
    """BH-10 (b): a meeting with scalar topics: project-atlas must NOT appear for slug 'atlas'."""
    (tmp_path / "tasks.todo.txt").write_text("", encoding="utf-8")
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "topics" / "project-atlas.md").write_text(
        "---\nslug: project-atlas\ntitle: Atlas Programme\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "meetings").mkdir()
    # Meeting belongs to project-atlas (scalar), NOT atlas
    (tmp_path / "meetings" / "scalar.md").write_text(
        "---\ndate: 2026-05-28\ntitle: Atlas Scalar\ntopics: project-atlas\n---\n",
        encoding="utf-8",
    )

    result = topic(tmp_path, "atlas", on=TODAY)
    # Before fix: "atlas" in "project-atlas" is True → false-positive match
    assert result["recent_meetings"] == []
