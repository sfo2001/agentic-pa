"""Frontend-owned git versioning of the notes tree (ADR-0003).

The agent is sandboxed (no shell), so the *frontend* commits the notes tree after
each operation, making changes reversible (undo = revert). The notes tree is its
OWN git repo, separate from the application code repo, and commits use a fixed
generic identity (never the user's).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_COMMITTER_NAME = "Notes Assistant"
_COMMITTER_EMAIL = "notes@localhost"


def _git(
    work_tree: Path | str,
    *args: str,
    git_dir: Path | str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    base = ["git"]
    if git_dir is not None:
        base += [f"--git-dir={Path(git_dir)}", f"--work-tree={Path(work_tree)}"]
    else:
        base += ["-C", str(work_tree)]
    return subprocess.run(
        [*base, *args],
        capture_output=True, text=True, check=check,
    )


def is_repo(notes_root: Path | str, git_dir: Path | str | None = None) -> bool:
    return (Path(git_dir) if git_dir is not None else Path(notes_root) / ".git").is_dir()


def ensure_repo(notes_root: Path | str, git_dir: Path | str | None = None) -> None:
    """Initialise ``notes_root`` as its own git repo (idempotent). Sets a generic
    committer identity and makes an initial commit so HEAD always exists.

    When ``git_dir`` is given the metadata directory is placed there instead of
    inside ``notes_root`` (split git-dir/work-tree, required by ADR-0005).

    Raises ``RuntimeError`` if ``notes_root`` overlaps with the application source
    tree (prevents accidentally versioning the code repo as notes)."""
    app_dir = Path(__file__).resolve().parent          # frontend/
    target = Path(notes_root).resolve()
    if app_dir == target or app_dir.is_relative_to(target) or target.is_relative_to(app_dir):
        raise RuntimeError(
            f"NOTES_ROOT ({target}) is inside the application source tree; "
            "point it at a separate directory outside the code repo")
    target.mkdir(parents=True, exist_ok=True)
    if not is_repo(target, git_dir):
        if git_dir is not None:
            Path(git_dir).mkdir(parents=True, exist_ok=True)
            _git(target, "init", "-q", git_dir=git_dir)
        else:
            _git(target, "init", "-q")
    _git(target, "config", "user.name", _COMMITTER_NAME, git_dir=git_dir)
    _git(target, "config", "user.email", _COMMITTER_EMAIL, git_dir=git_dir)
    if _git(target, "rev-parse", "--verify", "HEAD", git_dir=git_dir, check=False).returncode != 0:
        _git(target, "commit", "--allow-empty", "-q", "-m", "notes: initialise", git_dir=git_dir)


def _subject(message: str) -> str:
    stripped = (message or "").strip()
    line = stripped.splitlines()[0][:72] if stripped else "agent turn"
    return f"notes: {line or 'agent turn'}"


def commit_all(notes_root: Path | str, message: str, git_dir: Path | str | None = None) -> str | None:
    """Stage everything and commit a one-line subject derived from ``message``.
    Returns the new commit sha, or ``None`` if the tree was clean or not a repo.

    When ``git_dir`` is given the metadata is read from/written to that directory
    (split git-dir/work-tree mode)."""
    root = Path(notes_root)
    if not is_repo(root, git_dir):
        return None
    _git(root, "add", "-A", git_dir=git_dir)
    if not _git(root, "status", "--porcelain", git_dir=git_dir).stdout.strip():
        return None
    _git(root, "commit", "-q", "-m", _subject(message), git_dir=git_dir)
    return _git(root, "rev-parse", "HEAD", git_dir=git_dir).stdout.strip()


def revert_last(notes_root: Path | str, git_dir: Path | str | None = None) -> str:
    """Undo the most recent commit via ``git revert``. Returns the revert commit's
    sha. Raises ``RuntimeError`` if the directory is not a repo, if only the
    initial commit exists, or if the revert itself fails (e.g. a conflict) —
    callers (``/api/undo``) handle ``RuntimeError`` and surface a clean 400, so
    git's ``CalledProcessError`` must not escape."""
    root = Path(notes_root)
    if not is_repo(root, git_dir):
        raise RuntimeError("nothing to undo")
    count = int(_git(root, "rev-list", "--count", "HEAD", git_dir=git_dir).stdout.strip())
    if count <= 1:
        raise RuntimeError("nothing to undo")
    try:
        _git(root, "revert", "--no-edit", "HEAD", git_dir=git_dir)
    except subprocess.CalledProcessError as exc:
        # Leave no half-applied revert behind, then report cleanly.
        _git(root, "revert", "--abort", git_dir=git_dir, check=False)
        raise RuntimeError(f"undo failed: git revert returned {exc.returncode}") from exc
    return _git(root, "rev-parse", "HEAD", git_dir=git_dir).stdout.strip()


