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
    import re as _re
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
    # New lines are stamped with a fresh id: — assert the prefix survives and
    # the line ends with a valid 6-char base36 id.
    assert lines[1].startswith("(B) call vendor +hw t:2026-06-11 upd:2026-06-04 ")
    assert _re.search(r" id:[a-z0-9]{6}$", lines[1])
    assert lines[2].startswith("(C) email bob @office upd:2026-06-04 ")
    assert _re.search(r" id:[a-z0-9]{6}$", lines[2])


def test_apply_actions_creates_file_if_absent():
    import re as _re
    root = _root()
    proposal.apply_proposal(root, {"diary": "", "actions": ["(A) x +y upd:2026-06-04"],
                                   "topics": [], "meetings": []}, now=datetime.datetime(2026, 6, 4))
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8")
    # Action text preserved; the applier stamped a fresh id: at end of line.
    assert body.startswith("(A) x +y upd:2026-06-04 ")
    assert _re.search(r" id:[a-z0-9]{6}\n$", body)


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
    assert body.startswith("---\ndate: 2026-06-04\ntitle: Atlas sync\ntopics:\n- atlas\n---\n")
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


def test_apply_actions_preserves_literal_backslash_n():
    """M-4: A literal two-char ``\\n`` (backslash-n) is preserved as text.

    The sanitizer strips real control characters but does NOT strip the
    two-character escape sequence ``\n`` (backslash + n) — that is
    legitimate content (e.g. a Windows path ``C:\\new``). A literal
    backslash-n cannot smuggle a line break into tasks.todo.txt because
    the file format splits on real newline bytes, not on the text ``\n``.
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
    # Still one line (no real newline injected), but the literal \n text
    # survives — it is not flattened.
    assert len(lines) == 1
    assert "\\n(A) smuggled" in lines[0]
    assert lines[0].startswith("(B) ")


def test_apply_actions_strips_c0_and_unicode_line_separators():
    """L-1: NUL, C0 controls, C1 controls (\x80-\x9f), and U+2028/U+2029 are
    flattened to space — they shouldn't smuggle a second action line via a
    downstream parser that treats them as line breaks."""
    root = _root()
    # NUL + form feed + line separator + paragraph separator + C1 controls
    actions = [
        "(B) x +y upd:2026-06-04\x00(A) nul",
        "(B) x +y upd:2026-06-04\x0c(B) ff",
        "(B) x +y upd:2026-06-04\u2028(B) ls",
        "(B) x +y upd:2026-06-04\u2029(B) ps",
        "(B) x +y upd:2026-06-04\u0085(B) nel",
        "(B) x +y upd:2026-06-04\x80(B) c1_80",
        "(B) x +y upd:2026-06-04\x9f(B) c1_9f",
    ]
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": actions, "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8")
    # Exactly seven lines (no smuggled entries).
    assert len(body.splitlines()) == 7
    # The smuggled priority markers survive but are flattened into the
    # original action's prose — they are NOT on a separate line.
    for tag in ("(A) nul", "(B) ff", "(B) ls", "(B) ps", "(B) nel", "(B) c1_80", "(B) c1_9f"):
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


# ── M2: apply_proposal snapshot/rollback contract ────────────────────────────


def test_apply_proposal_rolls_back_on_topics_failure(monkeypatch):
    """M2 HIGH: when ``_apply_topics`` raises mid-apply, every snapshotted
    file is restored to its pre-apply byte-for-byte state, newly-created
    files are unlinked, and the original exception propagates.

    The apply order is diary → actions → topics → meetings; we inject the
    failure at topics so the diary write and the actions append have
    already landed and need to be rolled back.
    """
    import frontend.proposal as proposal_mod

    root = _root()
    (root / "tasks.todo.txt").write_text("OLD line\n", encoding="utf-8")
    diary_path = root / "diary" / "2026-06-04.md"
    topic_path = root / "topics" / "atlas.md"

    def _boom(_notes_root, _topics, _now):
        raise RuntimeError("simulated topics failure")

    monkeypatch.setattr(proposal_mod, "_apply_topics", _boom)

    with pytest.raises(RuntimeError, match="simulated topics failure"):
        proposal.apply_proposal(
            root,
            {"diary": "first sweep", "actions": ["(B) new +x upd:2026-06-04"],
             "topics": [{"slug": "atlas", "section": "## Current state", "text": "x"}],
             "meetings": []},
            now=datetime.datetime(2026, 6, 4, 14, 30),
        )

    # tasks.todo.txt: pre-existing file, content restored byte-for-byte.
    assert (root / "tasks.todo.txt").read_text(encoding="utf-8") == "OLD line\n"
    # diary/<today>.md: newly created by _append_diary, must be unlinked.
    assert not diary_path.exists()
    # topics/atlas.md: never created because _apply_topics raised before writing.
    assert not topic_path.exists()
    # No orphan parent directories left behind.
    assert not (root / "diary").exists()
    # The summary is not returned on failure (the call raised).


def test_apply_proposal_rolls_back_meetings_when_present(monkeypatch):
    """M2 MEDIUM: meeting files are now snapshotted too — if _apply_meetings
    fails after a meeting has been written, the meeting file is unlinked and
    its parent day dir is cleaned up iff it didn't exist before.
    """
    import frontend.proposal as proposal_mod

    root = _root()
    day_dir = root / "meetings" / "2026-06-04"
    meeting_path = day_dir / "atlas-sync.md"

    def _boom(_notes_root, _meetings, _now):
        raise RuntimeError("simulated meetings failure")

    monkeypatch.setattr(proposal_mod, "_apply_meetings", _boom)

    with pytest.raises(RuntimeError, match="simulated meetings failure"):
        proposal.apply_proposal(
            root,
            {"diary": "", "actions": [],
             "topics": [],
             "meetings": [{"slug": "atlas-sync", "title": "Atlas sync",
                            "summary": "x", "decisions": "", "actions": "", "raw": ""}]},
            now=datetime.datetime(2026, 6, 4, 14, 30),
        )
    # The meeting file was never created (the raise fired before write_text).
    assert not meeting_path.exists()
    # The day dir was never created, so there's nothing to rmdir.
    assert not day_dir.exists()


def test_apply_proposal_rolls_back_preexisting_meeting_on_partial_failure(monkeypatch):
    """M2 MEDIUM (deep): if the meetings list contains a slug whose file
    ALREADY exists (overwrite case) and a later meeting raises, the
    pre-existing file is restored byte-for-byte by the rollback.
    """
    import frontend.proposal as proposal_mod

    root = _root()
    day_dir = root / "meetings" / "2026-06-04"
    day_dir.mkdir(parents=True)
    existing_path = day_dir / "atlas-sync.md"
    original_body = "---\ndate: 2026-06-04\ntitle: ORIGINAL\n---\n## Summary\nold\n"
    existing_path.write_text(original_body, encoding="utf-8")

    # Create a second meeting in the SAME apply that will fail — but the
    # current `_apply_meetings` loops sequentially; if the second iteration
    # raises, the first iteration's write must be rolled back.
    real_apply = proposal_mod._apply_meetings
    calls = {"n": 0}

    def _explode_on_second(notes_root, meetings, now):
        for m in meetings:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated second-meeting failure")
            # Use the real function for the first call so the file lands.
            return_value = real_apply(notes_root, [m], now)
        return return_value

    monkeypatch.setattr(proposal_mod, "_apply_meetings", _explode_on_second)

    with pytest.raises(RuntimeError, match="simulated second-meeting failure"):
        proposal.apply_proposal(
            root,
            {"diary": "", "actions": [],
             "topics": [],
             "meetings": [
                 {"slug": "atlas-sync", "title": "Atlas sync",
                  "summary": "first", "decisions": "", "actions": "", "raw": ""},
                 {"slug": "ops-sync", "title": "Ops sync",
                  "summary": "second", "decisions": "", "actions": "", "raw": ""},
             ]},
            now=datetime.datetime(2026, 6, 4, 14, 30),
        )
    # The pre-existing file is restored to its original content.
    assert existing_path.read_text(encoding="utf-8") == original_body


# ── LOW: safe_topics / safe_meetings defensive branches (the new trust
#    boundary after M3 removed the in-apply re-checks) ────────────────────────


@pytest.mark.parametrize("bad_topic", [
    None,                                            # non-dict
    "not a dict",                                    # non-dict (str)
    {"slug": "", "section": "## Current state", "text": "x"},   # empty slug
    {"slug": "ok", "section": "## Current state", "text": ""},   # empty text
    {"slug": "../etc", "section": "## Current state", "text": "x"},  # bad slug
    {"slug": "ok", "section": "## Evil", "text": "x"},            # bad section
    {"slug": "ok", "section": "## Current state"},               # missing text
])
def test_safe_topics_drops_malformed_items(bad_topic):
    """LOW: M3 removed the in-apply re-checks; the *only* validation layer
    for topics is now ``safe_topics`` in ``apply_proposal``. Each of these
    inputs must be silently dropped, leaving ``summary["topics"] == 0``.
    """
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "meetings": [], "topics": [bad_topic]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["topics"] == 0
    assert not (root / "topics").exists()


@pytest.mark.parametrize("bad_meeting", [
    None,
    "not a dict",
    {},  # missing slug
    {"slug": "", "title": "x"},
    {"slug": "../etc", "title": "evil"},
    {"slug": "ok/with/slash"},
    {"slug": "ok with space"},
])
def test_safe_meetings_drops_malformed_items(bad_meeting):
    """LOW: same coverage for the meeting trust boundary. Note: ``{"slug": "ok"}``
    alone IS a valid meeting (title defaults to slug) so it is not in this list;
    the unit tests above (``test_apply_meeting_writes_record_in_exact_format``)
    pin the positive path."""
    root = _root()
    summary = proposal.apply_proposal(
        root,
        {"diary": "", "actions": [], "topics": [], "meetings": [bad_meeting]},
        now=datetime.datetime(2026, 6, 4),
    )
    assert summary["meetings"] == 0
    assert not (root / "meetings").exists()


# ── LOW: M4 motivating example pinned with a real Windows path ───────────────


def test_apply_actions_preserves_windows_path_with_backslashes():
    """LOW: the M4 commit message cites ``C:\\new`` as the motivating case
    for dropping the ``\\[nrt]`` alternation. Pin the documented contract
    with a real Windows-path input: a literal backslash-letter sequence in
    a path survives end-to-end, and the action is still a single line.
    """
    root = _root()
    proposal.apply_proposal(
        root,
        {"diary": "", "actions": ["(B) deploy to C:\\new\\release +ops upd:2026-06-04"],
         "topics": [], "meetings": []},
        now=datetime.datetime(2026, 6, 4),
    )
    body = (root / "tasks.todo.txt").read_text(encoding="utf-8")
    lines = body.splitlines()
    assert len(lines) == 1
    # The Windows path survives verbatim — both backslashes and the \r/\t/\n
    # *text* in any extension are preserved.
    assert "C:\\new\\release" in lines[0]
    assert lines[0].startswith("(B) ")


# ── validate_action_dates (date-sanity gate used by the propose tool) ────────


def test_validate_action_dates_clean_due_only():
    assert proposal.validate_action_dates(
        ["(A) prepare org chart +presentation due:2026-06-09 upd:2026-06-06"]
    ) == []


def test_validate_action_dates_clean_tickler_before_due():
    assert proposal.validate_action_dates(
        ["(A) do thing due:2026-06-12 t:2026-06-10 upd:2026-06-06"]
    ) == []


def test_validate_action_dates_tickler_equal_due_is_ok():
    assert proposal.validate_action_dates(
        ["(A) do thing due:2026-06-10 t:2026-06-10 upd:2026-06-06"]
    ) == []


def test_validate_action_dates_flags_tickler_after_due():
    """The exact 2026-06-05 bug shape: a reminder set *after* the deadline."""
    errs = proposal.validate_action_dates(
        ["(A) org chart for presentation due:2026-06-09 t:2026-06-12 upd:2026-06-06"]
    )
    assert len(errs) == 1
    assert "after due:2026-06-09" in errs[0]


def test_validate_action_dates_flags_malformed_due():
    errs = proposal.validate_action_dates(["(A) x due:2026-13-45 upd:2026-06-06"])
    assert len(errs) == 1
    assert "invalid due:" in errs[0]


def test_validate_action_dates_flags_malformed_tickler():
    errs = proposal.validate_action_dates(["(B) x t:not-a-date upd:2026-06-06"])
    assert len(errs) == 1
    assert "invalid t:" in errs[0]


def test_validate_action_dates_ignores_t_inside_upd():
    """`upd:` (and other tokens) must not be mistaken for a tickler `t:` token."""
    assert proposal.validate_action_dates(["(B) x +y upd:2026-06-06"]) == []


def test_validate_action_dates_empty_list():
    assert proposal.validate_action_dates([]) == []


# ── id: stamping on append (Phase 1 — Action identity) ─────────────────────


def test_gen_id_is_six_base36():
    import re as _re
    for _ in range(50):
        assert _re.fullmatch(r"[a-z0-9]{6}", proposal.gen_id())


def test_id_bare_pattern_lockstep():
    """ID_BARE_RE must match gen_id() output — lockstep guard."""
    for _ in range(100):
        assert proposal.ID_BARE_RE.fullmatch(proposal.gen_id())
    # Also verify _ID_TOKEN_RE (used by search/findall) matches the full form.
    id_val = proposal.gen_id()
    full = f"id:{id_val}"
    assert proposal._ID_TOKEN_RE.search(full)


def test_append_actions_stamps_id_when_absent(tmp_path):
    import re as _re
    proposal._append_actions(tmp_path, ["(A) do thing +t upd:2026-06-06"])
    line = (tmp_path / "tasks.todo.txt").read_text(encoding="utf-8").strip()
    assert _re.search(r" id:[a-z0-9]{6}$", line)


def test_append_actions_preserves_existing_id(tmp_path):
    proposal._append_actions(tmp_path, ["(A) do thing upd:2026-06-06 id:keepme"])
    line = (tmp_path / "tasks.todo.txt").read_text(encoding="utf-8").strip()
    assert line.endswith("id:keepme")
    assert line.count("id:") == 1


def test_backfill_ids_stamps_only_unstamped(tmp_path):
    import re as _re
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) already +t upd:2026-06-06 id:fixed1\n"
        "(B) needs one +t upd:2026-06-06\n"
        "\n"
        "# a comment\n",
        encoding="utf-8",
    )
    n = proposal.backfill_ids(tmp_path)
    assert n == 1
    lines = (tmp_path / "tasks.todo.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith("id:fixed1")              # untouched
    assert _re.search(r" id:[a-z0-9]{6}$", lines[1])   # stamped
    assert lines[2] == "" and lines[3] == "# a comment"  # blanks/comments preserved
    # idempotent: second run stamps nothing
    assert proposal.backfill_ids(tmp_path) == 0


def test_backfill_ids_no_file(tmp_path):
    assert proposal.backfill_ids(tmp_path) == 0


# ── apply_task_ops (Phase 2 — Mutation application) ────────────────────────


def _seed(tmp_path):
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) org chart +presentation due:2026-06-09 upd:2026-06-06 id:aaa111\n"
        "(B) call vendor +hw t:2026-06-12 upd:2026-06-06 id:bbb222\n",
        encoding="utf-8",
    )


def test_apply_task_ops_complete(tmp_path):
    import datetime as _dt
    _seed(tmp_path)
    res = proposal.apply_task_ops(tmp_path, [{"id": "aaa111", "op": "complete"}],
                                  now=_dt.date(2026, 6, 7))
    assert res["applied"] == 1 and res["errors"] == []
    line = [line for line in (tmp_path/"tasks.todo.txt").read_text().splitlines() if "aaa111" in line][0]
    assert line.startswith("x ")
    assert "upd:2026-06-07" in line  # upd bumped


def test_apply_task_ops_reprioritize(tmp_path):
    import datetime as _dt
    _seed(tmp_path)
    proposal.apply_task_ops(tmp_path, [{"id": "bbb222", "op": "reprioritize", "value": "A"}],
                            now=_dt.date(2026, 6, 7))
    line = [line for line in (tmp_path/"tasks.todo.txt").read_text().splitlines() if "bbb222" in line][0]
    assert line.startswith("(A) ")
    assert "(B)" not in line


def test_apply_task_ops_retickle(tmp_path):
    import datetime as _dt
    _seed(tmp_path)
    proposal.apply_task_ops(tmp_path, [{"id": "bbb222", "op": "retickle", "value": "2026-06-08"}],
                            now=_dt.date(2026, 6, 7))
    line = [line for line in (tmp_path/"tasks.todo.txt").read_text().splitlines() if "bbb222" in line][0]
    assert "t:2026-06-08" in line and "t:2026-06-12" not in line


def test_apply_task_ops_unknown_id_reported(tmp_path):
    import datetime as _dt
    _seed(tmp_path)
    res = proposal.apply_task_ops(tmp_path, [{"id": "zzz999", "op": "complete"}],
                                  now=_dt.date(2026, 6, 7))
    assert res["applied"] == 0
    assert any("zzz999" in e for e in res["errors"])


# ── Phase 4: unified apply_proposal with task_ops ──────────────────────────


def test_apply_proposal_with_task_ops_applies_both(tmp_path):
    """apply_proposal with task_ops must apply proposal fields AND task
    mutations under the same call, returning a merged summary."""
    import datetime as _dt
    _seed(tmp_path)
    prop = {
        "diary": "Sweep notes.",
        "actions": ["(A) new task +x upd:2026-06-07"],
        "topics": [],
        "meetings": [],
    }
    task_ops_list = [{"id": "aaa111", "op": "complete"}]
    summary = proposal.apply_proposal(
        tmp_path, prop,
        now=_dt.datetime(2026, 6, 7, 10, 0),
        task_ops=task_ops_list,
    )
    assert summary["diary"] is True
    assert summary["actions"] == 1
    assert summary["task_ops"]["applied"] == 1
    assert summary["task_ops"]["errors"] == []
    # Verify the task was actually completed
    lines = (tmp_path / "tasks.todo.txt").read_text(encoding="utf-8").splitlines()
    assert any(ln.startswith("x ") and "aaa111" in ln for ln in lines)


def test_apply_proposal_rolls_back_task_ops_on_failure(monkeypatch):
    """When _apply_topics raises after task_ops have been applied, the
    task_ops mutation is rolled back along with all other writes."""
    import datetime as _dt

    import frontend.proposal as proposal_mod

    tmp_path = _root()
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) existing +x upd:2026-06-06 id:aaa111\n", encoding="utf-8")
    orig_content = (tmp_path / "tasks.todo.txt").read_text(encoding="utf-8")

    def _boom(_notes_root, _topics, _now):
        raise RuntimeError("simulated topics failure")

    monkeypatch.setattr(proposal_mod, "_apply_topics", _boom)

    with pytest.raises(RuntimeError, match="simulated topics failure"):
        proposal.apply_proposal(
            tmp_path,
            {"diary": "", "actions": [], "topics": [{"slug": "atlas",
             "section": "## Current state", "text": "x"}], "meetings": []},
            now=_dt.datetime(2026, 6, 7),
            task_ops=[{"id": "aaa111", "op": "complete"}],
        )

    # tasks.todo.txt must be restored byte-for-byte (task_ops undone).
    assert (tmp_path / "tasks.todo.txt").read_text(encoding="utf-8") == orig_content


# ── MAX_TASK_OPS constant ──────────────────────────────────────────────────


def test_id_length_lockstep_with_agenda():
    """ID_LENGTH in frontend.proposal matches the duplicated constant in agenda/parser.py.
    If they diverge, id: tags written by one package won't be parseable by the other."""
    from agenda.parser import _ID_LENGTH
    assert proposal.ID_LENGTH == _ID_LENGTH


def test_max_task_ops_value():
    """MAX_TASK_OPS matches the cap used in the Pydantic model."""
    assert proposal.MAX_TASK_OPS == 50


def _write_tasks(root: Path, line: str) -> None:
    (root / "tasks.todo.txt").write_text(line, encoding="utf-8")


def test_apply_task_ops_no_file(tmp_path):
    """Missing tasks.todo.txt returns error with zero applied."""
    result = proposal.apply_task_ops(
        tmp_path, [{"id": "abc123", "op": "complete"}]
    )
    assert result == {"applied": 0, "errors": ["no tasks.todo.txt; ops: 1"]}


def test_apply_task_ops_bad_op(tmp_path):
    """Unknown op returns an error and is skipped."""
    _write_tasks(tmp_path, "(A) a task id:abc123\n")
    result = proposal.apply_task_ops(
        tmp_path, [{"id": "abc123", "op": "delete"}]
    )
    assert result["applied"] == 0
    assert any("unknown op" in e for e in result["errors"])


def test_apply_task_ops_bad_reprioritize_value(tmp_path):
    """reprioritize with value outside A-D returns an error."""
    _write_tasks(tmp_path, "(A) a task id:abc123\n")
    result = proposal.apply_task_ops(
        tmp_path, [{"id": "abc123", "op": "reprioritize", "value": "E"}]
    )
    assert result["applied"] == 0
    assert any("A-D" in e for e in result["errors"])


def test_apply_task_ops_bad_retickle_date(tmp_path):
    """retickle with an invalid date returns an error."""
    _write_tasks(tmp_path, "(A) a task id:abc123\n")
    result = proposal.apply_task_ops(
        tmp_path, [{"id": "abc123", "op": "retickle", "value": "bad-date"}]
    )
    assert result["applied"] == 0
    assert any("invalid date" in e for e in result["errors"])
