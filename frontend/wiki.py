"""Deterministic notes-tree housekeeping: index regeneration + structural lint.

The agent never maintains these — the frontend (sole writer, ADR-0003) regenerates
index.md and runs lint after a structural turn, so structure cannot silently drift.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from llm_wiki.lint import check_newlines, lint_structural


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}


def _entries(notes_root: Path) -> list[tuple[str, str]]:
    """Return sorted (title, relpath) for every topic and meeting page."""
    out: list[tuple[str, str]] = []
    for sub in ("topics", "meetings"):
        base = notes_root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            fm = _frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            title = str(fm.get("title") or p.stem)
            out.append((title, p.relative_to(notes_root).as_posix()))
    return sorted(out, key=lambda e: e[1])


def regenerate_index(notes_root: Path | str) -> Path:
    """Write index.md: one plain-markdown link per topic/meeting page. Plain links
    (not [[wikilinks]]) so lint orphan detection measures real inter-topic links."""
    root = Path(notes_root)
    lines = ["# Index", "", "_Generated — do not hand-edit._", ""]
    lines += [f"- [{title}]({rel})" for title, rel in _entries(root)]
    out = root / "index.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _autofix_newlines(notes_root: Path) -> None:
    """Silently normalise every page to exactly one trailing newline (mechanical)."""
    for finding in check_newlines(notes_root):
        p = Path(finding.path)
        text = p.read_text(encoding="utf-8", errors="replace")
        p.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


# Orphan/link lint applies to the curated page graph only. Uploaded documents are
# referenced by markdown links (not [[links]]) and inbox captures are transient, so
# flagging them as orphans is noise — scope orphan findings to these dirs.
_CURATED_DIRS = ("topics", "meetings")


def run_housekeeping(notes_root: Path | str) -> list[dict]:
    """Regenerate index, auto-fix mechanical lint silently, return judgment findings.

    Judgment findings (broken links, orphans, missing-index) are returned as
    {type, path, line, message} for the caller to surface to the agent/user.

    Orphan findings are scoped to the curated topic+meeting graph (see
    ``_CURATED_DIRS``); broken-link and missing-page findings are returned wherever
    they occur.
    """
    root = Path(notes_root)
    _autofix_newlines(root)
    regenerate_index(root)
    findings: list[dict] = []
    for f in lint_structural(root):
        rel = Path(f.path).relative_to(root)
        if f.issue_type == "orphan" and (not rel.parts or rel.parts[0] not in _CURATED_DIRS):
            continue
        findings.append(
            {"type": f.issue_type, "path": rel.as_posix(), "line": f.line, "message": f.message}
        )
    return findings
