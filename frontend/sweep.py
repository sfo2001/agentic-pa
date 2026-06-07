"""Sweep: turn the conversation transcript into filed structure via Ingest.

The frontend (not the sandboxed agent) reads the transcript, since the OpenCode
store lives outside the workspace. State is a small ``.sweep-state.json`` file
mapping sessionID → last-processed message id. The state file lives next to
the split git-dir (outside the agent's ``workspace/`` sandbox — see
ADR-0005) so the agent can never read or write it via its file tools.
See ``docs/adr/0009-propose-confirm-ingest-and-diary-sweep.md``.
"""
from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path

# Strictly-monotonic guard for make_capture_stamp: datetime.now()'s resolution is
# coarse on some platforms (Windows' system clock can repeat the same microsecond
# across two tight calls), which would collide two Sweep captures onto the same
# inbox/<stamp>.md filename — the second silently overwriting the first. Tracking
# the last stamp and advancing by ≥1µs guarantees uniqueness regardless of clock
# granularity, keeps the stamps sortable, and preserves the 6-digit %f format.
_stamp_lock = threading.Lock()
_last_stamp_dt: datetime.datetime | None = None


def _default_state_path(notes_root: Path | str, git_dir: Path | str | None) -> Path:
    """Return the state-file path: prefer the split git-dir (outside the
    workspace sandbox), fall back to ``notes_root/.sweep-state.json`` when
    no git_dir is given (e.g. some test fixtures).
    """
    if git_dir is not None:
        return Path(git_dir) / ".sweep-state.json"
    return Path(notes_root) / ".sweep-state.json"


def _load_state(notes_root: Path | str, *, git_dir: Path | str | None = None) -> dict:
    p = _default_state_path(notes_root, git_dir)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_watermark(
    notes_root: Path | str,
    session_id: str,
    *,
    git_dir: Path | str | None = None,
) -> str | None:
    """Return the last-processed message id for *session_id*, or None."""
    val = _load_state(notes_root, git_dir=git_dir).get(session_id)
    return val if isinstance(val, str) else None


def write_watermark(
    notes_root: Path | str,
    session_id: str,
    message_id: str,
    *,
    git_dir: Path | str | None = None,
) -> None:
    """Persist the watermark for *session_id* (merging, not clobbering siblings)."""
    state = _load_state(notes_root, git_dir=git_dir)
    state[session_id] = message_id
    _default_state_path(notes_root, git_dir).write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


WINDOW_CHARS = 6000  # ~1.5k tokens; one bounded Ingest unit so the agent can't overflow


def slice_window(
    messages: list[dict], *, after_id: str | None = None, budget: int = WINDOW_CHARS
) -> tuple[list[dict], str | None]:
    """Return ``(window, last_id)``: the next bounded run of messages strictly
    after *after_id*. Accumulates until adding another message would exceed
    *budget* chars, but always takes at least one message so an oversized lone
    message still makes progress. ``([] , None)`` when nothing remains.
    """
    if after_id is not None:
        idx = next((i for i, m in enumerate(messages) if m["id"] == after_id), -1)
        remaining = messages[idx + 1:] if idx >= 0 else messages
    else:
        remaining = messages
    window: list[dict] = []
    used = 0
    for m in remaining:
        size = len(m.get("text", ""))
        if window and used + size > budget:
            break
        window.append(m)
        used += size
    if not window:
        return [], None
    return window, window[-1]["id"]


_ROLE_LABEL = {"user": "you", "assistant": "assistant"}


def render_window_text(messages: list[dict]) -> str:
    """Render a window as the raw Inbox capture: one labelled block per message."""
    blocks = [
        f"**{_ROLE_LABEL.get(m.get('role', ''), m.get('role', ''))}:** {m.get('text', '')}"
        for m in messages
    ]
    return "\n\n".join(blocks) + "\n"


def make_capture_stamp() -> str:
    """Return a filename-safe capture stamp with microsecond precision.

    Microsecond precision (vs the old `%H%M%S`) prevents same-second
    collisions when a user mashes the Sweep button; the prefix is the
    same date+time grid the inbox already uses, so a 2026-06-04-1430
    capture sorts next to its 1430 siblings in `ls`.

    The stamp is strictly monotonic per process: if the clock has not advanced
    since the previous call (coarse timers on Windows can repeat a microsecond),
    we advance by 1µs so two captures never share a filename. timedelta carries
    into seconds/minutes as needed and `%f` stays six digits.
    """
    global _last_stamp_dt
    with _stamp_lock:
        now = datetime.datetime.now()
        if _last_stamp_dt is not None and now <= _last_stamp_dt:
            now = _last_stamp_dt + datetime.timedelta(microseconds=1)
        _last_stamp_dt = now
    return now.strftime("%Y-%m-%d-%H%M%S-%f")


def write_capture(notes_root: Path | str, text: str, *, stamp: str) -> Path:
    """Write *text* to ``inbox/<stamp>.md`` (the Sweep's Inbox capture). Returns path."""
    inbox = Path(notes_root) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{stamp}.md"
    path.write_text(text, encoding="utf-8")
    return path


def archive_capture(notes_root: Path | str, capture: Path) -> Path:
    """Move a processed capture from ``inbox/`` to ``archive/``. Returns new path."""
    archive = Path(notes_root) / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / capture.name
    capture.replace(dest)
    return dest
