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
    assert result["schedule"] == []
    assert result["resurfacing"] == []
    assert result["overdue"] == []


# ── BH-33: Pattern N — today() uses date.today() when on is None ─────────────


def test_bh33_today_defaults_to_real_clock(tmp_path):
    """BH-33: today() calls ``date.today()`` when ``on`` is None (the default),
    bypassing the injectable parameter. This means tests that don't pass
    ``on=...`` get the real system date (non-deterministic).

    The injectable clock (``on=``) is the public API for determinism in tests.
    The default route cannot be overridden without ``freezegun`` or similar."""
    from datetime import date as real_date
    result = today(tmp_path)  # No on= → uses date.today()
    assert result["date"] == real_date.today().isoformat(), (
        "Without on=, today() uses the real clock date.today()"
    )
