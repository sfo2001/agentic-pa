from pathlib import Path

from llm_wiki.search import search

from frontend.wiki import regenerate_index, run_housekeeping


def test_canary_search_finds_topic_and_lint_catches_broken_link(tmp_path):
    """Real-input replay: BM25 recall + structural lint over a seeded notes tree —
    guards against silent-fallback regressions the mocked unit tests can't see."""
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\n## Overview\nAtlas migration to Postgres.\nSee [[ghost]].\n",
        encoding="utf-8",
    )

    hits = search(tmp_path, "postgres migration")
    assert hits and hits[0].path.name == "atlas.md"

    findings = run_housekeeping(tmp_path)
    assert any(f["type"] == "broken_link" and "ghost" in f["message"] for f in findings)

def _topic(root: Path, slug: str, title: str):
    (root / "topics").mkdir(parents=True, exist_ok=True)
    (root / "topics" / f"{slug}.md").write_text(
        f"---\nslug: {slug}\ntitle: {title}\nstatus: active\n---\n## Overview\n", encoding="utf-8")

def test_regenerate_index_lists_topics_with_plain_links(tmp_path):
    _topic(tmp_path, "atlas", "Atlas Migration")
    _topic(tmp_path, "hiring", "Backend Hiring")

    regenerate_index(tmp_path)

    idx = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "[Atlas Migration](topics/atlas.md)" in idx
    assert "[Backend Hiring](topics/hiring.md)" in idx
    assert "[[" not in idx          # never wikilinks (would neuter orphan lint)

def test_regenerate_index_is_deterministic(tmp_path):
    _topic(tmp_path, "b", "Bee")
    _topic(tmp_path, "a", "Ay")
    regenerate_index(tmp_path)
    first = (tmp_path / "index.md").read_text()
    regenerate_index(tmp_path)
    second = (tmp_path / "index.md").read_text()
    assert first == second
    assert first.index("(topics/a.md)") < first.index("(topics/b.md)")  # sorted

def test_housekeeping_autofixes_newlines_silently(tmp_path):
    (tmp_path / "topics").mkdir()
    p = tmp_path / "topics" / "atlas.md"
    p.write_text("---\nslug: atlas\ntitle: Atlas\n---\n## Overview\nno newline", encoding="utf-8")  # missing trailing \n

    findings = run_housekeeping(tmp_path)

    assert p.read_text(encoding="utf-8").endswith("\n")          # fixed in place
    assert all(f["type"] != "newline" for f in findings)         # mechanical, not surfaced

def test_housekeeping_surfaces_broken_link(tmp_path):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text(
        "---\nslug: atlas\ntitle: Atlas\n---\nSee [[ghost]].\n", encoding="utf-8")

    findings = run_housekeeping(tmp_path)

    assert any(f["type"] == "broken_link" and "ghost" in f["message"] for f in findings)


def test_regenerate_index_includes_meetings(tmp_path):
    (tmp_path / "topics").mkdir()
    (tmp_path / "meetings" / "2026-05-01").mkdir(parents=True)
    (tmp_path / "topics" / "atlas.md").write_text("---\ntitle: Atlas\n---\n", encoding="utf-8")
    (tmp_path / "meetings" / "2026-05-01" / "sync.md").write_text(
        "---\ntitle: Sync\n---\n", encoding="utf-8")

    regenerate_index(tmp_path)

    idx = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "[Atlas](topics/atlas.md)" in idx
    assert "[Sync](meetings/2026-05-01/sync.md)" in idx


def test_housekeeping_empty_root(tmp_path):
    findings = run_housekeeping(tmp_path)
    assert findings == []
    assert (tmp_path / "index.md").exists()
