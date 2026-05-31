import agenda.server as server


def _seed(root):
    (root / "tasks.todo.txt").write_text(
        "(A) Alpha +x upd:2026-05-29\n", encoding="utf-8"
    )


def test_today_tool_reads_notes_root(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
    result = server.today()
    assert [a["text"] for a in result["do_now"]] == ["Alpha"]


def test_topic_tool_passes_slug(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
    result = server.topic("x")
    assert result["slug"] == "x"


def test_only_read_tools_registered():
    assert server.TOOL_NAMES == ("today", "review", "topic", "search")
    assert not any("create" in n or "write" in n or "update" in n for n in server.TOOL_NAMES)


def test_review_tool_reads_notes_root(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
    result = server.review()
    assert result["date"] is not None
    assert "topics" in result
    assert "ticklers_this_week" in result


# ── BH-18: Pattern C — empty NOTES_ROOT silently falls back to "." ────────────


def test_bh18_empty_notes_root_falls_back_to_dot(monkeypatch):
    """BH-18: an explicitly-empty NOTES_ROOT is treated as unset (by design —
    empty env values are not meaningful notes roots; see the empty-as-unset
    decision) and falls back to ".". Not a bug."""
    monkeypatch.setenv("NOTES_ROOT", "")
    result = server._notes_root()
    assert str(result) == "."


def test_search_tool_returns_ranked_paths(tmp_path, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\n## Overview\nAtlas migration to Postgres.\n",
        encoding="utf-8",
    )
    (tmp_path / "topics" / "hiring.md").write_text(
        "---\nslug: hiring\ntitle: Hiring\n---\n## Overview\nBackend hiring plan.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))

    import importlib

    from agenda import server
    importlib.reload(server)

    results = server.search("atlas migration")

    assert results, "expected at least one hit"
    assert results[0]["path"].endswith("topics/atlas.md")
    assert results[0]["score"] > 0


def test_server_key_is_notes():
    import importlib

    from agenda import server
    importlib.reload(server)
    assert server.mcp.name == "notes"


def test_search_excludes_archive_and_briefs(tmp_path, monkeypatch):
    for sub in ("topics", "archive", "briefs"):
        (tmp_path / sub).mkdir()
    (tmp_path / "topics" / "live.md").write_text(
        "---\nslug: live\ntitle: Live\n---\nAtlas migration to Postgres.\n", encoding="utf-8")
    (tmp_path / "archive" / "old.md").write_text(
        "---\nslug: old\ntitle: Old\n---\nAtlas migration to Postgres, archived copy.\n", encoding="utf-8")
    (tmp_path / "briefs" / "b.md").write_text(
        "---\ntitle: Brief\n---\nAtlas migration daily brief.\n", encoding="utf-8")
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))

    import importlib

    from agenda import server
    importlib.reload(server)

    paths = [r["path"] for r in server.search("atlas migration")]

    assert "topics/live.md" in paths
    assert not any(p.startswith("archive/") or p.startswith("briefs/") for p in paths)


def _reload_server(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_ROOT", str(tmp_path))
    import importlib

    from agenda import server
    importlib.reload(server)
    return server


def test_search_empty_and_no_hits(tmp_path, monkeypatch):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "a.md").write_text("---\ntitle: A\n---\nAtlas.\n", encoding="utf-8")
    server = _reload_server(tmp_path, monkeypatch)
    assert server.search("") == []
    assert server.search("zzzqxyzzy-nomatch-term") == []


def test_search_respects_n_limit(tmp_path, monkeypatch):
    (tmp_path / "topics").mkdir()
    for s in ("a", "b", "c", "d", "e"):
        (tmp_path / "topics" / f"{s}.md").write_text(
            f"---\ntitle: {s}\n---\nAtlas migration postgres shared terms.\n", encoding="utf-8")
    server = _reload_server(tmp_path, monkeypatch)
    assert len(server.search("atlas migration postgres", n=2)) == 2


def test_search_skips_paths_outside_root(tmp_path, monkeypatch):
    from pathlib import Path

    from llm_wiki.search import SearchResult

    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "ok.md").write_text("ok", encoding="utf-8")
    server = _reload_server(tmp_path, monkeypatch)
    # Simulate a poisoned BM25 cache: one in-root hit + one absolute path elsewhere.
    fake = [
        SearchResult(path=(tmp_path / "topics" / "ok.md"), score=2.0, snippet="ok"),
        SearchResult(path=Path("/etc/passwd"), score=9.0, snippet="leak"),
    ]
    monkeypatch.setattr("llm_wiki.search.search", lambda *a, **k: fake)
    paths = [r["path"] for r in server.search("q")]
    assert "topics/ok.md" in paths
    assert not any(p.startswith("/") or "passwd" in p for p in paths)
