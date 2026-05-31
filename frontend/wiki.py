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


def run_housekeeping(notes_root: Path | str) -> list[dict]:
    """Regenerate index, auto-fix mechanical lint silently, return judgment findings.

    Judgment findings (broken links, orphans, missing-index) are returned as
    {type, path, line, message} for the caller to surface to the agent/user.
    """
    root = Path(notes_root)
    _autofix_newlines(root)
    regenerate_index(root)
    return [
        {"type": f.issue_type, "path": Path(f.path).relative_to(root).as_posix(),
         "line": f.line, "message": f.message}
        for f in lint_structural(root)
    ]
