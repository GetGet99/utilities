"""Per-worktree ``mr base`` storage, shared by ``mr`` and ``mr-diff``.

Worktree base is a single-line text file at ``<worktree-git-dir>/mr-base``
(e.g. ``.git/mr-base`` for the main worktree,
``.git/worktrees/<name>/mr-base`` for linked worktrees), so each
worktree resolves its own base with no GC or locking needed.

Repo-level custom default lives at ``<common-git-dir>/mr-default`` so all
worktrees share it. When set, it replaces ``origin/<default-branch>`` as
the fallback for :func:`get_base` and :func:`reset_base`.
"""

from __future__ import annotations

from pathlib import Path

from utilities import git as gitops

BASE_FILENAME = "mr-base"
DEFAULT_FILENAME = "mr-default"
PENDING_FILENAME = "mr-rebase-onto"


def pending_file_path(cwd: Path) -> Path:
    return gitops.worktree_git_dir(cwd) / PENDING_FILENAME


def get_pending_rebase_onto(cwd: Path) -> str | None:
    """Pending ``--onto`` target for this worktree, or None when idle.

    Set by ``mr rebase --onto`` before rebasing; cleared on
    ``--continue`` success, ``--abort``, or explicit ``base set/reset``.
    """
    try:
        path = pending_file_path(cwd)
    except gitops.GitError:
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not content:
        return None
    return content.splitlines()[0].strip() or None


def set_pending_rebase_onto(ref: str, cwd: Path) -> str:
    """Record a pending ``--onto`` target (plain write, already validated)."""
    path = pending_file_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ref.strip() + "\n", encoding="utf-8")
    return ref.strip()


def clear_pending_rebase_onto(cwd: Path) -> None:
    """Drop any pending ``--onto`` target (best-effort, never raises)."""
    try:
        path = pending_file_path(cwd)
    except gitops.GitError:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def base_file_path(cwd: Path) -> Path:
    return gitops.worktree_git_dir(cwd) / BASE_FILENAME


def default_file_path(cwd: Path) -> Path:
    return gitops.git_common_dir(cwd) / DEFAULT_FILENAME


def get_custom_default(cwd: Path) -> str | None:
    """Repo-level custom default, or None if unset (shared by all worktrees)."""
    path = default_file_path(cwd)
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not content:
        return None
    return content.splitlines()[0].strip()


def get_effective_default(cwd: Path) -> str:
    """Custom repo default if set, else ``origin/<default-branch>``."""
    custom = get_custom_default(cwd)
    if custom is not None:
        return custom
    return gitops.default_remote_base(cwd)


def set_custom_default(ref: str, cwd: Path, *, fetch: bool = True) -> str:
    """Validate (fetching if remote), persist repo-wide, and return *ref*.

    Stored at ``<common-git-dir>/mr-default`` so all worktrees share it.
    Hard-fails if the ref does not resolve or the fetch fails.
    """
    gitops.ensure_fresh_base(ref, cwd, fetch=fetch)
    path = default_file_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ref.strip() + "\n", encoding="utf-8")
    return ref.strip()


def reset_custom_default(cwd: Path) -> str:
    """Drop the repo-level custom default, returning ``origin/<default-branch>``."""
    ref = gitops.default_remote_base(cwd)
    path = default_file_path(cwd)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return ref


def get_base(cwd: Path) -> str:
    """Stored base for this worktree, or the effective default if unset."""
    path = base_file_path(cwd)
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return get_effective_default(cwd)
    if not content:
        return get_effective_default(cwd)
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
    """Reset this worktree's base to the effective default and return it.

    Uses the repo-level custom default when set, else
    ``origin/<default-branch>``. Does not fetch by default (reset only
    computes the default name); pass ``fetch=True`` to refresh the
    remote ref as well.
    """
    ref = get_effective_default(cwd)
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
