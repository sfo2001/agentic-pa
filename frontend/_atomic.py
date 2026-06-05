"""Atomic file replacement helper.

Writes content to a sibling ``.tmp`` file in the same directory and then
``os.replace()`` swaps it into place. ``os.replace`` is atomic on POSIX and
Windows — readers see either the old or the new content, never a truncated
intermediate. A crash or process kill between the write and the replace
leaves the original file intact and the ``.tmp`` file as debris for the
next call to clean up (or for manual inspection).
"""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path | str, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically.

    Raises ``OSError`` on failure; the ``.tmp`` debris is cleaned up best-effort
    before re-raising so the caller's directory is left tidy.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        os.replace(tmp, p)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # debris; not the caller's problem
        raise
