from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from frontend import proposal as _proposal
from frontend._atomic import atomic_write_text

# Re-export the slug regex so callers (e.g. tests) that imported
# `presenter.server._SLUG_PATTERN` keep working.
_SLUG_RE = _proposal.SLUG_RE
_SLUG_PATTERN = _proposal.SLUG_PATTERN
_VALID_SECTION_HEADERS = _proposal.VALID_SECTIONS


def _is_valid_section(section: str) -> bool:
    return _proposal.is_valid_section(section)


mcp = FastMCP("present")

# Bare tool names — OpenCode namespaces as `present_<name>` via the server key
# `present`; the agent-visible tools are therefore `present_present` and
# `present_propose` (the server key prefixes the bare name).
TOOL_NAMES = ("present", "propose", "present_brief", "present_task")


def _notes_root() -> Path:
    root = os.environ.get("NOTES_ROOT")
    if root is None:
        raise RuntimeError("NOTES_ROOT must be set in the environment")
    return Path(root)


@mcp.tool()
def present(path: str) -> dict:
    """Show a workspace file (markdown) in the user's Presentation pane.

    `path` is relative to the notes workspace (e.g. "meetings/2026-05-31/atlas.md").
    This is a UI signal: it does not read or modify the file. The frontend renders
    the file in the right-hand pane.
    """
    return {"ok": True, "presented": path}


def _load_staging(root: Path) -> tuple[dict, bool]:
    """Load the existing ``inbox/_proposal.json`` staging, or return the empty
    default. Ensures the ``task_ops`` key is present so callers can append
    directly. A malformed file is treated as empty (a fresh start).

    Returns ``(data, was_lost)`` where *was_lost* is True when an existing
    staging file could not be parsed and had to be replaced.
    """
    stage = root / "inbox" / "_proposal.json"
    had_file = stage.is_file()
    if had_file:
        try:
            data = json.loads(stage.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("task_ops", [])
                return data, False
        except json.JSONDecodeError:
            pass
    return {"diary": "", "actions": [], "topics": [], "meetings": [], "task_ops": []}, had_file


@mcp.tool()
def present_brief(kind: str, content: str) -> dict:
    """Write a daily/weekly brief to briefs/<date>-<kind>.md and show it.

    `kind` is "daily" or "weekly". A brief is a regenerable digest, so this
    writes directly (no confirm) and overwrites same-day. The agent generates
    the markdown; the frontend persists it.
    """
    if kind not in ("daily", "weekly"):
        return {"ok": False, "error": "kind must be 'daily' or 'weekly'"}
    root = _notes_root()
    briefs = root / "briefs"
    briefs.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.date.today():%Y-%m-%d}-{kind}.md"
    atomic_write_text(briefs / name, content, encoding="utf-8")
    return {"ok": True, "path": f"briefs/{name}"}


@mcp.tool()
def present_task(id: str, op: str, value: str | None = None) -> dict:
    """Stage a mutation of an EXISTING action (by its id:) for user confirmation.

    op ∈ {"complete", "reprioritize" (value=A-D), "retickle" (value=YYYY-MM-DD)}.
    Read tasks.todo.txt first to find the id:. The op is staged into the shared
    proposal; the user confirms it in the frontend, which applies it.
    """
    if op not in ("complete", "reprioritize", "retickle"):
        return {"ok": False, "error": "op must be complete|reprioritize|retickle"}
    if op == "reprioritize" and value not in ("A", "B", "C", "D"):
        return {"ok": False, "error": "reprioritize value must be A-D"}
    if op == "retickle" and (not value or _proposal.validate_action_dates([f"t:{value}"])):
        return {"ok": False, "error": "retickle value must be YYYY-MM-DD"}
    root = _notes_root()
    tasks = root / "tasks.todo.txt"
    text = tasks.read_text(encoding="utf-8") if tasks.exists() else ""
    if not re.search(rf"(?<!\S)id:{re.escape(id)}(?!\S)", text):
        return {"ok": False, "error": f"no action with id {id!r}"}
    data, was_lost = _load_staging(root)
    data["task_ops"].append({"id": id, "op": op, "value": value})
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    atomic_write_text(root / "inbox" / "_proposal.json",
                      json.dumps(data, indent=2), encoding="utf-8")
    result: dict = {"ok": True, "staged": {"id": id, "op": op, "value": value}}
    if was_lost:
        result["warning"] = "prior staging was corrupted and replaced"
    return result


def _cap_field(value: str, limit: int, name: str, errors: list[str]) -> str:
    if len(value) > limit:
        errors.append(f"{name} exceeds {limit} chars (got {len(value)})")
        return value[:limit]
    return value


@mcp.tool()
def propose(proposal: str) -> dict:
    """Submit a structured Ingest proposal for the user to confirm.

    The agent MUST use this tool for ALL ingest operations — never write
    proposal content (actions, topics, meetings, diary) directly with file
    tools. The frontend will show the proposal to the user; on confirm it
    applies the proposal deterministically.

    Parameters:
        proposal: A JSON string matching the Ingest schema:
            {
              "diary": "narrative summary",
              "actions": ["(B) text +topic due:… t:… upd:…", ...],
              "topics": [{"slug": "...", "section": "## Current state", "text": "..."}],
              "meetings": [{"slug": "...", "title": "...", "topics": [...], ...}]
            }
    """
    # Total size cap (DoS hardening) — checked on the raw string so a
    # pathological payload never reaches json.loads.
    if len(proposal.encode("utf-8")) > _proposal.MAX_PROPOSAL_BYTES:
        return {
            "ok": False,
            "error": (
                f"proposal exceeds {_proposal.MAX_PROPOSAL_BYTES} bytes"
            ),
        }

    try:
        data = json.loads(proposal)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid JSON: syntax error in proposal"}

    if not isinstance(data, dict):
        return {"ok": False, "error": "proposal must be a JSON object"}

    errors: list[str] = []
    required_keys = ("diary", "actions", "topics", "meetings")
    for k in required_keys:
        if k not in data:
            errors.append(f"missing required key: {k}")
    if errors:
        return {"ok": False, "error": "; ".join(errors)}

    diary = _cap_field(
        str(data.get("diary", "")),
        _proposal.MAX_DIARY_LEN,
        "diary",
        errors,
    )
    actions_raw = data.get("actions", [])
    if not isinstance(actions_raw, list):
        actions_raw = []
    if len(actions_raw) > _proposal.MAX_ACTIONS:
        return {
            "ok": False,
            "error": (
                f"actions list exceeds {_proposal.MAX_ACTIONS} entries"
            ),
        }
    topics_raw = data.get("topics", [])
    if not isinstance(topics_raw, list):
        topics_raw = []
    if len(topics_raw) > _proposal.MAX_TOPICS:
        return {
            "ok": False,
            "error": (
                f"topics list exceeds {_proposal.MAX_TOPICS} entries"
            ),
        }
    meetings_raw = data.get("meetings", [])
    if not isinstance(meetings_raw, list):
        meetings_raw = []
    if len(meetings_raw) > _proposal.MAX_MEETINGS:
        return {
            "ok": False,
            "error": (
                f"meetings list exceeds {_proposal.MAX_MEETINGS} entries"
            ),
        }

    warnings: list[str] = []

    valid_actions: list[str] = []
    for a in actions_raw:
        if isinstance(a, str) and a.strip():
            valid_actions.append(
                _cap_field(
                    a.strip(),
                    _proposal.MAX_ACTION_TEXT_LEN,
                    "action text",
                    errors,
                )
            )
        else:
            warnings.append("non-empty action dropped (not a string or empty)")

    valid_topics = []
    for t in topics_raw:
        if not isinstance(t, dict):
            warnings.append("non-dict topic dropped")
            continue
        slug = str(t.get("slug", "")).strip()
        section = _cap_field(
            str(t.get("section", "## Current state")).strip(),
            _proposal.MAX_TOPIC_SECTION_LEN,
            "topic section",
            errors,
        )
        text = _cap_field(
            str(t.get("text", "")).strip(),
            _proposal.MAX_TOPIC_TEXT_LEN,
            "topic text",
            errors,
        )
        if slug and re.match(_SLUG_PATTERN, slug) and text and _is_valid_section(section):
            valid_topics.append({"slug": slug, "section": section, "text": text})
        else:
            warnings.append(f"topic {slug or '(no slug)'!r} dropped: invalid slug/section/text")

    valid_meetings = []
    for m in meetings_raw:
        if not isinstance(m, dict):
            warnings.append("non-dict meeting dropped")
            continue
        slug = str(m.get("slug", "")).strip()
        if not (slug and re.match(_SLUG_PATTERN, slug)):
            warnings.append(f"meeting {slug or '(no slug)'!r} dropped: invalid slug")
            continue
        m_topics = [
            s for s in m.get("topics", [])
            if isinstance(s, str) and re.match(_SLUG_PATTERN, s)
        ]
        if len(m_topics) > _proposal.MAX_MEETING_TOPICS_PER:
            return {
                "ok": False,
                "error": (
                    f"meeting {slug!r} topics list exceeds"
                    f" {_proposal.MAX_MEETING_TOPICS_PER} entries"
                ),
            }
        valid_meetings.append({
            "slug": slug,
            "title": _cap_field(
                str(m.get("title", slug)),
                _proposal.MAX_MEETING_TITLE_LEN,
                "meeting title",
                errors,
            ),
            "topics": m_topics,
            "summary": _cap_field(
                str(m.get("summary", "")),
                _proposal.MAX_MEETING_FIELD_LEN,
                "meeting summary",
                errors,
            ),
            "decisions": _cap_field(
                str(m.get("decisions", "")),
                _proposal.MAX_MEETING_FIELD_LEN,
                "meeting decisions",
                errors,
            ),
            "actions": _cap_field(
                str(m.get("actions", "")),
                _proposal.MAX_MEETING_FIELD_LEN,
                "meeting actions",
                errors,
            ),
            "raw": _cap_field(
                str(m.get("raw", "")),
                _proposal.MAX_MEETING_FIELD_LEN,
                "meeting raw",
                errors,
            ),
        })

    tags_in_actions: set[str] = set()
    for a in valid_actions:
        for word in a.split():
            if word.startswith("+") and len(word) > 1:
                tag = word[1:]
                # Skip tags that aren't valid slugs; they're noise.
                if re.match(_SLUG_PATTERN, tag):
                    tags_in_actions.add(tag)
    topic_slugs = {t["slug"] for t in valid_topics}
    if not tags_in_actions.issubset(topic_slugs):
        missing = tags_in_actions - topic_slugs
        errors.append(
            f"+tag topics missing from proposal: {', '.join(sorted(missing))}"
        )

    # Date sanity: malformed dates + tickler-after-deadline (the exact class of
    # bug from the 2026-06-05 mis-file, where a reminder was set days after the
    # event). Time-independent checks only, so the gate stays deterministic.
    errors.extend(_proposal.validate_action_dates(valid_actions))

    if not diary.strip() and (valid_actions or valid_topics or valid_meetings):
        errors.append("diary must be non-empty when actions/topics/meetings are present")

    if errors:
        return {"ok": False, "error": "; ".join(errors)}

    root = _notes_root()
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    stage = inbox / "_proposal.json"
    # Merge with any existing staging so task_ops (from present_task) and
    # additions (from propose) land in the same file the frontend confirms.
    # Atomic write: route through a sibling .tmp + os.replace so a crash
    # mid-write can never leave a half-written staging file (which would
    # surface to the UI as a 500 'corrupted proposal' and lock the
    # propose-confirm handshake until manual cleanup). The frontend
    # _atomic helper is stdlib-only (os + pathlib) so presenter can
    # import it without acquiring any package-level dependency.
    data, was_lost = _load_staging(root)
    if was_lost:
        warnings.append("prior staging was corrupted and replaced")
    data.update({
        "diary": diary,
        "actions": valid_actions,
        "topics": valid_topics,
        "meetings": valid_meetings,
    })
    atomic_write_text(stage, json.dumps(data, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "diary": bool(diary.strip()),
        "action_count": len(valid_actions),
        "topic_count": len(valid_topics),
        "meeting_count": len(valid_meetings),
        "warnings": warnings or None,
    }


def _require_notes_root() -> None:
    """Fail-fast guard: NOTES_ROOT must be set in the environment.

    Exposed as a free function (rather than inlined in ``main``) so the
    guard is directly testable without spawning a thread to catch
    ``mcp.run()``'s blocking stdio loop.
    """
    if "NOTES_ROOT" not in os.environ:
        raise RuntimeError("NOTES_ROOT must be set in the environment")


def main() -> None:
    _require_notes_root()
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
