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
import os
from pathlib import Path

from frontend.config import CANONICAL_PROMPT_PATH, PROVIDER_ID, build_opencode_config

# Canonical system prompt ships inside the installable ``frontend`` package.
_CANONICAL_PROMPT = CANONICAL_PROMPT_PATH


def _open_private(path, flags):
    """``open()`` opener that creates the file with mode 0600 from the start.

    Passing this as ``open(..., opener=_open_private)`` means the secret is
    written into a file that is owner-only from creation — no world-readable
    window between ``write`` and a follow-up ``chmod`` (and no lingering 0644
    file if a later ``chmod`` were to fail).
    """
    return os.open(path, flags, 0o600)


def _write_auth_json(oc_home: Path, api_key: str) -> Path:
    """Store *api_key* in OpenCode's native credential file, mode 600.

    OpenCode reads credentials from ``$XDG_DATA_HOME/opencode/auth.json`` keyed
    by provider id (see opencode auth/index.ts). The launcher points
    ``XDG_DATA_HOME`` at ``<install-root>/oc-home/.local/share`` (launcher.run),
    so that is where this file must live for OpenCode to find it. The format and
    0600 permission mirror what ``opencode auth login`` writes itself.

    Note: ``chmod(0o600)`` only sets POSIX owner-private bits on POSIX systems;
    on Windows it merely toggles the read-only attribute, so the owner-private
    guarantee holds on POSIX only (the launcher/opencode stack is POSIX-oriented).
    """
    auth_path = oc_home / ".local" / "share" / "opencode" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    # Merge into any existing credentials rather than clobbering them.
    existing: dict = {}
    if auth_path.exists():
        try:
            loaded = json.loads(auth_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError):
            existing = {}
    # Match opencode's own key normalization (auth.set strips trailing slashes);
    # PROVIDER_ID has none today, but normalize so a future change can't make the
    # written key diverge from opencode's read path.
    key = PROVIDER_ID.rstrip("/")
    existing[key] = {"type": "api", "key": api_key}
    # Create owner-private (0600) up front rather than write-then-chmod, so the
    # secret never lands in a world-readable file even briefly.
    with open(auth_path, "w", encoding="utf-8", opener=_open_private) as fh:
        fh.write(json.dumps(existing, indent=2) + "\n")
    # Existing files keep their inode/mode through "w" truncation; re-assert 600.
    auth_path.chmod(0o600)
    return auth_path


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
    python_executable: str,
    api_key: str | None = None,
    mcp_pythonpath: str | None = None,
    restrict_write: bool = False,
    model_options: dict | None = None,
) -> dict:
    """Create (or verify) the Chief-of-Staff Notes install layout.

    Args:
        install_root: Target directory for the install (will be created).
        model_endpoint: Base URL of the OpenAI-compatible inference server.
        model_id: Model identifier string.
        python_executable: Absolute path to the venv Python that has agenda/
            presenter installed; both MCP servers are spawned as
            ``<python> -m <module>`` (see ``frontend.config``).
        api_key: Bearer token for an authenticated endpoint, or ``None`` for a
            local/keyless server. When set, it is stored in OpenCode's native
            auth.json under oc-home (mode 600) and deliberately OMITTED from
            opencode.json — an inline ``options.apiKey`` would shadow the
            auth.json credential (see ``frontend.config.build_opencode_config``).
        mcp_pythonpath: Target/venv-less mode only — absolute ``.pysite`` path
            baked as ``PYTHONPATH`` into the generated MCP server environments so
            OpenCode's ``python -m`` MCP children are self-sufficient. ``None``
            (venv mode) leaves the config untouched.
        model_options: Optional provider options (e.g. ``{"temperature": 0}``) to
            pin known-good defaults for a weak local backbone, forwarded to
            ``build_opencode_config``. The wizard parses these from the
            ``MODEL_OPTIONS`` env via ``frontend.config.parse_model_options``;
            ``baseURL``/``apiKey`` in it are neutralized by the builder.

    Returns:
        A dict with keys ``install_root``, ``workspace``, ``git_dir``,
        ``opencode_json``, and ``auth_json`` (``None`` for keyless installs,
        else the ``Path`` to the written auth.json).

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
    config = build_opencode_config(
        model_endpoint=model_endpoint,
        model_id=model_id,
        notes_root=str(work),
        python_executable=python_executable,
        prompt_path=str(prompt_dest),
        api_key=api_key,
        mcp_pythonpath=mcp_pythonpath,
        restrict_write=restrict_write,
        model_options=model_options,
    )
    opencode_json = root / "opencode.json"
    opencode_json.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Store the API key (if any) in OpenCode's native auth.json under oc-home.
    # opencode.json deliberately omits options.apiKey for authenticated
    # endpoints, so the key here is what OpenCode actually uses.
    # ------------------------------------------------------------------
    auth_json = _write_auth_json(oc_home, api_key) if api_key else None

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
        "auth_json": auth_json,
    }
