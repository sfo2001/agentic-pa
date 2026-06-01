"""Store an uploaded document into the notes tree, converting office files to Markdown."""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

CONVERT_EXTS = {".pdf", ".docx", ".pptx"}


def _sanitise_basename(name: str) -> str:
    """Return a markdown-safe basename: no spaces or characters that would break a
    plain ``[text](path)`` link. Preserves the final extension (lower-cased) and
    collapses runs of unsafe characters to single hyphens. Falls back to
    ``upload`` if nothing usable remains. The agent links documents with markdown
    links, so a space-free name keeps those links valid (see CONTEXT.md).
    """
    p = Path(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", p.stem).strip("-._")
    ext = re.sub(r"[^A-Za-z0-9.]+", "", p.suffix).lower()
    return (stem or "upload") + ext


def store_upload(
    notes_root: Path,
    filename: str,
    data: bytes,
    *,
    convert: Callable[[bytes, str], str],
) -> dict:
    """Store ``data`` under ``notes_root/documents/`` using a sanitised basename.

    For office files (.pdf/.docx/.pptx) also write a ``<name>.md`` sibling produced
    by ``convert(data, suffix)``. Returns repo-relative-ish paths under the notes tree.

    An existing file at the same name is OVERWRITTEN (intentional for the single-user
    notes tree — re-uploading a revised document replaces the previous version).
    """
    base = os.path.basename(filename).strip()
    if "\x00" in base:
        raise ValueError("invalid filename")
    if not base:
        raise ValueError("upload filename is empty")
    if base in (".", ".."):
        raise ValueError("invalid filename")
    base = _sanitise_basename(base)
    docs = Path(notes_root) / "documents"
    docs.mkdir(parents=True, exist_ok=True)

    target = docs / base
    if target.resolve().parent != docs.resolve():
        raise ValueError("invalid filename")
    target.write_bytes(data)
    result = {"stored": f"documents/{base}", "markdown": None}

    suffix = target.suffix.lower()
    if suffix in CONVERT_EXTS:
        md = convert(data, suffix)
        md_path = docs / f"{base}.md"
        md_path.write_text(md, encoding="utf-8")
        result["markdown"] = f"documents/{base}.md"
    return result


def markitdown_convert(data: bytes, suffix: str) -> str:
    """Default converter: office bytes -> Markdown via markitdown (writes a temp file)."""
    import tempfile

    from markitdown import MarkItDown

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return MarkItDown().convert(tmp.name).text_content


def lwt_convert(data: bytes, suffix: str) -> str:
    """Convert office/markdown bytes to markdown via llm-wiki-tools, with
    traceability frontmatter. Writes bytes to a temp file (the lwt handlers are
    path-based) and uses ingest_source's stdout mode to get frontmatter + body."""
    import io
    import tempfile
    from contextlib import redirect_stdout
    from pathlib import Path

    from llm_wiki.ingest import ingest_source

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"upload{suffix}"
        src.write_bytes(data)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ingest_source(
                source=src,
                wiki_dir=Path(td),
                ingest_command=f"upload {suffix}",
                output="-",
            )
        return buf.getvalue()
