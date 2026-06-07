"""Structured Ingest proposals: parse the agent's proposal, apply it deterministically.

The agent proposes (it does not write); the frontend applies the confirmed proposal,
so what the user confirms is byte-for-byte what lands. See
docs/adr/0009-propose-confirm-ingest-and-diary-sweep.md.
"""
from __future__ import annotations

import datetime
import json
import re
import secrets
from pathlib import Path

import yaml

from frontend import _atomic

# Slugs: lowercase alnum + hyphen/underscore; 1-64 chars; no path separators.
# Reject anything that could become a path component (no '.', '/', '\\', '..').
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SLUG_PATTERN = SLUG_RE.pattern

# Hard caps on proposal list sizes — defends against DoS via oversized proposals.
MAX_ACTIONS = 50
MAX_TOPICS = 20
MAX_MEETINGS = 10
MAX_TASK_OPS = 50

# Per-field length caps for the propose entry. Mirrors the Pydantic body at the
# HTTP boundary (see frontend/app.py::_SweepTopicEntry / _SweepMeetingEntry) so
# the same limits are enforced at the MCP entry. The Pydantic body imports these
# constants directly — keep the two sides in lock-step.
MAX_DIARY_LEN = 8000
MAX_ACTION_TEXT_LEN = 200
MAX_TOPIC_TEXT_LEN = 8000
MAX_TOPIC_SECTION_LEN = 120
MAX_MEETING_TITLE_LEN = 200
MAX_MEETING_FIELD_LEN = 8000  # summary / decisions / actions / raw
MAX_MEETING_TOPICS_PER = 20
MAX_PROPOSAL_BYTES = 1 * 1024 * 1024  # 1 MiB total JSON size cap

# Known topic/meeting sections (literal set used by the Pydantic model).
# `## Open actions (as of YYYY-MM-DD)` is the regenerated snapshot — also
# accepted, but only when the date is a real \d{4}-\d{2}-\d{2} pattern.
_OPEN_ACTIONS_RE_STRICT = re.compile(
    r"^## Open actions \(as of \d{4}-\d{2}-\d{2}\)$"
)
_VALID_SECTION_HEADERS = (
    "## Overview", "## Current state", "## Open questions",
    "## Key decisions", "## Meetings", "## Documents",
)
VALID_SECTIONS: tuple[str, ...] = _VALID_SECTION_HEADERS


# Date tokens in a todo.txt action line: `due:YYYY-MM-DD` (deadline) and
# `t:YYYY-MM-DD` (tickler/resurface). `(?<!\S)` anchors each to a token start
# (whitespace or line start) so `t:` is not matched inside `upd:` etc.
_DUE_RE = re.compile(r"(?<!\S)due:(\S+)")
_TICKLER_RE = re.compile(r"(?<!\S)t:(\S+)")

# Stable per-action id tag: `id:xxxxxx` (6 base36 chars). Token-anchored so
# `id:` inside other words isn't matched. Used by mutate-via-id paths.
# The bare id value pattern (without the `id:` prefix) — shared by Pydantic
# and agenda/parser.py so all consumers stay in lock-step.
ID_LENGTH = 6
ID_BARE_PATTERN = rf"^[a-z0-9]{{{ID_LENGTH}}}$"
ID_BARE_RE = re.compile(ID_BARE_PATTERN)
_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_ID_TOKEN_RE = re.compile(rf"(?<!\S)id:[a-z0-9]{{{ID_LENGTH}}}(?!\S)")


def gen_id() -> str:
    """A 6-char base36 action id (≈2.2e9 space; collisions handled per-file)."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(ID_LENGTH))


def validate_action_dates(actions: list[str]) -> list[str]:
    """Return human-readable errors for date problems in todo.txt action lines.

    Two **time-independent** checks (so the propose gate stays deterministic and
    test-safe — a wall-clock-relative check would make hardcoded-date tests flaky):

      * malformed ``due:`` / ``t:`` dates (not a real ``YYYY-MM-DD``), and
      * a tickler later than the deadline (``t:`` > ``due:``) — i.e. a reminder
        that fires *after* the thing is due, the exact bug this guards against.

    It deliberately does **not** flag past dates (time-relative) and cannot know
    that a deadline-worded action *should* carry a ``due:`` — that stays the
    agent's job (see notes-agent.md ingest rule 3). Empty list ⇒ all good.
    """
    errors: list[str] = []
    for a in actions:
        due = tick = None
        m = _DUE_RE.search(a)
        if m:
            try:
                due = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                errors.append(f"invalid due: date {m.group(1)!r} in action: {a!r}")
        m = _TICKLER_RE.search(a)
        if m:
            try:
                tick = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                errors.append(f"invalid t: date {m.group(1)!r} in action: {a!r}")
        if due and tick and tick > due:
            errors.append(
                f"tickler t:{tick.isoformat()} is after due:{due.isoformat()} — a "
                f"reminder after the deadline is almost always wrong, in action: {a!r}"
            )
    return errors


class ProposalError(ValueError):
    """The agent output could not be parsed as a structured proposal."""


class ProposalValidationError(ValueError):
    """A proposal field failed structural validation (regex, literal, length)."""


def is_valid_section(section: str) -> bool:
    r"""True if *section* is a known topic section header (exact match or the
    regenerated ``## Open actions (as of YYYY-MM-DD)`` snapshot form with a
    valid ``\d{4}-\d{2}-\d{2}`` date).
    """
    if section in _VALID_SECTION_HEADERS:
        return True
    if bool(_OPEN_ACTIONS_RE_STRICT.fullmatch(section)):
        return True
    return False


def _find_balanced_json_object(text: str) -> str | None:
    """Find the first balanced top-level ``{…}`` object in *text*.

    Robust to inner braces (a topic text containing ``{x}`` must not be
    mis-parsed as a closer). Returns the object substring, or None."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            return text[start:end]
        start = text.find("{", start + 1)
    return None



def _append_diary(notes_root: Path, text: str, now: datetime.datetime) -> None:
    if not text.strip():
        return
    diary = notes_root / "diary"
    diary.mkdir(parents=True, exist_ok=True)
    path = diary / f"{now:%Y-%m-%d}.md"
    if not path.exists():
        _atomic.atomic_write_text(path, f"# Diary {now:%Y-%m-%d}\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {now:%H:%M}\n\n{text.strip()}\n")


def apply_proposal(notes_root: Path | str, prop: dict, *, now: datetime.datetime | None = None, task_ops: list[dict] | None = None) -> dict:
    """Apply a confirmed proposal deterministically. Returns a summary of writes.

    Validation policy: per-item structural checks (slug regex, section literal)
    are enforced *silently* — bad items are dropped, summary counts reflect
    what was actually written. List caps are enforced by silent truncation
    (first MAX_ACTIONS/MAX_TOPICS/MAX_MEETINGS) as a DoS backstop.

    The ``SweepConfirm`` Pydantic boundary at the HTTP layer is the strict
    validation gate — it uses the same regex and section-literal checks and
    rejects malformed input with a 422. This function is the lenient applier
    that direct callers (tests, scripts) can use without pre-validating.

    *task_ops* are applied under the same snapshot/rollback as the proposal
    fields, so a failure mid-apply (e.g. a disk-full on a topic write after
    task_ops have already mutated tasks.todo.txt) restores all files to
    pre-apply state.
    """
    if not isinstance(prop, dict):
        raise ProposalValidationError("proposal is not a dict")
    # Enforce the list caps at the apply level. We SILENTLY cap (truncate) —
    # the HTTP boundary in SweepConfirm rejects with 422 for direct violations,
    # but a direct caller (e.g. a test) gets the same DoS protection without
    # needing to pre-validate.

    # Per-item sanitization: strip control chars from action text (single-line),
    # drop topic/meeting entries whose slug or section is invalid.
    safe_actions: list[str] = []
    for a in (prop.get("actions", []) or []):
        # Strip control characters that could smuggle a second action line
        # into tasks.todo.txt: C0 controls (NUL .. \x08, \x0E .. \x1F, \x7F),
        # C1 controls (\x80 .. \x9F — NEXT LINE, START OF STRING, etc.), actual
        # newline/tab/vertical-tab/form-feed, Unicode line/paragraph separators
        # (U+2028, U+2029). NEL (U+0085) is already covered by the C1 range.
        # We do NOT strip the two-character sequences \n, \r, \t (backslash +
        # letter) — those are legitimate content (e.g. a Windows path C:\new)
        # and real newline bytes are already caught by the control-char class.
        s = str(a)
        s = re.sub(
            r"[\x00-\x08\x0e-\x1f\x7f\x80-\x9f\r\n\t\v\f\u2028\u2029]",
            " ", s,
        ).strip()
        if s:
            safe_actions.append(s)

    safe_topics: list[dict] = []
    for t in (prop.get("topics", []) or []):
        if not isinstance(t, dict):
            continue
        slug = str(t.get("slug", "")).strip()
        section = str(t.get("section", "## Current state")).strip()
        text = str(t.get("text", "")).strip()
        if not slug or not text:
            continue
        if not SLUG_RE.match(slug):
            continue
        if not is_valid_section(section):
            continue
        safe_topics.append({"slug": slug, "section": section, "text": text})

    safe_meetings: list[dict] = []
    for m in (prop.get("meetings", []) or []):
        if not isinstance(m, dict):
            continue
        slug = str(m.get("slug", "")).strip()
        if not slug or not SLUG_RE.match(slug):
            continue
        m_topics = [str(s).strip() for s in (m.get("topics") or [])]
        m_topics = [s for s in m_topics if s and SLUG_RE.match(s)]
        safe_meetings.append({
            "slug": slug,
            "title": str(m.get("title", slug)),
            "topics": m_topics,
            "summary": str(m.get("summary", "")),
            "decisions": str(m.get("decisions", "")),
            "actions": str(m.get("actions", "")),
            "raw": str(m.get("raw", "")),
        })

    root = Path(notes_root)
    now = now or datetime.datetime.now()
    summary: dict = {"diary": False, "actions": 0, "topics": 0, "meetings": 0, "task_ops": None}

    # Bind the apply slices to locals so the snapshot and the apply call use
    # the exact same lists — guards against a future refactor that re-caps
    # inside a helper and silently desyncs the rollback target list.
    actions_for_apply = safe_actions[:MAX_ACTIONS]
    topics_for_apply = safe_topics[:MAX_TOPICS]
    meetings_for_apply = safe_meetings[:MAX_MEETINGS]

    # Snapshot files that will be modified so we can rollback on failure.
    # Each entry: path → (existed_before, content_or_None).
    # Memory bound: O(MAX_ACTIONS + MAX_TOPICS + MAX_MEETINGS) files, each
    # bounded by the user's per-file size (one line per action in
    # tasks.todo.txt, one small topic file per topic, one small meeting file
    # per meeting). Today's caps (50/20/10) keep this well under 1 MB even
    # for very large actions files.
    snapshot: dict[Path, tuple[bool, str | None]] = {}
    # Parent directories the apply may create — we rmdir them in rollback
    # iff they didn't exist before and are empty after the restore. Keeps
    # the rollback footprint identical to "no apply happened".
    dirs_snapshot: dict[Path, bool] = {}
    diary_text = str(prop.get("diary", "")).strip()
    if diary_text:
        p = root / "diary" / f"{now:%Y-%m-%d}.md"
        snapshot[p] = (p.exists(), p.read_text(encoding="utf-8") if p.exists() else None)
        dirs_snapshot[root / "diary"] = (root / "diary").exists()
    if actions_for_apply:
        p = root / "tasks.todo.txt"
        snapshot[p] = (p.exists(), p.read_text(encoding="utf-8") if p.exists() else None)
    for t in topics_for_apply:
        p = root / "topics" / f"{t['slug']}.md"
        if p not in snapshot:
            snapshot[p] = (p.exists(), p.read_text(encoding="utf-8") if p.exists() else None)
        dirs_snapshot[root / "topics"] = (root / "topics").exists()
    for m in meetings_for_apply:
        day = root / "meetings" / f"{now:%Y-%m-%d}"
        p = day / f"{m['slug']}.md"
        if p not in snapshot:
            snapshot[p] = (p.exists(), p.read_text(encoding="utf-8") if p.exists() else None)
        dirs_snapshot[day] = day.exists()
    # Snapshot tasks.todo.txt for task_ops too — the actions block above may
    # have already captured it; skip if so.
    safe_task_ops = list(task_ops or [])
    if safe_task_ops:
        p = root / "tasks.todo.txt"
        if p not in snapshot:
            snapshot[p] = (p.exists(), p.read_text(encoding="utf-8") if p.exists() else None)

    try:
        if diary_text:
            _append_diary(root, diary_text, now)
            summary["diary"] = True
        # Silent cap (DoS hardening): if the caller passed more than MAX, take the
        # first MAX. The Pydantic boundary in SweepConfirm will reject earlier with
        # 422 for HTTP callers; this is the backstop for direct callers.
        summary["actions"] = _append_actions(root, actions_for_apply)
        summary["topics"] = _apply_topics(root, topics_for_apply, now)
        summary["meetings"] = _apply_meetings(root, meetings_for_apply, now)
        if safe_task_ops:
            task_result = apply_task_ops(root, safe_task_ops,
                                         now=now.date() if now else None)
            summary["task_ops"] = task_result
    except Exception:
        # Rollback partial writes: restore snapshotted files to their original
        # state, delete files that didn't exist before. This prevents partial
        # writes (diary+actions when topics fail) from leaking into the next
        # commit (see M2 in the audit). A crash between the write_text and
        # the filesystem fsync is still possible — atomic_write_text below
        # shrinks that window by routing the restore through a sibling .tmp
        # and os.replace() so the file is never observed in a half-written
        # state.
        for path, (existed, content) in snapshot.items():
            try:
                if existed:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _atomic.atomic_write_text(path, content or "", encoding="utf-8")
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass  # best-effort rollback
        # Best-effort: drop any parent directories the apply created and the
        # rollback left empty. rmdir() only succeeds when the directory is
        # empty, so a directory that still has other files (e.g. a pre-existing
        # topic untouched by this apply) is left in place.
        for d, existed in dirs_snapshot.items():
            if not existed:
                try:
                    d.rmdir()
                except OSError:
                    pass
        raise

    return summary


def _append_actions(notes_root: Path, actions: list[str]) -> int:
    if not actions:
        return 0
    path = notes_root / "tasks.todo.txt"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    used = set(_ID_TOKEN_RE.findall(existing))
    stamped: list[str] = []
    for a in actions:
        if _ID_TOKEN_RE.search(a):
            stamped.append(a)
            continue
        new = f"id:{gen_id()}"
        while f"id:{new[3:]}" in used or new in used:
            new = f"id:{gen_id()}"
        used.add(new)
        stamped.append(f"{a.rstrip()} {new}")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    _atomic.atomic_write_text(path, existing + "\n".join(stamped) + "\n", encoding="utf-8")
    return len(stamped)


def backfill_ids(notes_root: Path | str) -> int:
    """Stamp ``id:`` on any task line lacking one. Idempotent; preserves blanks,
    comments, and existing ids. Returns the count stamped."""
    path = Path(notes_root) / "tasks.todo.txt"
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    used = set(_ID_TOKEN_RE.findall(text))
    out: list[str] = []
    stamped = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or _ID_TOKEN_RE.search(line):
            out.append(line)
            continue
        new = f"id:{gen_id()}"
        while new in used:
            new = f"id:{gen_id()}"
        used.add(new)
        out.append(f"{line.rstrip()} {new}")
        stamped += 1
    if stamped:
        _atomic.atomic_write_text(path, "\n".join(out) + "\n", encoding="utf-8")
    return stamped


_PRIORITY_TOK_RE = re.compile(r"^\([A-D]\)$")


def _rewrite_line(line: str, op: str, value: str | None, today: str) -> str:
    """Apply one op to a single todo.txt line, bumping upd: to *today*."""
    tokens = line.split()
    if tokens and tokens[0] == "x":
        done, rest = True, tokens[1:]
    else:
        done, rest = False, tokens
    # locate priority (first token if it matches)
    prio_idx = 0 if rest and _PRIORITY_TOK_RE.match(rest[0]) else None
    if op == "reprioritize" and value:
        new_prio = f"({value})"
        if prio_idx is not None:
            rest[prio_idx] = new_prio
        else:
            rest.insert(0, new_prio)
    elif op == "retickle" and value:
        rest = [t for t in rest if not t.startswith("t:")]
        # keep ticklers next to other date tags — append; ordering is cosmetic
        rest.append(f"t:{value}")
    elif op == "complete":
        done = True
    # bump upd:
    rest = [t for t in rest if not t.startswith("upd:")]
    rest.append(f"upd:{today}")
    prefix = "x " if done else ""
    return prefix + " ".join(rest)


def apply_task_ops(notes_root: Path | str, ops: list[dict], *, now: datetime.date | None = None) -> dict:
    """Apply mutation ops to existing actions, matched by ``id:``. Returns
    ``{"applied": n, "errors": [...]}``. Atomic write; bumps ``upd:`` to today.
    retickle/reprioritize values are validated; bad values become errors."""
    path = Path(notes_root) / "tasks.todo.txt"
    today = (now or datetime.date.today()).isoformat()
    errors: list[str] = []
    if not path.exists():
        return {"applied": 0, "errors": [f"no tasks.todo.txt; ops: {len(ops)}"]}
    lines = path.read_text(encoding="utf-8").splitlines()
    by_id = {}
    for i, line in enumerate(lines):
        m = _ID_TOKEN_RE.search(line)
        if m:
            by_id[m.group(0)[3:]] = i
    applied = 0
    for op in ops:
        oid, name, value = str(op.get("id", "")), str(op.get("op", "")), op.get("value")
        if oid not in by_id:
            errors.append(f"no action with id {oid!r}")
            continue
        if name not in ("complete", "reprioritize", "retickle"):
            errors.append(f"unknown op {name!r} for id {oid}")
            continue
        if name == "reprioritize" and value not in ("A", "B", "C", "D"):
            errors.append(f"reprioritize id {oid}: value must be A-D, got {value!r}")
            continue
        if name == "retickle" and validate_action_dates([f"t:{value}"]):
            errors.append(f"retickle id {oid}: invalid date {value!r}")
            continue
        lines[by_id[oid]] = _rewrite_line(lines[by_id[oid]], name, value, today)
        applied += 1
    if applied:
        _atomic.atomic_write_text(path, "\n".join(lines) + "\n", encoding="utf-8")
    return {"applied": applied, "errors": errors}


# Open-actions section marker, regenerated by _regenerate_open_actions_block.
_OPEN_ACTIONS_RE = re.compile(
    r"^## Open actions \(as of \d{4}-\d{2}-\d{2}\)\s*$", re.MULTILINE
)


def _regenerate_open_actions_block(notes_root: Path, topic_body: str, now: datetime.datetime) -> str:
    """Replace the trailing ``## Open actions (as of …)`` block in *topic_body*
    with a fresh snapshot computed from ``notes_root / "tasks.todo.txt"``.

    If no such block exists in the topic, the new block is appended at EOF.
    Only the LAST ``## Open actions (as of …)`` occurrence is replaced; this
    preserves any earlier provenance the topic may carry.
    """
    today = now.strftime("%Y-%m-%d")
    heading = f"## Open actions (as of {today})"
    new_block = _build_open_actions_block(notes_root, topic_body, now, heading)
    # Replace last occurrence (or append).
    matches = list(_OPEN_ACTIONS_RE.finditer(topic_body))
    if matches:
        last = matches[-1]
        # Drop the old block (from its heading line to EOF, since the snapshot
        # is always the last block of the topic).
        return topic_body[: last.start()].rstrip() + "\n\n" + new_block
    suffix = "" if topic_body.endswith("\n") else "\n"
    return f"{topic_body}{suffix}\n{new_block}\n"


def _build_open_actions_block(notes_root: Path, topic_body: str, now: datetime.datetime, heading: str) -> str:
    """Build the Open actions block, filtering by the +<slug> tags in the topic.

    To find the topic's slug, read the YAML frontmatter; if absent, keep all
    actions (the topic is brand-new — there's no +<slug> tag to filter by yet).
    """
    slug = _read_topic_slug(topic_body)
    task_path = notes_root / "tasks.todo.txt"
    if not task_path.exists():
        return heading + "\n"
    lines = [ln for ln in task_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if slug:
        tag = f"+{slug}"
        lines = [ln for ln in lines if tag in ln]
    if not lines:
        return heading + "\n\n(none)\n"
    return heading + "\n\n" + "\n".join("- " + ln for ln in lines) + "\n"


def _read_topic_slug(topic_body: str) -> str | None:
    if not topic_body.startswith("---\n"):
        return None
    end = topic_body.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(topic_body[4:end]) or {}
    except yaml.YAMLError:
        return None
    return str(fm.get("slug", "")).strip() or None


_TOPIC_SECTIONS = _VALID_SECTION_HEADERS


def _new_topic(slug: str, now: datetime.datetime) -> str:
    sections = "\n\n".join(_TOPIC_SECTIONS)
    # YAML-quote the slug and title so a hostile or odd slug cannot break out
    # of the frontmatter block. yaml.safe_dump is the source of truth for the
    # block — we write a string header manually but use safe_dump for the
    # body so escaping is correct.
    fm = yaml.safe_dump(
        {"slug": slug, "title": slug, "tags": [], "status": "active"},
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{fm}---\n{sections}\n\n## Open actions (as of {now:%Y-%m-%d})\n"


def _insert_in_section(content: str, section: str, text: str) -> str:
    """Insert *text* at the end of *section* (before the next ``## `` heading or EOF).
    If the section is absent, append it as a new section at EOF."""
    lines = content.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == section.strip())
    except StopIteration:
        suffix = "" if content.endswith("\n") else "\n"
        return f"{content}{suffix}\n{section}\n\n{text}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    block = lines[start:end]
    while block and block[-1].strip() == "":
        block.pop()
    block.append("")
    block.append(text)
    new_lines = lines[:start] + block + ([""] if end < len(lines) else []) + lines[end:]
    return "\n".join(new_lines) + ("\n" if content.endswith("\n") else "")


def _apply_topics(notes_root: Path, topics: list, now: datetime.datetime) -> int:
    """Apply topics to disk. Trusts that *topics* has been pre-filtered by
    ``safe_topics`` in ``apply_proposal`` — slug regex and section literal
    checks already ran there; we only guard against empty values."""
    count = 0
    for t in topics:
        slug = str(t.get("slug", "")).strip()
        text = str(t.get("text", "")).strip()
        section = str(t.get("section", "## Current state")).strip()
        if not slug or not text:
            continue
        tdir = notes_root / "topics"
        tdir.mkdir(parents=True, exist_ok=True)
        path = tdir / f"{slug}.md"
        content = path.read_text(encoding="utf-8") if path.exists() else _new_topic(slug, now)
        # Insert the new note under the requested section, then regenerate the
        # ## Open actions snapshot so the topic's view of the task list is
        # always current (per CONTEXT.md: "a stamped snapshot you regenerate
        # when you edit that topic file").
        inserted = _insert_in_section(content, section, text)
        content = _regenerate_open_actions_block(notes_root, inserted, now)
        _atomic.atomic_write_text(path, content, encoding="utf-8")
        count += 1
    return count


def _apply_meetings(notes_root: Path, meetings: list, now: datetime.datetime) -> int:
    """Apply meetings to disk. Trusts that *meetings* has been pre-filtered by
    ``safe_meetings`` in ``apply_proposal`` — slug regex already ran there."""
    count = 0
    for m in meetings:
        slug = str(m.get("slug", "")).strip()
        if not slug:
            continue
        day = notes_root / "meetings" / f"{now:%Y-%m-%d}"
        day.mkdir(parents=True, exist_ok=True)
        m_topics = list(m.get("topics") or [])
        # Build frontmatter via yaml.safe_dump (same pattern as _new_topic) so
        # NUL bytes, YAML-significant characters, and break-out sequences like
        # ``\n---\n`` in the title are properly YAML-quoted and cannot escape
        # the frontmatter block.
        fm = yaml.safe_dump(
            {
                "date": now.date(),
                "title": m.get("title", slug),
                "topics": m_topics,
            },
            default_flow_style=False,
            sort_keys=False,
        )
        body = (
            f"---\n{fm}---\n"
            f"## Summary\n{m.get('summary', '')}\n\n"
            f"## Decisions\n{m.get('decisions', '')}\n\n"
            f"## Actions\n{m.get('actions', '')}\n\n"
            f"## Raw notes\n{m.get('raw', '')}\n"
        )
        _atomic.atomic_write_text(day / f"{slug}.md", body, encoding="utf-8")
        count += 1
    return count
