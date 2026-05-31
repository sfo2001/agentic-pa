from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agenda import engine

mcp = FastMCP("notes")

# Bare tool names — OpenCode namespaces these as notes_<name> (server key "notes"),
# so the agent sees notes_today / notes_review / notes_topic / notes_search.
# This is the read-only Ground Truth service: deterministic reads over the Ground
# Truth — agenda views plus BM25 search; never writes.
# Registering prefixed names would produce the double-prefix notes_notes_*.
TOOL_NAMES = ("today", "review", "topic", "search")


def _notes_root() -> Path:
    # In production NOTES_ROOT is injected by the launcher/bootstrap (= workspace/).
    # "." is only a dev fallback for running the server standalone from a notes dir.
    return Path(os.environ.get("NOTES_ROOT") or ".")


@mcp.tool()
def today() -> dict:
    """Today's agenda: do-now, schedule, resurfacing, overdue, stale-important."""
    return engine.today(_notes_root())


@mcp.tool()
def review() -> dict:
    """Weekly review: per-topic staleness, stale topics, ticklers landing this week."""
    return engine.review(_notes_root())


@mcp.tool()
def topic(slug: str) -> dict:
    """One topic's open actions, ticklers, and recent meetings."""
    return engine.topic(_notes_root(), slug)


# Search ranks over the live Ground Truth only — processed/derived areas are
# excluded so stale copies never outrank current topics/meetings.
_SEARCH_EXCLUDED = {"archive", "briefs"}


@mcp.tool()
def search(query: str, n: int = 10) -> list[dict]:
    """BM25 keyword search over the Ground Truth. Returns ranked
    {path, score, snippet}. Pull this when you need to find topics/meetings by
    content; then read the top hits and cite them."""
    from llm_wiki.search import search as _search

    root = _notes_root()
    out: list[dict] = []
    # Over-fetch, then drop excluded subtrees, so the result still holds up to n.
    for r in _search(root, query, n=n * 3):
        # Never surface a path outside the Ground Truth (e.g. a poisoned BM25
        # cache pointing elsewhere) — confine results to NOTES_ROOT.
        if not r.path.is_relative_to(root):
            continue
        rel = r.path.relative_to(root)
        if rel.parts and rel.parts[0] in _SEARCH_EXCLUDED:
            continue
        out.append({"path": rel.as_posix(), "score": round(r.score, 2), "snippet": r.snippet})
        if len(out) >= n:
            break
    return out


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
