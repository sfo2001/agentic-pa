"""Unit tests for frontend/pane.py — pure HTML rendering functions."""
from __future__ import annotations

import datetime

from frontend import pane as render_pane


def test_actions_contains_bucket_labels(tmp_path):
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) Urgent +x due:2026-06-09 upd:2026-06-04 id:a1\n"
        "(B) Later +x upd:2026-06-04 id:b1\n", encoding="utf-8")
    html = render_pane.actions(tmp_path)
    assert "Do Now" in html
    assert "Schedule" in html


def test_actions_empty(tmp_path):
    html = render_pane.actions(tmp_path)
    assert "No open actions" in html


def test_actions_task_op_buttons(tmp_path):
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) Test +x due:2026-06-09 upd:2026-06-04 id:id0001\n", encoding="utf-8")
    html = render_pane.actions(tmp_path)
    assert 'data-op="complete"' in html or 'data-op=&#34;complete&#34;' in html
    assert 'data-op="reprioritize"' in html or 'data-op=&#34;reprioritize&#34;' in html
    assert 'data-id="id0001"' in html or 'data-id=&#34;id0001&#34;' in html


def test_diary_empty(tmp_path):
    html = render_pane.diary(tmp_path)
    assert "No diary today" in html


def test_diary_renders(tmp_path):
    (tmp_path / "diary").mkdir()
    (tmp_path / "diary" / f"{datetime.date.today():%Y-%m-%d}.md").write_text(
        "# Test diary", encoding="utf-8")
    html = render_pane.diary(tmp_path)
    assert "<h1>" in html
    assert "Test diary" in html


def test_brief_empty(tmp_path):
    html = render_pane.brief(tmp_path)
    assert "Ask in chat" in html
    assert "Daily Brief" in html


def test_brief_renders(tmp_path):
    (tmp_path / "briefs").mkdir()
    (tmp_path / "briefs" / f"{datetime.date.today():%Y-%m-%d}-daily.md").write_text(
        "# Daily Brief\n\nItem.", encoding="utf-8")
    html = render_pane.brief(tmp_path)
    assert "<h1>" in html
    assert "Daily Brief" in html


def test_artifact_empty():
    html = render_pane.artifact()
    assert "Nothing presented yet" in html
