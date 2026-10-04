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


def list_local_branches(cwd: Path) -> list[str]:
    """Sorted local branch short names, or [] when git fails (e.g. no repo).

    Used for shell completion of base-ish positions (never raises).
    """
    result = run_git(["branch", "--format=%(refname:short)"], cwd, check=False)
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def list_remote_branches(cwd: Path) -> list[str]:
    """Sorted remote-tracking branches (e.g. ``origin/main``), or [] on failure.

    ``origin/HEAD -> origin/main`` symref lines are filtered out.
    Used for shell completion of base-ish positions (never raises).
    """
    result = run_git(["branch", "-r", "--format=%(refname:short)"], cwd, check=False)
    if result.returncode != 0:
        return []
    names: set[str] = set()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or " -> " in stripped:
            continue
        names.add(stripped)
    return sorted(names)


def list_completion_refs(cwd: Path) -> list[str]:
    """Sorted local + remote-tracking refs for base completion (never raises)."""
    return sorted(set(list_local_branches(cwd)) | set(list_remote_branches(cwd)))


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
    """Captured ``git diff --name-status <mb>`` (staged+unstaged+committed vs mb).

    Rename detection is forced on so ``R`` rows appear regardless of the
    user's ``diff.renames`` config.
    """
    result = run_git(["diff", "--find-renames", "--name-status", merge_base_sha], cwd)
    return result.stdout


def diff_name_only(merge_base_sha: str, cwd: Path) -> str:
    """Captured ``git diff --name-only <mb>`` (paths only, renames detected)."""
    result = run_git(["diff", "--find-renames", "--name-only", merge_base_sha], cwd)
    return result.stdout


def list_untracked(cwd: Path) -> list[str]:
    """Repo-relative paths of untracked, non-ignored files (``git ls-files``)."""
    result = run_git(["ls-files", "--others", "--exclude-standard"], cwd)
    return [line for line in (line.strip() for line in result.stdout.splitlines()) if line]


def is_untracked(path: str, cwd: Path) -> bool:
    """True when *path* matches an untracked, non-ignored file."""
    result = run_git(["ls-files", "--others", "--exclude-standard", "--", path], cwd, check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def exec_diff_patch(merge_base_sha: str, cwd: Path, path: str | None = None) -> int:
    """Inheriting ``git diff <mb> [-- path]`` so pager/color behave like git.

    Returns the git exit code.
    """
    args: list[str] = ["diff", "--find-renames", merge_base_sha]
    if path is not None:
        args += ["--", path]
    result = run_git(args, cwd, check=False, capture=False)
    return result.returncode


def exec_untracked_patch(path: str, cwd: Path) -> int:
    """Inheriting full-add patch for an untracked file via ``--no-index``.

    Shows ``/dev/null`` -> *path* so pager/color behave like git.
    ``git diff --no-index`` exits 1 when differences exist, which is the
    success case here, so 0 and 1 both map to 0.
    """
    result = run_git(
        ["diff", "--no-index", "--", "/dev/null", path], cwd, check=False, capture=False
    )
    return 0 if result.returncode in (0, 1) else result.returncode


def exec_rebase(base: str, cwd: Path) -> int:
    """Inheriting ``git rebase <base>`` so conflicts/editors behave like git.

    Returns the git exit code.
    """
    result = run_git(["rebase", base], cwd, check=False, capture=False)
    return result.returncode


def exec_rebase_onto(new_base: str, old_base: str, cwd: Path) -> int:
    """Inheriting ``git rebase --onto <new> <old>`` (retarget, squash-safe).

    Replays only ``<old>..HEAD`` onto ``<new>`` so commits already
    squashed into ``<new>`` via the old base are not replayed.
    Returns the git exit code.
    """
    result = run_git(["rebase", "--onto", new_base, old_base], cwd, check=False, capture=False)
    return result.returncode


def exec_rebase_continue(cwd: Path) -> int:
    """Inheriting ``git rebase --continue`` so conflicts/editors behave like git."""
    result = run_git(["rebase", "--continue"], cwd, check=False, capture=False)
    return result.returncode


def exec_rebase_skip(cwd: Path) -> int:
    """Inheriting ``git rebase --skip`` so output behaves like git."""
    result = run_git(["rebase", "--skip"], cwd, check=False, capture=False)
    return result.returncode


def exec_rebase_abort(cwd: Path) -> int:
    """Inheriting ``git rebase --abort`` so output behaves like git."""
    result = run_git(["rebase", "--abort"], cwd, check=False, capture=False)
    return result.returncode


def fetch_remote(remote: str, branch: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git fetch <remote> <branch>`` (narrow, best-effort or blocking)."""
    return run_git(["fetch", remote, branch], cwd, check=False)


def is_clean(cwd: Path) -> bool:
    """True when there are no staged or unstaged changes (untracked ignored)."""
    unstaged = run_git(["diff", "--quiet"], cwd, check=False)
    if unstaged.returncode != 0:
        return False
    staged = run_git(["diff", "--cached", "--quiet"], cwd, check=False)
    return staged.returncode == 0


def operation_in_progress(cwd: Path) -> str | None:
    """Describe an in-progress operation in *cwd*, or None when idle.

    Checks worktree-private state files (MERGE_HEAD, rebase dirs,
    CHERRY_PICK_HEAD, REVERT_HEAD, BISECT_LOG).
    """
    try:
        gd = git_dir(cwd)
    except GitError:
        return None
    checks = (
        ("MERGE_HEAD", "merge"),
        ("REBASE_MERGE", "rebase"),
        ("REBASE_APPLY", "rebase"),
        ("rebase-merge", "rebase"),
        ("rebase-apply", "rebase"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
        ("BISECT_LOG", "bisect"),
    )
    for filename, label in checks:
        try:
            if (gd / filename).exists():
                return label
        except OSError:
            continue
    return None


def worktree_branches(cwd: Path) -> dict[str, Path]:
    """Map local branch short name -> worktree path for all linked worktrees.

    Parses ``git worktree list --porcelain``. Detached, bare, or corrupted
    entries are skipped.
    """
    result = run_git(["worktree", "list", "--porcelain"], cwd, check=False)
    if result.returncode != 0:
        raise GitError("cannot list worktrees")
    mapping: dict[str, Path] = {}
    current_wt: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            try:
                current_wt = Path(line[len("worktree ") :].strip()).resolve()
            except OSError:
                current_wt = None
        elif line.startswith("branch refs/heads/"):
            if current_wt is not None:
                branch = line[len("branch refs/heads/") :].strip()
                if branch:
                    mapping[branch] = current_wt
        elif line == "bare" or line == "detached":
            # A following "branch ..." line never occurs for these, but if
            # the entry was bare/detached, drop any pending association.
            # Handled implicitly: detached entries emit no branch line.
            continue
    return mapping


def find_worktree_for_branch(branch: str, cwd: Path) -> Path | None:
    """Worktree path owning *branch*, or None when not checked out anywhere."""
    try:
        return worktree_branches(cwd).get(branch)
    except GitError:
        return None


def rev_parse(ref: str, cwd: Path) -> str:
    """Full SHA for *ref*; raise GitError if it does not resolve."""
    result = run_git(["rev-parse", "--verify", ref], cwd, check=False)
    if result.returncode != 0:
        raise GitError(f"ref '{ref}' does not resolve")
    return result.stdout.strip()


def rev_list_count(rev_range: str, cwd: Path) -> int:
    """Number of commits in *rev_range* (e.g. ``main..HEAD``)."""
    result = run_git(["rev-list", "--count", rev_range], cwd, check=False)
    if result.returncode != 0:
        raise GitError(f"cannot count commits in '{rev_range}'")
    try:
        return int(result.stdout.strip())
    except ValueError:
        raise GitError(f"cannot count commits in '{rev_range}'")


def commit_subjects(rev_range: str, cwd: Path) -> list[str]:
    """Commit subjects (oldest first) in *rev_range*."""
    result = run_git(["log", "--format=%s", "--reverse", rev_range], cwd, check=False)
    if result.returncode != 0:
        raise GitError(f"cannot list commits in '{rev_range}'")
    return [line for line in (line.strip() for line in result.stdout.splitlines()) if line]


def merge_ff_only(ref: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git merge --ff-only <ref>``."""
    return run_git(["merge", "--ff-only", ref], cwd, check=False)


def merge_squash(branch: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git merge --squash <branch>``."""
    return run_git(["merge", "--squash", branch], cwd, check=False)


def merge_no_ff(branch: str, message: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git merge --no-ff <branch> -m <message>``."""
    return run_git(["merge", "--no-ff", branch, "-m", message], cwd, check=False)


def commit(message: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git commit -m <message>``."""
    return run_git(["commit", "-m", message], cwd, check=False)


def reset_to(ref: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git reset <ref>`` (mixed; moves pointer, keeps worktree)."""
    return run_git(["reset", ref], cwd, check=False)


def exec_reset(mode: str, ref: str, cwd: Path) -> int:
    """Inheriting ``git reset --<mode> <ref>`` so output behaves like git.

    *mode* must be one of ``soft``, ``mixed``, or ``hard``.
    Returns the git exit code.
    """
    result = run_git(["reset", f"--{mode}", ref], cwd, check=False, capture=False)
    return result.returncode


def push(remote: str, branch: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git push <remote> <branch>``."""
    return run_git(["push", remote, branch], cwd, check=False)


def upstream_ref(cwd: Path) -> str | None:
    """Upstream of HEAD (e.g. ``origin/feature``), or None when unset."""
    result = run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd,
        check=False,
    )
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def push_set_upstream(remote: str, branch: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured ``git push -u <remote> <branch>`` (first publish)."""
    return run_git(["push", "-u", remote, branch], cwd, check=False)


def push_current(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Captured plain ``git push`` (upstream already set)."""
    return run_git(["push"], cwd, check=False)
