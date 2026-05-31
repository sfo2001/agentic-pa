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


def test_invalid_date_token_parses_to_none():
    a = parse_task_line("(A) Thing +x due:not-a-date upd:also-bad")
    assert a.due is None
    assert a.updated is None


def test_c_and_d_quadrants():
    assert parse_task_line("(C) x").quadrant == "urgent_not_important"
    assert parse_task_line("(D) x").quadrant == "neither"


# ── BH-30: Pattern C/I — invalid date tokens consumed from description ───────


def test_bh30_invalid_date_tokens_consumed_from_description():
    """BH-30: parse_task_line() removes tokens like ``due:not-a-date``
    from the description even though the value doesn't parse as a date.
    The token vanishes from the action without warning (data-loss bug).

    Correct behavior: invalid date tokens should remain in the description
    so the user can see what was originally written."""
    a = parse_task_line("(A) Sign off +x due:not-a-date")
    # The correct behavior: description should preserve the unrecognised token
    assert "due:not-a-date" in a.description, (
        "Invalid date token 'due:not-a-date' was silently consumed from description"
    )
