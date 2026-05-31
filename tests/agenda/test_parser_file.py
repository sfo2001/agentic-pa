from agenda.parser import parse_task_file


def test_parses_file_skipping_blanks_and_comments(tmp_path):
    f = tmp_path / "tasks.todo.txt"
    f.write_text(
        "# my tasks\n"
        "(A) Do thing +alpha\n"
        "\n"
        "x (C) Done thing +beta\n",
        encoding="utf-8",
    )
    actions = parse_task_file(f)
    assert len(actions) == 2
    assert actions[0].description == "Do thing"
    assert actions[1].done is True


def test_missing_file_returns_empty_list(tmp_path):
    actions = parse_task_file(tmp_path / "nope.txt")
    assert actions == []
