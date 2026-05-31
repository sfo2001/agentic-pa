"""Build the Chief-of-Staff Notes install layout (ADR-0005 / D-opencode-sandbox).

The canonical layout::

    <install-root>/        # NOT a git repo; agent cannot reach parent files
      opencode.json        # OpenCode config (found by config walk-up, not by agent)
      notes-agent.md       # system prompt (referenced by path in opencode.json)
      notes.git/           # split git-dir for notes audit repo
      oc-home/             # isolated HOME/XDG for OpenCode process
      workspace/           # THE sandbox = OpenCode launch cwd = NOTES_ROOT
        inbox/ meetings/ topics/ documents/ briefs/ archive/
        tasks.todo.txt

The install-root must NOT be, or be inside, an existing git repository.  If a
``.git`` entry exists at or above the install-root, ``init_install`` raises
``RuntimeError`` — installing inside a git repo would expand the agent's
sandbox boundary to the git work-tree root (see D-opencode-sandbox.md).
"""
from __future__ import annotations

import json
from pathlib import Path

from frontend.config import CANONICAL_PROMPT_PATH, build_opencode_config

# Canonical system prompt ships inside the installable ``frontend`` package.
_CANONICAL_PROMPT = CANONICAL_PROMPT_PATH


def _has_git_ancestor(path: Path) -> bool:
    """Return True if *path* or any of its ancestors contains a ``.git`` entry."""
    current = path.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return True
    return False


def init_install(
    install_root: Path | str,
    *,
    model_endpoint: str,
    model_id: str,
    agenda_server: str,
) -> dict:
    """Create (or verify) the Chief-of-Staff Notes install layout.

    Args:
        install_root: Target directory for the install (will be created).
        model_endpoint: Base URL of the OpenAI-compatible inference server.
        model_id: Model identifier string.
        agenda_server: Absolute path to the agenda-server executable.

    Returns:
        A dict with keys ``install_root``, ``workspace``, ``git_dir``,
        ``opencode_json``.

    Raises:
        RuntimeError: If ``install_root`` or any ancestor already contains a
            ``.git`` entry.  Placing the install inside a git repo would expand
            the OpenCode sandbox boundary to the git work-tree root.
    """
    root = Path(install_root).resolve()

    # ------------------------------------------------------------------
    # Guard: refuse to install inside an existing git repository.
    # ------------------------------------------------------------------
    if _has_git_ancestor(root):
        raise RuntimeError(
            f"Cannot install inside an existing git repo: a .git entry was found "
            f"at or above {root}.  The install-root must NOT be a git repo "
            "(placing it inside one would expand the agent sandbox boundary — "
            "see docs/decisions/D-opencode-sandbox.md)."
        )

    work = root / "workspace"
    git_dir = root / "notes.git"
    oc_home = root / "oc-home"

    # ------------------------------------------------------------------
    # Create directory tree (idempotent)
    # ------------------------------------------------------------------
    for d in [
        root,
        work,
        oc_home,
        work / "inbox",
        work / "meetings",
        work / "topics",
        work / "documents",
        work / "briefs",
        work / "archive",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    tasks_file = work / "tasks.todo.txt"
    if not tasks_file.exists():
        tasks_file.touch()

    # Keep llm-wiki-tools' runtime artifacts out of the per-turn notes git: the
    # BM25 cache (.lwt_cache/) and ingest temp (.tmp/) are derived, not content.
    # Append-if-missing (not create-only) so re-installs over an existing
    # .gitignore still gain the entries.
    gitignore = work / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = existing.splitlines()
    for entry in (".lwt_cache/", ".tmp/"):
        if entry not in lines:
            lines.append(entry)
    new_text = "\n".join(lines) + "\n"
    if new_text != existing:
        gitignore.write_text(new_text, encoding="utf-8")

    # ------------------------------------------------------------------
    # Write notes-agent.md into the install-root (parent, not workspace).
    # Rewritten unconditionally on every (re-)install so it stays in sync with
    # opencode.json (also rewritten below) — a re-install picks up an updated
    # canonical prompt rather than silently keeping the stale copy.
    # ------------------------------------------------------------------
    prompt_dest = root / "notes-agent.md"
    prompt_dest.write_text(_CANONICAL_PROMPT.read_text(encoding="utf-8"), encoding="utf-8")

    # ------------------------------------------------------------------
    # Generate opencode.json into the install-root
    # ------------------------------------------------------------------
    present_server = str(Path(agenda_server).parent / "present-server")
    config = build_opencode_config(
        model_endpoint=model_endpoint,
        model_id=model_id,
        notes_root=str(work),
        agenda_server=agenda_server,
        prompt_path=str(prompt_dest),
        present_server=present_server,
    )
    opencode_json = root / "opencode.json"
    opencode_json.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Initialise the split notes git repo (work-tree = workspace, git-dir
    # = notes.git/ in parent — no .git entry at or above workspace/).
    # ------------------------------------------------------------------
    from frontend import versioning  # local import avoids circular-import risk

    versioning.ensure_repo(work, git_dir=git_dir)

    return {
        "install_root": root,
        "workspace": work,
        "git_dir": git_dir,
        "opencode_json": opencode_json,
    }
