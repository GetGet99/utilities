"""Thin git subprocess wrapper. All git I/O goes through here."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command fails and the caller wants an exception."""


def run_git(
    args: Sequence[str],
    cwd: Path,
    *,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in *cwd*.

    When *capture* is True, stdout/stderr are captured as text; otherwise
    they are inherited (used for pager/color-sensitive ``git diff``).
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (exit {result.returncode})"
            + (f": {(result.stderr or '').strip()}" if capture and result.stderr else "")
        )
    return result


def repo_root(cwd: Path) -> Path:
    """Absolute path of the worktree root (per-worktree, not common dir)."""
    result = run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(result.stdout.strip()).resolve()


def _abs_git_path(raw: str, cwd: Path) -> Path:
    p = Path(raw.strip())
    if not p.is_absolute():
        p = cwd.resolve() / p
    return (
        p.resolve()
        if p.exists()
        else Path(raw.strip())
        if Path(raw.strip()).is_absolute()
        else (cwd.resolve() / p)
    )


def git_dir(cwd: Path) -> Path:
    """Per-worktree git dir (``.git`` for main, ``.git/worktrees/<name>`` for linked)."""
    result = run_git(["rev-parse", "--git-dir"], cwd)
    return _abs_git_path(result.stdout, cwd)


def git_common_dir(cwd: Path) -> Path:
    """Shared ``.git`` dir across all worktrees of this repository."""
    result = run_git(["rev-parse", "--git-common-dir"], cwd)
    return _abs_git_path(result.stdout, cwd)


def worktree_git_dir(cwd: Path) -> Path:
    """Alias for :func:`git_dir` — the per-worktree dir used for ``mr-base`` storage."""
    return git_dir(cwd)


def list_remotes(cwd: Path) -> list[str]:
    result = run_git(["remote"], cwd)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def default_branch(cwd: Path) -> str:
    """Short name of the default branch (e.g. ``main``), resolved via origin/HEAD.

    Falls back to ``main`` then ``master`` if ``origin/HEAD`` is not set.
    """
    probe = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd, check=False)
    if probe.returncode == 0:
        ref = probe.stdout.strip()  # e.g. refs/remotes/origin/main
        prefix = "refs/remotes/origin/"
        if ref.startswith(prefix) and len(ref) > len(prefix):
            return ref[len(prefix) :]
    for candidate in ("main", "master"):
        check = run_git(
            ["show-ref", "--verify", f"refs/remotes/origin/{candidate}"],
            cwd,
            check=False,
        )
        if check.returncode == 0:
            return candidate
    raise GitError("cannot determine default branch: no origin/HEAD and no origin/main|master")


def default_remote_base(cwd: Path) -> str:
    """E.g. ``origin/main`` for the current repository."""
    return f"origin/{default_branch(cwd)}"


def parse_remote_ref(ref: str, cwd: Path) -> tuple[str, str] | None:
    """Split ``origin/main`` -> ``(origin, main)`` iff ``origin`` is a known remote.

    Returns None for local branches, SHAs, and slash-containing branch names
    whose first component is NOT a remote (e.g. ``feat/my-new-feature``).
    Splits on the FIRST ``/`` only, so ``origin/feature/foo`` keeps ``feature/foo``.
    """
    if "/" not in ref:
        return None
    remote, _, branch = ref.partition("/")
    if not remote or not branch:
        return None
    if remote not in list_remotes(cwd):
        return None
    return (remote, branch)


def resolve_to_commit(ref: str, cwd: Path) -> str:
    """Return full commit SHA for *ref*; raise GitError if it does not resolve."""
    result = run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd, check=False)
    if result.returncode != 0:
        raise GitError(f"base '{ref}' does not resolve to a commit")
    return result.stdout.strip()


def ensure_fresh_base(ref: str, cwd: Path, *, fetch: bool = True) -> str:
    """Fetch remote base if needed, then return its commit SHA.

    - If *ref* parses as ``<remote>/<branch>`` and *fetch* is True, runs
      ``git fetch <remote> <branch>`` first. Fetch failure HARD-FAILS.
    - Then validates via :func:`resolve_to_commit` (also hard-fails).
    """
    parsed = parse_remote_ref(ref, cwd)
    if parsed is not None and fetch:
        remote, branch = parsed
        fetched = run_git(["fetch", remote, branch], cwd, check=False)
        if fetched.returncode != 0:
            detail = (fetched.stderr or "").strip() if fetched.stderr else ""
            raise GitError(
                f"failed to fetch '{ref}': {detail or 'exit ' + str(fetched.returncode)}"
            )
    return resolve_to_commit(ref, cwd)


def branch_exists(name: str, cwd: Path) -> bool:
    result = run_git(["show-ref", "--verify", f"refs/heads/{name}"], cwd, check=False)
    return result.returncode == 0


def merge_base(base: str, cwd: Path) -> str:
    """Full SHA of ``git merge-base <base> HEAD``."""
    result = run_git(["merge-base", base, "HEAD"], cwd, check=False)
    if result.returncode != 0:
        raise GitError(f"cannot compute merge-base of '{base}' and HEAD")
    return result.stdout.strip()


def current_branch(cwd: Path) -> str | None:
    result = run_git(["branch", "--show-current"], cwd, check=False)
    name = result.stdout.strip()
    return name or None


def diff_name_status(merge_base_sha: str, cwd: Path) -> str:
    """Captured ``git diff --name-status <mb>`` (staged+unstaged+committed vs mb)."""
    result = run_git(["diff", "--name-status", merge_base_sha], cwd)
    return result.stdout


def exec_diff_patch(merge_base_sha: str, cwd: Path, path: str | None = None) -> int:
    """Inheriting ``git diff <mb> [-- path]`` so pager/color behave like git.

    Returns the git exit code.
    """
    args: list[str] = ["diff", merge_base_sha]
    if path is not None:
        args += ["--", path]
    result = run_git(args, cwd, check=False, capture=False)
    return result.returncode


def exec_rebase(base: str, cwd: Path) -> int:
    """Inheriting ``git rebase <base>`` so conflicts/editors behave like git.

    Returns the git exit code.
    """
    result = run_git(["rebase", base], cwd, check=False, capture=False)
    return result.returncode
