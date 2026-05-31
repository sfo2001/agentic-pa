from agenda.parser import parse_frontmatter


def test_parses_yaml_frontmatter(tmp_path):
    f = tmp_path / "project-atlas.md"
    f.write_text(
        "---\n"
        "slug: project-atlas\n"
        "title: Atlas Programme\n"
        "tags: [technical, delivery]\n"
        "status: active\n"
        "---\n"
        "## Overview\n",
        encoding="utf-8",
    )
    fm = parse_frontmatter(f)
    assert fm["slug"] == "project-atlas"
    assert fm["title"] == "Atlas Programme"
    assert fm["tags"] == ["technical", "delivery"]


def test_no_frontmatter_returns_empty_dict(tmp_path):
    f = tmp_path / "plain.md"
    f.write_text("just text, no frontmatter\n", encoding="utf-8")
    assert parse_frontmatter(f) == {}


def test_missing_file_returns_empty_dict(tmp_path):
    assert parse_frontmatter(tmp_path / "nope.md") == {}


def test_no_closing_fence_returns_empty_dict(tmp_path):
    f = tmp_path / "unclosed.md"
    f.write_text("---\nslug: oops\ntitle: Unclosed\n", encoding="utf-8")
    assert parse_frontmatter(f) == {}


# ---------------------------------------------------------------------------
# BH-03 regression: malformed YAML must return {} instead of raising
# ---------------------------------------------------------------------------

def test_malformed_yaml_returns_empty_dict(tmp_path):
    """BH-03: yaml.safe_load raises YAMLError on malformed frontmatter; must return {}."""
    f = tmp_path / "malformed.md"
    # Unclosed bracket is valid YAML-error territory
    f.write_text(
        "---\ntags: [unclosed\nslug: bad\n---\n## Body\n",
        encoding="utf-8",
    )
    # Before the fix this raises yaml.YAMLError; after fix it must return {}
    assert parse_frontmatter(f) == {}


def test_tab_indented_mapping_yaml_returns_empty_dict(tmp_path):
    """BH-03: Tab-indented YAML mapping is a parse error; must return {}."""
    f = tmp_path / "tab-indent.md"
    f.write_text(
        "---\nslug: bad\n\tkey: value\n---\n## Body\n",
        encoding="utf-8",
    )
    assert parse_frontmatter(f) == {}


# ---------------------------------------------------------------------------
# BH-14 regression: --- inside a frontmatter value must not corrupt the split
# ---------------------------------------------------------------------------

# ── BH-29: Pattern I — BOM before "---" silently drops frontmatter ────────────


def test_bh29_bom_before_frontmatter_silently_drops_metadata(tmp_path):
    """BH-29: parse_frontmatter() checks ``not text.startswith("---")``.
    If the file has a UTF-8 BOM (``\\ufeff``) before ``---`` (common from
    Windows editors), ``startswith("---")`` is False, and frontmatter is
    skipped entirely — the function returns {} with no error or log.

    The BOM should be stripped before checking for the opening fence."""
    f = tmp_path / "bom.md"
    f.write_bytes(b"\xef\xbb\xbf---\nslug: project-atlas\ntitle: BOM Test\n---\n")
    fm = parse_frontmatter(f)
    # Correct behavior: BOM is stripped, frontmatter is parsed
    assert "slug" in fm, (
        "BOM before --- caused frontmatter to be silently dropped"
    )


def test_embedded_delimiter_preserves_all_fields(tmp_path):
    """BH-14: a value containing --- must not truncate the frontmatter block."""
    f = tmp_path / "atlas.md"
    f.write_text(
        "---\n"
        "slug: project-atlas\n"
        "title: Atlas --- Q2 push\n"
        "status: active\n"
        "---\n"
        "## Overview\n",
        encoding="utf-8",
    )
    fm = parse_frontmatter(f)
    # Before the fix, text.split("---", 2) splits on the embedded --- in the
    # title value, truncating the block and dropping "status".
    assert fm["slug"] == "project-atlas"
    assert fm["title"] == "Atlas --- Q2 push"
    assert fm["status"] == "active"
