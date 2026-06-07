import os

import pytest

from presenter import server


def test_present_returns_ok_and_echoes_path():
    assert server.present("meetings/2026-05-31/atlas.md") == {
        "ok": True,
        "presented": "meetings/2026-05-31/atlas.md",
    }


def test_tool_names_include_present_and_propose():
    assert server.TOOL_NAMES == ("present", "propose", "present_brief", "present_task")


class TestPropose:
    """Isolated test class: each test sets NOTES_ROOT to a tmp dir."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_ROOT", str(tmp_path))

    def test_valid_json(self):
        result = server.propose("""{
            "diary": "User shared two tasks today.",
            "actions": ["(A) Prepare org chart +presentation due:2026-06-09 upd:2026-06-05"],
            "topics": [{"slug": "presentation", "section": "## Current state", "text": "Org chart needed for Tuesday"}],
            "meetings": []
        }""")
        assert result["ok"] is True
        assert result["diary"] is True
        assert result["action_count"] == 1
        assert result["topic_count"] == 1

    def test_rejects_tickler_after_due(self):
        """A reminder (t:) set after the deadline (due:) is rejected — the exact
        2026-06-05 mis-file class of bug (reminder fires after the event)."""
        result = server.propose("""{
            "diary": "Org chart needed for Tuesday's presentation.",
            "actions": ["(A) Prepare org chart due:2026-06-09 t:2026-06-12 upd:2026-06-06"],
            "topics": [],
            "meetings": []
        }""")
        assert result["ok"] is False
        assert "after due:2026-06-09" in result["error"]

    def test_invalid_json(self):
        result = server.propose("not json")
        assert result["ok"] is False
        assert "invalid JSON" in result["error"]

    def test_not_a_dict(self):
        result = server.propose("[1, 2, 3]")
        assert result["ok"] is False
        assert "JSON object" in result["error"]

    def test_missing_required_keys(self):
        result = server.propose('{"diary": "x"}')
        assert result["ok"] is False
        for k in ("actions", "topics", "meetings"):
            assert k in result["error"]

    def test_empty_diary_with_content(self):
        result = server.propose("""{
            "diary": "",
            "actions": ["(B) something +test upd:2026-06-05"],
            "topics": [],
            "meetings": []
        }""")
        assert result["ok"] is False
        assert "diary" in result["error"]

    def test_tag_without_topic(self):
        result = server.propose("""{
            "diary": "Test",
            "actions": ["(B) task +missing-tag upd:2026-06-05"],
            "topics": [],
            "meetings": []
        }""")
        assert result["ok"] is False
        assert "missing-tag" in result["error"]

    def test_invalid_topic_slug(self):
        result = server.propose("""{
            "diary": "Test",
            "actions": [],
            "topics": [{"slug": "has a space", "section": "## Current state", "text": "bad slug"}],
            "meetings": []
        }""")
        assert result["ok"] is True
        assert result["topic_count"] == 0

    def test_invalid_topic_section(self):
        result = server.propose("""{
            "diary": "Test",
            "actions": [],
            "topics": [{"slug": "ok", "section": "## Unknown section", "text": "text"}],
            "meetings": []
        }""")
        assert result["ok"] is True
        assert result["topic_count"] == 0

    def test_string_instead_of_list(self):
        """Type-confusion guard: a string value for actions/topics/meetings is rejected."""
        result = server.propose("""{
            "diary": "Test",
            "actions": "not a list",
            "topics": 42,
            "meetings": null
        }""")
        assert result["ok"] is True
        assert result["action_count"] == 0
        assert result["topic_count"] == 0
        assert result["meeting_count"] == 0

    def test_diary_only_no_actions(self):
        """A proposal with only diary text (no actions/topics/meetings) is valid."""
        result = server.propose("""{
            "diary": "Just a quick braindump.",
            "actions": [],
            "topics": [],
            "meetings": []
        }""")
        assert result["ok"] is True
        assert result["diary"] is True
        assert result["action_count"] == 0

    def test_invalid_meeting_slug(self):
        """An invalid-slug meeting entry is silently dropped like an invalid topic slug."""
        result = server.propose("""{
            "diary": "Test",
            "actions": [],
            "topics": [],
            "meetings": [{"slug": "has space"}]
        }""")
        assert result["ok"] is True
        assert result["meeting_count"] == 0

    def test_writes_proposal_file(self):
        """The propose tool writes _proposal.json to inbox/ with the correct content."""
        import json
        from pathlib import Path

        root = Path(os.environ["NOTES_ROOT"])
        result = server.propose("""{
            "diary": "Written test.",
            "actions": ["(A) test task +test-topic due:2026-06-10 upd:2026-06-05"],
            "topics": [{"slug": "test-topic", "section": "## Current state", "text": "test"}],
            "meetings": []
        }""")
        assert result["ok"] is True
        proposal_file = root / "inbox" / "_proposal.json"
        assert proposal_file.exists()
        written = json.loads(proposal_file.read_text(encoding="utf-8"))
        assert written["diary"] == "Written test."
        assert len(written["actions"]) == 1
        assert len(written["topics"]) == 1
        assert len(written["meetings"]) == 0
        proposal_file.unlink()

    def test_valid_meeting(self):
        """A valid meeting with all fields round-trips through _proposal.json.

        Regression for finding B-4: the `valid_meetings.append` branch and the
        summary / decisions / actions / raw / topics field mapping at
        presenter/server.py were 100% uncovered — the only test exercising
        the meeting path used an invalid slug, which was silently dropped.
        """
        import json
        from pathlib import Path

        root = Path(os.environ["NOTES_ROOT"])
        result = server.propose("""{
            "diary": "Discussed the atlas migration.",
            "actions": [],
            "topics": [],
            "meetings": [{
                "slug": "atlas-migration-sync",
                "title": "Atlas migration sync",
                "topics": ["atlas", "infra"],
                "summary": "Walked through the cutover plan.",
                "decisions": "Cutover 2026-06-15 18:00 UTC.",
                "actions": "Action: prepare rollback runbook.",
                "raw": "raw notes text"
            }]
        }""")
        assert result["ok"] is True
        assert result["meeting_count"] == 1
        assert result["topic_count"] == 0
        proposal_file = root / "inbox" / "_proposal.json"
        assert proposal_file.exists()
        written = json.loads(proposal_file.read_text(encoding="utf-8"))
        assert len(written["meetings"]) == 1
        m = written["meetings"][0]
        assert m["slug"] == "atlas-migration-sync"
        assert m["title"] == "Atlas migration sync"
        assert m["topics"] == ["atlas", "infra"]
        assert m["summary"] == "Walked through the cutover plan."
        assert m["decisions"] == "Cutover 2026-06-15 18:00 UTC."
        assert m["actions"] == "Action: prepare rollback runbook."
        assert m["raw"] == "raw notes text"
        proposal_file.unlink()

    def test_too_many_actions_rejected(self):
        """MAX_ACTIONS+1 actions are rejected at the MCP entry, not silently capped."""
        import json

        actions = [f"(B) action {i} +t upd:2026-06-05" for i in range(51)]
        result = server.propose(json.dumps({
            "diary": "Test",
            "actions": actions,
            "topics": [{"slug": "t", "section": "## Current state", "text": "t"}],
            "meetings": [],
        }))
        assert result["ok"] is False
        assert "actions list exceeds 50" in result["error"]

    def test_too_many_topics_rejected(self):
        import json

        topics = [{"slug": f"t{i}", "section": "## Current state", "text": "x"} for i in range(21)]
        result = server.propose(json.dumps({
            "diary": "Test",
            "actions": [],
            "topics": topics,
            "meetings": [],
        }))
        assert result["ok"] is False
        assert "topics list exceeds 20" in result["error"]

    def test_too_many_meetings_rejected(self):
        import json

        meetings = [{"slug": f"m{i}", "title": "m"} for i in range(11)]
        result = server.propose(json.dumps({
            "diary": "Test",
            "actions": [],
            "topics": [],
            "meetings": meetings,
        }))
        assert result["ok"] is False
        assert "meetings list exceeds 10" in result["error"]

    def test_oversized_action_text_rejected(self):
        """Action text >200 chars is rejected, not silently truncated."""
        import json

        long_action = "(B) " + ("x" * 250) + " +t upd:2026-06-05"
        result = server.propose(json.dumps({
            "diary": "Test",
            "actions": [long_action],
            "topics": [{"slug": "t", "section": "## Current state", "text": "t"}],
            "meetings": [],
        }))
        assert result["ok"] is False
        assert "action text" in result["error"]
        assert "exceeds 200" in result["error"]

    def test_oversized_topic_text_rejected(self):
        import json

        result = server.propose(json.dumps({
            "diary": "Test",
            "actions": [],
            "topics": [{"slug": "t", "section": "## Current state", "text": "x" * 8001}],
            "meetings": [],
        }))
        assert result["ok"] is False
        assert "topic text" in result["error"]
        assert "exceeds 8000" in result["error"]

    def test_oversized_diary_rejected(self):
        import json

        result = server.propose(json.dumps({
            "diary": "x" * 8001,
            "actions": [],
            "topics": [],
            "meetings": [],
        }))
        assert result["ok"] is False
        assert "diary" in result["error"]
        assert "exceeds 8000" in result["error"]

    def test_oversized_total_proposal_rejected(self):
        """Total JSON > 1 MiB is rejected before json.loads runs."""
        import json

        # Pad the diary to push the JSON over 1 MiB. We need to construct the
        # JSON string and pass it directly, since the dict form would be
        # parsed before reaching the size check.
        diary = "x" * (1 * 1024 * 1024 + 1024)
        payload = json.dumps({
            "diary": diary,
            "actions": [],
            "topics": [],
            "meetings": [],
        })
        assert len(payload.encode("utf-8")) > 1 * 1024 * 1024
        result = server.propose(payload)
        assert result["ok"] is False
        assert "exceeds 1048576" in result["error"]

    def test_orphan_tag_silently_dropped(self):
        """A +tag that isn't a valid slug is ignored, not a hard error.

        This is a deliberate permissiveness — the agent might emit `+C:`
        (todo.txt context prefix), `++double`, or other token forms that look
        like tags but aren't topic references. Treating those as hard errors
        would make the propose path brittle. Only valid-slug tags
        (matching SLUG_PATTERN) are checked against topic_slugs.
        """
        result = server.propose("""{
            "diary": "Test",
            "actions": ["(B) contact @colleague +t upd:2026-06-05"],
            "topics": [{"slug": "t", "section": "## Current state", "text": "t"}],
            "meetings": []
        }""")
        assert result["ok"] is True
        # Cleanup
        from pathlib import Path
        Path(os.environ["NOTES_ROOT"]).joinpath("inbox", "_proposal.json").unlink(missing_ok=True)

    def test_orphan_topic_accepted(self):
        """A topic entry not referenced by any +tag in actions is accepted.

        Documented as the symmetric-permissive choice: the +tag check
        (action-tag must exist in topics) is one-way, on the principle that
        an orphan topic note is still useful content even if no action
        currently references it. See audit finding 2.5.
        """
        result = server.propose("""{
            "diary": "Test",
            "actions": [],
            "topics": [{"slug": "orphan", "section": "## Current state", "text": "x"}],
            "meetings": []
        }""")
        assert result["ok"] is True
        assert result["topic_count"] == 1
        from pathlib import Path
        Path(os.environ["NOTES_ROOT"]).joinpath("inbox", "_proposal.json").unlink(missing_ok=True)

    def test_writes_atomically(self):
        """The _proposal.json write is atomic (sibling .tmp + os.replace).

        Indirect evidence: the file is observed either pre-write (absent) or
        post-write (full content). A partial mid-write would surface as
        invalid JSON on read, but we cannot reliably trigger a kill
        mid-write from a unit test — the regression we care about is the
        *absence* of a .tmp file after the write completes, which proves
        the os.replace happened.
        """
        from pathlib import Path

        server.propose("""{
            "diary": "Atomic.",
            "actions": [],
            "topics": [],
            "meetings": []
        }""")
        proposal_file = Path(os.environ["NOTES_ROOT"]) / "inbox" / "_proposal.json"
        tmp_file = proposal_file.with_suffix(proposal_file.suffix + ".tmp")
        assert proposal_file.exists()
        assert not tmp_file.exists(), "sibling .tmp must be replaced, not left as debris"
        proposal_file.unlink()


def test_main_raises_without_notes_root(monkeypatch):
    """Regression for finding B-5: the main() NOTES_ROOT guard is enforced.

    A bare `python -m presenter.server` without the env var would
    otherwise silently fail to write proposals to the correct location.
    The guard is what the launcher relies on for fail-fast diagnostics.
    """
    monkeypatch.delenv("NOTES_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="NOTES_ROOT must be set"):
        server._require_notes_root()


def test_load_staging_returns_empty_default_when_no_file(tmp_path):
    """No staging file → empty default, was_lost=False."""
    data, was_lost = server._load_staging(tmp_path)
    assert was_lost is False
    assert data == {"diary": "", "actions": [], "topics": [], "meetings": [], "task_ops": []}


def test_load_staging_parses_valid_file(tmp_path):
    """Valid staging file → parsed data, was_lost=False."""
    import json
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "_proposal.json").write_text(
        json.dumps({"diary": "test", "actions": [], "topics": [], "meetings": []}),
        encoding="utf-8",
    )
    data, was_lost = server._load_staging(tmp_path)
    assert was_lost is False
    assert data["diary"] == "test"


def test_load_staging_malformed_json_returns_empty(tmp_path):
    """Corrupted _proposal.json → empty default, was_lost=True."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "_proposal.json").write_text("not json", encoding="utf-8")
    data, was_lost = server._load_staging(tmp_path)
    assert was_lost is True
    assert data == {"diary": "", "actions": [], "topics": [], "meetings": [], "task_ops": []}


# ── present_brief (Phase 3 — MCP tools) ─────────────────────────────────────


class TestBrief:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
        self.root = tmp_path

    def test_writes_dated_brief(self):
        r = server.present_brief("daily", "# Today\n- do X\n")
        assert r["ok"] is True
        import datetime
        name = f"{datetime.date.today():%Y-%m-%d}-daily.md"
        body = (self.root / "briefs" / name).read_text(encoding="utf-8")
        assert body == "# Today\n- do X\n"
        assert r["path"].endswith(name)

    def test_rejects_bad_kind(self):
        r = server.present_brief("monthly", "x")
        assert r["ok"] is False and "kind" in r["error"]


# ── present_task (Phase 3 — MCP tools) ──────────────────────────────────────


class TestTask:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
        self.root = tmp_path
        (tmp_path / "tasks.todo.txt").write_text(
            "(B) call vendor +hw t:2026-06-12 upd:2026-06-06 id:bbb222\n", encoding="utf-8")

    def _staged(self):
        import json
        return json.loads((self.root / "inbox" / "_proposal.json").read_text())

    def test_stages_op_for_known_id(self):
        r = server.present_task("bbb222", "complete")
        assert r["ok"] is True
        assert self._staged()["task_ops"] == [{"id": "bbb222", "op": "complete", "value": None}]

    def test_rejects_unknown_id(self):
        r = server.present_task("nope00", "complete")
        assert r["ok"] is False and "nope00" in r["error"]

    def test_rejects_bad_op(self):
        r = server.present_task("bbb222", "delete")
        assert r["ok"] is False and "op" in r["error"]

    def test_merges_with_existing_proposal(self):
        server.propose('{"diary":"d","actions":[],"topics":[],"meetings":[]}')
        server.present_task("bbb222", "retickle", "2026-06-08")
        s = self._staged()
        assert s["diary"] == "d"  # preserved
        assert s["task_ops"][0] == {"id": "bbb222", "op": "retickle", "value": "2026-06-08"}

    def test_rejects_reprioritize_invalid_value(self):
        r = server.present_task("bbb222", "reprioritize", "E")
        assert r["ok"] is False and "A-D" in r["error"]

    def test_rejects_retickle_bad_date(self):
        r = server.present_task("bbb222", "retickle", "bad-date")
        assert r["ok"] is False and "YYYY-MM-DD" in r["error"]

    def test_rejects_retickle_empty_value(self):
        r = server.present_task("bbb222", "retickle", "")
        assert r["ok"] is False and "YYYY-MM-DD" in r["error"]

    def test_stages_diary_only_no_warnings(self):
        r = server.propose('{"diary":"x","actions":[],"topics":[],"meetings":[]}')
        assert r["warnings"] is None

    def test_warns_on_dropped_topic(self):
        r = server.propose("""{
            "diary": "Test",
            "actions": [],
            "topics": [{"slug": "has space", "section": "## Current state", "text": "bad"}],
            "meetings": []
        }""")
        assert r["topic_count"] == 0
        assert "has space" in str(r["warnings"])
