"""Per-worktree ``mr base`` storage, shared by ``mr`` and ``mr-diff``.

Storage is a single-line text file at ``<worktree-git-dir>/mr-base``
(e.g. ``.git/mr-base`` for the main worktree,
``.git/worktrees/<name>/mr-base`` for linked worktrees), so each
worktree resolves its own base with no GC or locking needed.
"""

from __future__ import annotations

from pathlib import Path

from utilities import git as gitops

BASE_FILENAME = "mr-base"


def base_file_path(cwd: Path) -> Path:
    return gitops.worktree_git_dir(cwd) / BASE_FILENAME


def get_base(cwd: Path) -> str:
    """Stored base for this worktree, or ``origin/<default-branch>`` if unset."""
    path = base_file_path(cwd)
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return gitops.default_remote_base(cwd)
    if not content:
        return gitops.default_remote_base(cwd)
    return content.splitlines()[0].strip()


def set_base(ref: str, cwd: Path, *, fetch: bool = True) -> str:
    """Validate (fetching if remote), persist, and return *ref*.

    Stores the ref verbatim (``main`` stays ``main``).
    Hard-fails if the ref does not resolve or the fetch fails.
    """
    gitops.ensure_fresh_base(ref, cwd, fetch=fetch)
    path = base_file_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ref.strip() + "\n", encoding="utf-8")
    return ref.strip()


def reset_base(cwd: Path, *, fetch: bool = False) -> str:
    """Reset this worktree's base to ``origin/<default-branch>`` and return it.

    Does not fetch by default (reset only computes the default name);
    pass ``fetch=True`` to refresh the remote ref as well.
    """
    ref = gitops.default_remote_base(cwd)
    if fetch:
        gitops.ensure_fresh_base(ref, cwd, fetch=True)
    path = base_file_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ref + "\n", encoding="utf-8")
    return ref


def set_base_after_create(ref: str, cwd: Path) -> str:
    """Record the creation base after ``mr new`` without re-validating.

    ``mr new`` already validated/fetched, so this is a plain write.
    """
    path = base_file_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ref.strip() + "\n", encoding="utf-8")
    return ref.strip()
