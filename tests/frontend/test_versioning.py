import subprocess
from pathlib import Path

import pytest

from frontend import versioning


def _count(root):
    return int(subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                              capture_output=True, text=True).stdout.strip())


def test_ensure_repo_inits_with_head_and_is_idempotent(tmp_path):
    versioning.ensure_repo(tmp_path)
    assert (tmp_path / ".git").is_dir()
    assert _count(tmp_path) == 1                      # initial commit exists
    versioning.ensure_repo(tmp_path)                  # idempotent
    assert _count(tmp_path) == 1
    cfg = subprocess.run(["git", "-C", str(tmp_path), "config", "user.email"],
                         capture_output=True, text=True).stdout.strip()
    assert cfg == "notes@localhost"                   # generic identity, not the user's


def test_commit_all_commits_changes_and_noops_when_clean(tmp_path):
    versioning.ensure_repo(tmp_path)
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "atlas.md").write_text("x", encoding="utf-8")
    sha = versioning.commit_all(tmp_path, "Process the inbox")
    assert sha and _count(tmp_path) == 2
    subj = subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
                          capture_output=True, text=True).stdout.strip()
    assert subj == "notes: Process the inbox"
    assert versioning.commit_all(tmp_path, "again") is None   # clean tree -> no-op
    assert _count(tmp_path) == 2


def test_revert_last_undoes_the_last_commit(tmp_path):
    versioning.ensure_repo(tmp_path)
    f = tmp_path / "note.md"
    f.write_text("hello", encoding="utf-8")
    versioning.commit_all(tmp_path, "add note")
    assert f.exists()
    versioning.revert_last(tmp_path)
    assert not f.exists()                             # revert removed the added file
    assert _count(tmp_path) == 3                      # revert is a new commit


# ── BH-23: Pattern I — revert_last() must not crash on non-repo ─────────────


def test_bh23_revert_last_raises_runtime_error_on_non_repo(tmp_path):
    """BH-23: revert_last() calls ``git rev-list --count HEAD`` without an
    ``is_repo()`` guard. On a non-repo directory, ``_git(...)`` raises
    ``subprocess.CalledProcessError`` (which is NOT a subclass of
    RuntimeError). Callers (``/api/undo``) only catch RuntimeError, so the
    CalledProcessError becomes a 500.

    revert_last() should check is_repo() first and raise RuntimeError with a
    clear message, like commit_all() does."""
    with pytest.raises(RuntimeError, match="not a git repository|undo failed|nothing to undo"):
        versioning.revert_last(tmp_path)


def test_revert_last_raises_when_nothing_to_undo(tmp_path):
    versioning.ensure_repo(tmp_path)                  # only the initial commit
    with pytest.raises(RuntimeError):
        versioning.revert_last(tmp_path)


def test_subject_truncates_and_defaults():
    assert versioning._subject("a" * 100).startswith("notes: ")
    assert len(versioning._subject("a" * 100)) <= len("notes: ") + 72
    assert versioning._subject("a" * 100) == "notes: " + "a" * 72
    assert versioning._subject("   ") == "notes: agent turn"
    assert versioning._subject("line1\nline2") == "notes: line1"


def test_commit_all_returns_none_on_non_repo(tmp_path):
    assert versioning.commit_all(tmp_path, "x") is None


def test_ensure_repo_refuses_app_source_tree():
    frontend_dir = Path(versioning.__file__).resolve().parent
    with pytest.raises(RuntimeError):
        versioning.ensure_repo(frontend_dir)


def test_split_gitdir_keeps_dotgit_out_of_worktree(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    gd = tmp_path / "notes.git"
    versioning.ensure_repo(work, git_dir=gd)
    assert gd.is_dir()                       # metadata lives outside the work-tree
    assert not (work / ".git").exists()      # nothing inside the sandbox
    (work / "tasks.todo.txt").write_text("(A) x +y upd:2026-05-30", encoding="utf-8")
    sha = versioning.commit_all(work, "ingest", git_dir=gd)
    assert sha
    files = subprocess.run(["git", f"--git-dir={gd}", f"--work-tree={work}",
                            "ls-tree", "-r", "--name-only", "HEAD"],
                           capture_output=True, text=True).stdout.split()
    assert files == ["tasks.todo.txt"]
    # clean tree → no-op commit returns None (split mode)
    assert versioning.commit_all(work, "again", git_dir=gd) is None


def test_split_gitdir_revert_last(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    gd = tmp_path / "notes.git"
    versioning.ensure_repo(work, git_dir=gd)
    (work / "tasks.todo.txt").write_text("(A) one upd:2026-05-30", encoding="utf-8")
    versioning.commit_all(work, "ingest one", git_dir=gd)

    def _log():
        out = subprocess.run(["git", f"--git-dir={gd}", f"--work-tree={work}",
                              "log", "--oneline"], capture_output=True, text=True).stdout
        return [ln for ln in out.splitlines() if ln.strip()]

    before = _log()
    sha = versioning.revert_last(work, git_dir=gd)
    assert sha
    after = _log()
    # revert adds a NEW commit (it does not rewrite history)
    assert len(after) == len(before) + 1
    # the working file is restored to its pre-commit (absent) state
    assert not (work / "tasks.todo.txt").exists()


def test_revert_last_wraps_git_failure_as_runtimeerror(tmp_path, monkeypatch):
    """A failing `git revert` (e.g. a conflict) must surface as RuntimeError, not a
    raw CalledProcessError — /api/undo only catches RuntimeError."""
    work = tmp_path / "workspace"
    work.mkdir()
    gd = tmp_path / "notes.git"
    versioning.ensure_repo(work, git_dir=gd)
    (work / "f.txt").write_text("x", encoding="utf-8")
    versioning.commit_all(work, "c1", git_dir=gd)

    real_git = versioning._git

    def fake_git(root, *args, git_dir=None, check=True):
        # Fail the actual revert; let the cleanup `revert --abort` and everything
        # else run for real.
        if args[:1] == ("revert",) and "--abort" not in args:
            raise subprocess.CalledProcessError(1, ["git", "revert", "--no-edit", "HEAD"])
        return real_git(root, *args, git_dir=git_dir, check=check)

    monkeypatch.setattr(versioning, "_git", fake_git)
    with pytest.raises(RuntimeError, match="undo failed"):
        versioning.revert_last(work, git_dir=gd)
