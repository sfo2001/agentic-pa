"""Structured proposal: parse + apply tests."""
import datetime
import tempfile
from pathlib import Path

import pytest

from frontend import proposal


def test_parse_fenced_json_block():
    text = (
        "Here is what I'd file:\n"
        "```json\n"
        '{"diary": "Worked on atlas.", "actions": ["(B) call vendor +hw t:2026-06-11 upd:2026-06-04"],'
        ' "topics": [{"slug": "atlas", "section": "## Current state", "text": "sync lag"}],'
        ' "meetings": []}\n'
        "```\n"
    )
    p = proposal.parse_proposal(text)
    assert p["diary"] == "Worked on atlas."
    assert p["actions"] == ["(B) call vendor +hw t:2026-06-11 upd:2026-06-04"]
    assert p["topics"][0]["slug"] == "atlas"
    assert p["meetings"] == []


def test_parse_defaults_missing_keys():
    p = proposal.parse_proposal('```json\n{"diary": "x"}\n```')
    assert p == {"diary": "x", "actions": [], "topics": [], "meetings": []}


def test_parse_raises_on_unparseable():
    import pytest
    with pytest.raises(proposal.ProposalError):
        proposal.parse_proposal("no json here at all")


def _root():
    return Path(tempfile.mkdtemp())


def test_apply_diary_appends_dated_section():
    root = _root()
    when = datetime.datetime(2026, 6, 4, 14, 30)
    proposal.apply_proposal(root, {"diary": "Morning on atlas.", "actions": [], "topics": [], "meetings": []}, now=when)
    body = (root / "diary" / "2026-06-04.md").read_text(encoding="utf-8")
    assert body.startswith("# Diary 2026-06-04")
    assert "## 14:30" in body
    assert "Morning on atlas." in body


def test_apply_diary_accretes_across_sweeps():
    root = _root()
    proposal.apply_proposal(root, {"diary": "first", "actions": [], "topics": [], "meetings": []},
                            now=datetime.datetime(2026, 6, 4, 9, 0))
    proposal.apply_proposal(root, {"diary": "second", "actions": [], "topics": [], "meetings": []},
                            now=datetime.datetime(2026, 6, 4, 14, 0))
    body = (root / "diary" / "2026-06-04.md").read_text(encoding="utf-8")
    assert body.count("# Diary 2026-06-04") == 1  # header once
    assert "## 09:00" in body and "## 14:00" in body
    assert body.index("first") < body.index("second")  # chronological


def test_apply_diary_skipped_when_empty():
    root = _root()
    proposal.apply_proposal(root, {"diary": "  ", "actions": [], "topics": [], "meetings": []},
                            now=datetime.datetime(2026, 6, 4, 14, 0))
    assert not (root / "diary").exists()


def test_apply_actions_appends_lines_with_trailing_newline():
    root = _root()
    (root / "tasks.todo.txt").write_text("(A) existing thing +foo upd:2026-06-01\n", encoding="utf-8")
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": ["(B) call vendor +hw t:2026-06-11 upd:2026-06-04",
                                   "(C) email bob @office upd:2026-06-04"],
         "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["actions"] == 2
    lines = (root / "tasks.todo.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "(A) existing thing +foo upd:2026-06-01"
    assert lines[1] == "(B) call vendor +hw t:2026-06-11 upd:2026-06-04"
    assert lines[2] == "(C) email bob @office upd:2026-06-04"


def test_apply_actions_creates_file_if_absent():
    root = _root()
    proposal.apply_proposal(root, {"diary": "", "actions": ["(A) x +y upd:2026-06-04"],
                                   "topics": [], "meetings": []}, now=datetime.datetime(2026, 6, 4))
    assert (root / "tasks.todo.txt").read_text(encoding="utf-8") == "(A) x +y upd:2026-06-04\n"


TOPIC_TEMPLATE = (
    "---\nslug: atlas\ntitle: Atlas\ntags: []\nstatus: active\n---\n"
    "## Overview\n\n## Current state\n\n## Open questions\n"
)


def test_apply_topic_appends_under_named_section():
    root = _root()
    (root / "topics").mkdir()
    (root / "topics" / "atlas.md").write_text(TOPIC_TEMPLATE, encoding="utf-8")
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [{"slug": "atlas", "section": "## Current state", "text": "sync lag suspected"}]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["topics"] == 1
    body = (root / "topics" / "atlas.md").read_text(encoding="utf-8")
    cur = body.index("## Current state")
    nxt = body.index("## Open questions")
    assert "sync lag suspected" in body[cur:nxt]  # inserted in the right section


def test_apply_topic_creates_file_from_template_when_absent():
    root = _root()
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [{"slug": "newtopic", "section": "## Overview", "text": "seed note"}]},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "topics" / "newtopic.md").read_text(encoding="utf-8")
    assert body.startswith("---\nslug: newtopic\n")
    assert "seed note" in body


def test_apply_meeting_writes_record_in_exact_format():
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "topics": [],
         "meetings": [{"slug": "atlas-sync", "title": "Atlas sync",
                        "topics": ["atlas"], "summary": "Discussed lag.",
                        "decisions": "Rebuild index.", "actions": "Owner: me.",
                        "raw": "raw notes here"}]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["meetings"] == 1
    body = (root / "meetings" / "2026-06-04" / "atlas-sync.md").read_text(encoding="utf-8")
    assert body.startswith("---\ndate: 2026-06-04\ntitle: Atlas sync\ntopics: [atlas]\n---\n")
    assert "## Summary\nDiscussed lag." in body
    assert "## Decisions\nRebuild index." in body
    assert "## Raw notes\nraw notes here" in body


def test_no_meeting_when_list_empty():
    root = _root()
    proposal.apply_proposal(root, {"diary": "x", "actions": [], "topics": [], "meetings": []},
                            now=datetime.datetime(2026, 6, 4))
    assert not (root / "meetings").exists()


# ── TDD-red: slug regex + action sanitization + list caps (Group A) ─────────


def test_apply_topic_rejects_traversal_slug():
    """A topic slug containing '..' or '/' must be rejected, not written."""
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [{"slug": "../opencode.json", "section": "## Current state", "text": "x"}]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["topics"] == 0
    # The applier should not have created topics/opencode.json (the slug
    # "../opencode.json" is rejected; the file at the literal traversal
    # path was never a write target in the first place).
    assert not (root / "opencode.json").exists()
    # And no topics/ directory was created (no successful topic writes).
    assert not (root / "topics").exists()


def test_apply_meeting_rejects_traversal_slug():
    """A meeting slug containing '..' must be rejected, not written."""
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "topics": [],
         "meetings": [{"slug": "../../etc/passwd", "title": "evil",
                        "summary": "x", "decisions": "", "actions": "", "raw": ""}]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["meetings"] == 0
    # No meetings/ tree created.
    assert not (root / "meetings").exists()


def test_apply_actions_strips_newline_injection():
    """An embedded newline in an action must NOT add a second action line.

    The threat: an LLM emits ``"x\n(A) smuggled"`` and the old code wrote
    both lines to tasks.todo.txt, so the user ended up with TWO actions
    when they confirmed only one. The fix flattens newlines to spaces
    so the action stays a single line — the smuggled text becomes part
    of the original action's prose, not a separate (A) entry.
    """
    root = _root()
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": ["(B) x +y upd:2026-06-04\n(A) smuggled +z upd:2026-06-04"],
         "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8")
    lines = body.splitlines()
    # Only ONE action line, not two — the smuggled (A) was not promoted.
    assert len(lines) == 1
    # The line still has the smuggled text (now flattened to a space) — that's
    # the expected user-visible outcome: they see the smuggled substring but
    # it is part of the original action's prose, not a separate (A) entry.
    assert "(A) smuggled" in body
    # And the line begins with the original (B) — never with the smuggled (A).
    assert lines[0].startswith("(B) ")


def test_apply_actions_strips_literal_backslash_n():
    """M-5: A literal two-char ``\\n`` (backslash-n) is flattened to space.

    The LLM might emit the escape sequence as a string (rather than a real
    newline byte) in its JSON output. The sanitizer must strip both forms
    so neither can smuggle a second line into tasks.todo.txt.
    """
    root = _root()
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": ["(B) x +y upd:2026-06-04\\n(A) smuggled +z upd:2026-06-04"],
         "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8")
    lines = body.splitlines()
    # Only one line, the smuggled (A) was flattened (the literal \n is
    # rendered as a space, not as a newline byte).
    assert len(lines) == 1
    assert lines[0].startswith("(B) ")


def test_apply_actions_strips_c0_and_unicode_line_separators():
    """L-1: NUL, the remaining C0 controls, and U+2028/U+2029/U+0085 are
    flattened to space — they shouldn't smuggle a second action line via a
    downstream parser that treats them as line breaks."""
    root = _root()
    # NUL + form feed + line separator + paragraph separator
    actions = [
        "(B) x +y upd:2026-06-04\x00(A) nul",
        "(B) x +y upd:2026-06-04\x0c(B) ff",
        "(B) x +y upd:2026-06-04\u2028(B) ls",
        "(B) x +y upd:2026-06-04\u2029(B) ps",
        "(B) x +y upd:2026-06-04\u0085(B) nel",
    ]
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": actions, "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8")
    # Exactly five lines (no smuggled entries).
    assert len(body.splitlines()) == 5
    # The smuggled priority markers (A) (B) survive but are flattened into the
    # original action's prose — they are NOT on a separate line.
    for tag in ("(A) nul", "(B) ff", "(B) ls", "(B) ps", "(B) nel"):
        assert tag in body
        # And no line in the file starts with one of the smuggled markers.
    for line in body.splitlines():
        assert not (line.startswith("(A) ") and "nul" in line and len(line) < 30)


def test_apply_caps_action_list_length():
    """More than MAX_ACTIONS actions must be silently dropped (DoS hardening)."""
    root = _root()
    big = [f"(B) a{i} +x upd:2026-06-04" for i in range(200)]
    summary = proposal.apply_proposal(
        root, {"diary": "", "actions": big, "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["actions"] <= 50  # MAX_ACTIONS
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8").splitlines()
    assert len(body) <= 50


def test_apply_topic_creates_quoted_yaml_frontmatter():
    """Topic frontmatter must YAML-quote the slug to prevent header break-out."""
    root = _root()
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [{"slug": "atlas", "section": "## Current state", "text": "x"}]},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "topics" / "atlas.md").read_text(encoding="utf-8")
    # Slug is YAML-quoted: slug: "atlas" (or uses safe_dump's block format)
    import yaml
    end = body.find("\n---", 4)
    fm = yaml.safe_load(body[4:end])
    assert fm["slug"] == "atlas"
    assert fm["title"] == "atlas"


# ── TDD-red: Pydantic sub-models + section literal (Group A continued) ──────


def test_sweep_confirm_rejects_section_outside_literal_set():
    """A section header not in the known literal set must raise ValidationError."""
    from pydantic import ValidationError

    from frontend.app import SweepConfirm
    with pytest.raises(ValidationError):
        SweepConfirm(
            proposal={
                "diary": "", "actions": [],
                "topics": [{"slug": "atlas", "section": "## Evil", "text": "x"}],
                "meetings": [],
            },
            capture="x.md", session="s", last_id="m",
        )


def test_sweep_confirm_caps_list_lengths_at_model_boundary():
    """SweepConfirm must reject topic lists > MAX_TOPICS / action lists > MAX_ACTIONS."""
    from pydantic import ValidationError

    from frontend.app import SweepConfirm
    with pytest.raises(ValidationError):
        SweepConfirm(
            proposal={
                "diary": "", "actions": [],
                "topics": [{"slug": f"t{i}", "section": "## Current state", "text": "x"}
                           for i in range(100)],  # > MAX_TOPICS
                "meetings": [],
            },
            capture="x.md", session="s", last_id="m",
        )


def test_sweep_confirm_rejects_malformed_slug_at_model_boundary():
    """A topic with a traversal slug must raise ValidationError (Pydantic catches it)."""
    from pydantic import ValidationError

    from frontend.app import SweepConfirm
    with pytest.raises(ValidationError):
        SweepConfirm(
            proposal={
                "diary": "", "actions": [],
                "topics": [{"slug": "../etc", "section": "## Current state", "text": "x"}],
                "meetings": [],
            },
            capture="x.md", session="s", last_id="m",
        )


# ── M-6: _SWEEP_SLUG boundary cases (64 ok / 65 reject / leading-hyphen / etc.) ─


@pytest.mark.parametrize("slug,should_accept", [
    ("a", True),                                  # single char, letter start
    ("1foo", True),                               # digit start allowed
    ("a" * 64, True),                             # 64 chars (upper bound inclusive)
    ("a" * 65, False),                            # 65 chars (over the cap)
    ("-foo", False),                              # leading hyphen (regex requires [a-z0-9])
    ("_foo", False),                              # leading underscore
    (".foo", False),                              # leading dot
    ("foo.bar", False),                           # dot in the middle
    ("foo/bar", False),                           # slash (path separator)
    ("foo\\bar", False),                          # backslash
    ("foo bar", False),                           # space
    ("FOO", False),                               # uppercase
    ("foo@bar", False),                           # @
    ("foo$bar", False),                           # shell metachar
    ("foo\nbar", False),                          # newline (smuggling vector)
    ("foo\x00bar", False),                        # NUL byte
])
def test_sweep_slug_boundary(slug, should_accept):
    """M-6: Pydantic regex/length boundary — 16 cases pin the contract."""
    from pydantic import ValidationError

    from frontend.app import SweepConfirm
    if should_accept:
        # Must not raise.
        SweepConfirm(
            proposal={"diary": "", "actions": [],
                     "topics": [{"slug": slug, "section": "## Current state", "text": "x"}],
                     "meetings": []},
            capture="x.md", session="s", last_id="m",
        )
    else:
        with pytest.raises(ValidationError):
            SweepConfirm(
                proposal={"diary": "", "actions": [],
                         "topics": [{"slug": slug, "section": "## Current state", "text": "x"}],
                         "meetings": []},
                capture="x.md", session="s", last_id="m",
            )


# ── TDD-red: parse_proposal raw_decode (Group F) ────────────────────────────


def test_parse_proposal_handles_brace_in_text_field():
    """A topic text containing '{x}' must not be cut short by the fence regex."""
    p = proposal.parse_proposal(
        '```json\n{"diary": "", "actions": [],'
        ' "topics": [{"slug": "atlas", "section": "## Current state",'
        '             "text": "config {x} looks wrong"}],'
        ' "meetings": []}\n```\n'
    )
    assert p["topics"][0]["text"] == "config {x} looks wrong"


# ── TDD-red: multi-topic meeting frontmatter (Group A, ISC-8) ───────────────


def test_apply_meeting_with_multiple_topics_uses_valid_yaml():
    """Multi-topic meeting frontmatter must parse as a YAML list, not bare tokens."""
    import yaml
    root = _root()
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "topics": [],
         "meetings": [{"slug": "atlas-sync", "title": "Atlas sync",
                        "topics": ["atlas", "hw", "ops"],
                        "summary": "x", "decisions": "", "actions": "", "raw": ""}]},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "meetings" / "2026-06-04" / "atlas-sync.md").read_text(encoding="utf-8")
    end = body.find("\n---", 4)
    fm = yaml.safe_load(body[4:end])
    assert fm["topics"] == ["atlas", "hw", "ops"]


# ── TDD-red: ## Open actions regeneration (Group E, ISC-15) ─────────────────


def test_apply_topic_regenerates_open_actions_block():
    """After _apply_topics, the topic's ## Open actions block reflects current tasks."""
    root = _root()
    (root / "topics").mkdir()
    (root / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\n## Current state\n\n"
        "## Open actions (as of 2026-05-30)\n\n- (B) stale action\n",
        encoding="utf-8",
    )
    (root / "tasks.todo.txt").write_text(
        "(B) call vendor +atlas t:2026-06-11 upd:2026-06-04\n"
        "(C) email bob @office upd:2026-06-04\n",
        encoding="utf-8",
    )
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [{"slug": "atlas", "section": "## Current state", "text": "new note"}]},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "topics" / "atlas.md").read_text(encoding="utf-8")
    assert "## Open actions (as of 2026-06-04)" in body
    # The atlas snapshot only contains actions tagged +atlas.
    assert "(B) call vendor +atlas" in body
    assert "(C) email bob" not in body  # no +atlas tag → not in this topic
    assert "(B) stale action" not in body  # the old snapshot is replaced


# ── M-3: _is_valid_section must require a real \d{4}-\d{2}-\d{2} in the snapshot form ─


def test_apply_topic_rejects_section_with_malformed_date():
    """M-3: a section header of the form ``## Open actions (as of …)`` with
    a missing/malformed date is NOT a valid snapshot — the applier drops it.

    Previously the check was just ``startswith(prefix) and endswith(")")``,
    which let ``## Open actions (as of ../../etc/passwd)`` and
    ``## Open actions (as of )`` slip through and land as a topic section.
    """
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [
             {"slug": "atlas", "section": "## Open actions (as of ../../etc/passwd)", "text": "x"},
             {"slug": "atlas2", "section": "## Open actions (as of )", "text": "x"},
         ]},
        now=datetime.datetime(2026, 6, 4),
    )
    # Neither malicious section landed.
    assert summary["topics"] == 0
    assert not (root / "topics" / "atlas.md").exists()
    assert not (root / "topics" / "atlas2.md").exists()


def test_apply_topic_accepts_section_with_valid_date():
    """M-3 (positive): ``## Open actions (as of YYYY-MM-DD)`` IS accepted."""
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [],
         "topics": [
             {"slug": "atlas", "section": "## Open actions (as of 2026-06-04)", "text": "x"},
         ]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["topics"] == 1


# ── LOW-2: apply_proposal rejects non-dict proposal ─────────────────────────


def test_apply_proposal_rejects_non_dict():
    """LOW-2: apply_proposal must raise ProposalValidationError when given
    a non-dict value (defense against a corrupt payload at the apply layer).
    """
    root = _root()
    with pytest.raises(proposal.ProposalValidationError, match="proposal is not a dict"):
        proposal.apply_proposal(root, "not a dict")
