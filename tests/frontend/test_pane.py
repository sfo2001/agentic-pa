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


def test_diary_at_cap_renders_normally(tmp_path):
    """A diary exactly at the cap still renders as markdown (boundary)."""
    (tmp_path / "diary").mkdir()
    body = "# Diary\n" + "x" * (render_pane.MAX_DIARY_RENDER_BYTES - len("# Diary\n"))
    assert len(body.encode("utf-8")) == render_pane.MAX_DIARY_RENDER_BYTES
    (tmp_path / "diary" / f"{datetime.date.today():%Y-%m-%d}.md").write_text(
        body, encoding="utf-8")
    html = render_pane.diary(tmp_path)
    assert "<h1>" in html
    assert "is large" not in html


def test_diary_over_cap_returns_hint(tmp_path):
    """A diary over the cap returns the 'open from chat' hint, not the body."""
    (tmp_path / "diary").mkdir()
    name = f"{datetime.date.today():%Y-%m-%d}.md"
    (tmp_path / "diary" / name).write_text(
        "# Secret\n" + "y" * (render_pane.MAX_DIARY_RENDER_BYTES + 1), encoding="utf-8")
    html = render_pane.diary(tmp_path)
    assert "is large" in html
    assert f"diary/{name}" in html
    assert "Secret" not in html  # body must not be rendered


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


def test_esc_escapes_all_html_metachars():
    """_esc must escape &, <, >, ", ' — the previous version omitted >."""
    out = render_pane._esc("""<a href="x" onclick='y'>&z""")
    for raw in ("<", ">", '"', "&z"):
        assert raw not in out.replace("&amp;z", "")
    assert "&lt;" in out
    assert "&gt;" in out
    assert "&amp;" in out
    assert "&quot;" in out
    assert "&#x27;" in out  # html.escape renders ' as &#x27;


def test_actions_truncates_at_cap(tmp_path, monkeypatch):
    """More than MAX_ACTIONS_RENDER actions render a 'Showing the first N' note."""
    cap = render_pane.MAX_ACTIONS_RENDER
    view = {"date": "2026-06-08", "do_now": [], "overdue": [], "schedule": [],
            "resurfacing": [], "stale_important": []}
    view["do_now"] = [{"id": f"id{n:04d}", "text": f"t{n}", "priority": "A"}
                      for n in range(cap + 5)]
    monkeypatch.setattr(render_pane.engine, "today", lambda _root: view)
    html = render_pane.actions(tmp_path)
    assert f"Showing the first {cap} actions" in html
    # Only the cap is rendered, not all cap+5.
    assert html.count('class="action-row"') == cap
