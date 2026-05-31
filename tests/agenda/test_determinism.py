from datetime import date

from agenda.engine import review, today, topic

TODAY = date(2026, 5, 30)


def test_identical_input_yields_identical_output(tmp_path):
    (tmp_path / "tasks.todo.txt").write_text(
        "(A) Alpha +x upd:2026-05-29\n(B) Beta +y t:2026-05-30 upd:2026-05-29\n",
        encoding="utf-8",
    )
    first = today(tmp_path, on=TODAY)
    second = today(tmp_path, on=TODAY)
    assert first == second


def _seed_full(root):
    (root / "tasks.todo.txt").write_text(
        "(A) Open task +x upd:2026-05-29\n"
        "(B) Scheduled +x t:2026-06-01 upd:2026-05-29\n",
        encoding="utf-8",
    )
    (root / "topics").mkdir()
    (root / "topics" / "x.md").write_text(
        "---\nslug: x\ntitle: Topic X\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (root / "meetings" / "2026-05-28").mkdir(parents=True)
    (root / "meetings" / "2026-05-28" / "meeting-x.md").write_text(
        "---\ndate: 2026-05-28\ntitle: X Sync\ntopics: [x]\n---\n",
        encoding="utf-8",
    )


def test_review_is_deterministic(tmp_path):
    _seed_full(tmp_path)
    first = review(tmp_path, on=TODAY)
    second = review(tmp_path, on=TODAY)
    assert first == second


def test_topic_is_deterministic(tmp_path):
    _seed_full(tmp_path)
    first = topic(tmp_path, "x", on=TODAY)
    second = topic(tmp_path, "x", on=TODAY)
    assert first == second
