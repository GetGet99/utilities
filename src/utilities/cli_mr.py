"""``mr`` CLI: easy branch creation + per-worktree base pointer."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from utilities import base_store, config_store
from utilities import git as gitops
from utilities import glab as glabops
from utilities.completion import (
    completion_status,
    detect_shell,
    handle_print_completion,
    install_completion,
    uninstall_completion,
)


def _cwd() -> Path:
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mr", description="Branch + base-branch helper")
    parser.add_argument(
        "--print-completion",
        choices=["bash", "zsh"],
        default=None,
        help="Print shell completion script and exit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="Create a new branch from a base and switch to it")
    p_new.add_argument("branch", help="New branch name to create")
    p_new.add_argument(
        "base",
        nargs="?",
        default=None,
        help="Base ref (default: effective default). Accepts local or origin/<branch>.",
    )
    p_new.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching when base is a remote branch (default: fetch).",
    )

    p_base = sub.add_parser("base", help="Print or change this worktree's base branch")
    base_sub = p_base.add_subparsers(dest="base_command", required=False)
    p_set = base_sub.add_parser("set", help="Change this worktree's base branch")
    p_set.add_argument("base", help="New base ref (e.g. main or origin/main)")
    p_set.add_argument("--no-fetch", action="store_true", help="Skip fetching remote base.")
    base_sub.add_parser("reset", help="Reset base to the effective default")
    p_default = base_sub.add_parser("default", help="Print or change the repo-level default branch")
    default_sub = p_default.add_subparsers(dest="default_command", required=False)
    p_dset = default_sub.add_parser("set", help="Change the repo-level default branch")
    p_dset.add_argument("ref", help="New default ref (e.g. main or origin/main)")
    p_dset.add_argument("--no-fetch", action="store_true", help="Skip fetching remote default.")
    default_sub.add_parser("reset", help="Reset repo default to origin/<default-branch>")

    p_rebase = sub.add_parser("rebase", help="Rebase the current branch onto this worktree's base")
    onto_group = p_rebase.add_mutually_exclusive_group()
    onto_group.add_argument(
        "--onto",
        metavar="NEW_BASE",
        default=None,
        help="Retarget onto NEW_BASE replaying only old-base..HEAD (squash-safe).",
    )
    onto_group.add_argument(
        "--continue",
        dest="continue_op",
        action="store_true",
        help="Continue an in-progress rebase (applies pending --onto base when done).",
    )
    onto_group.add_argument(
        "--skip",
        dest="skip_op",
        action="store_true",
        help="Skip the current patch and continue the rebase.",
    )
    onto_group.add_argument(
        "--abort",
        dest="abort_op",
        action="store_true",
        help="Abort the in-progress rebase and drop any pending --onto base.",
    )
    p_rebase.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching when base is a remote branch (default: fetch).",
    )

    p_reset = sub.add_parser("reset", help="Reset the current branch to this worktree's base")
    reset_mode = p_reset.add_mutually_exclusive_group()
    reset_mode.add_argument(
        "--soft",
        dest="soft",
        action="store_true",
        default=False,
        help="Keep index and working tree (git reset --soft).",
    )
    reset_mode.add_argument(
        "--mixed",
        dest="mixed",
        action="store_true",
        default=False,
        help="Keep working tree, reset index (default; git reset --mixed).",
    )
    reset_mode.add_argument(
        "--hard",
        dest="hard",
        action="store_true",
        default=False,
        help="Discard index and working-tree changes (git reset --hard).",
    )
    p_reset.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching when base is a remote branch (default: fetch).",
    )

    p_squash = sub.add_parser("squash", help="Squash this branch's commits into a single commit")
    p_squash.add_argument(
        "-m",
        "--message",
        default=None,
        help="Squashed commit message (default: ask when interactive, else message of HEAD).",
    )
    p_squash.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching when base is a remote branch (default: fetch).",
    )

    p_merge = sub.add_parser(
        "merge",
        help="Rebase onto this worktree's base, then merge into the base worktree",
    )
    p_merge.add_argument(
        "-m",
        "--message",
        default=None,
        help="Squash/merge commit message (default: ask when squashing, else branch subjects).",
    )
    strategy = p_merge.add_mutually_exclusive_group()
    strategy.add_argument(
        "--squash",
        dest="squash",
        action="store_true",
        default=None,
        help="Squash all branch commits into one commit on the base (default).",
    )
    strategy.add_argument(
        "--no-ff",
        dest="no_ff",
        action="store_true",
        default=None,
        help="Regular merge commit preserving branch history.",
    )
    push = p_merge.add_mutually_exclusive_group()
    push.add_argument(
        "--push",
        dest="push",
        action="store_true",
        default=None,
        help="Push the base after merging.",
    )
    push.add_argument(
        "--no-push",
        dest="no_push",
        action="store_true",
        default=None,
        help="Never push the base after merging.",
    )
    p_merge.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching when base is a remote branch (default: fetch).",
    )

    p_publish = sub.add_parser(
        "publish",
        help="Push the current branch and open a GitLab merge request via glab",
    )
    p_publish.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching when base is a remote branch (default: fetch).",
    )
    p_publish.add_argument(
        "--no-push",
        dest="no_push",
        action="store_true",
        default=False,
        help="Skip pushing; assume the branch is already on the remote.",
    )
    p_publish.add_argument(
        "--fill",
        action="store_true",
        help="Fill MR title/description from commits (passed to glab).",
    )
    p_publish.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip submission confirmation prompt (passed to glab).",
    )
    p_publish.add_argument(
        "--draft",
        action="store_true",
        help="Mark merge request as a draft (passed to glab).",
    )
    p_publish.add_argument(
        "-t",
        "--title",
        default=None,
        help="MR title (passed to glab).",
    )
    p_publish.add_argument(
        "-d",
        "--description",
        default=None,
        help="MR description (passed to glab).",
    )
    p_publish.add_argument(
        "-l",
        "--label",
        dest="labels",
        action="append",
        default=None,
        help="Add label (repeatable, passed to glab).",
    )
    p_publish.add_argument(
        "-a",
        "--assignee",
        dest="assignees",
        action="append",
        default=None,
        help="Assign user (repeatable, passed to glab).",
    )
    p_publish.add_argument(
        "--reviewer",
        dest="reviewers",
        action="append",
        default=None,
        help="Request review from user (repeatable, passed to glab).",
    )
    p_publish.add_argument(
        "--remove-source-branch",
        action="store_true",
        help="Remove source branch on merge (passed to glab).",
    )
    p_publish.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="Extra args forwarded verbatim to 'glab mr create' after '--'.",
    )

    p_config = sub.add_parser("config", help="Print or change global mr behavior defaults")
    config_sub = p_config.add_subparsers(dest="config_command", required=False)
    config_sub.add_parser("list", help="List global config values")
    p_cset = config_sub.add_parser("set", help="Change a global config value")
    p_cset.add_argument("key", help="Config key (merge.strategy or merge.push)")
    p_cset.add_argument("value", help="Config value")
    p_creset = config_sub.add_parser("reset", help="Drop global config value(s)")
    p_creset.add_argument(
        "key",
        nargs="?",
        default=None,
        help="Config key to drop (default: drop all global config).",
    )

    p_completion = sub.add_parser("completion", help="Install or remove shell completion")
    comp_sub = p_completion.add_subparsers(dest="completion_command", required=False)
    p_cinstall = comp_sub.add_parser(
        "install",
        help="Append mr + mr-diff completion to your shell rc file",
    )
    p_cinstall.add_argument(
        "--shell",
        dest="shells",
        action="append",
        choices=["bash", "zsh"],
        default=None,
        help="Shell to configure (repeatable; default: current $SHELL).",
    )
    p_cinstall.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    p_cuninstall = comp_sub.add_parser(
        "uninstall", help="Remove the managed completion block again"
    )
    p_cuninstall.add_argument(
        "--shell",
        dest="shells",
        action="append",
        choices=["bash", "zsh"],
        default=None,
        help="Shell to clean (repeatable; default: current $SHELL).",
    )
    comp_sub.add_parser("status", help="Show completion install state per shell")
    return parser


def cmd_new(branch: str, base: str | None, *, fetch: bool) -> int:
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    if gitops.branch_exists(branch, cwd):
        print(f"error: branch '{branch}' already exists", file=sys.stderr)
        return 2
    try:
        resolved_base = base if base is not None else base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        gitops.ensure_fresh_base(resolved_base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = gitops.run_git(
        ["checkout", "--no-track", "-b", branch, resolved_base], cwd, check=False
    )
    if result.returncode != 0:
        # Let git's own message (e.g. "would be overwritten by checkout") go to stderr.
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return result.returncode
    base_store.set_base_after_create(resolved_base, cwd)
    base_store.clear_pending_rebase_onto(cwd)
    print(f"Switched to a new branch '{branch}' from '{resolved_base}'")
    return 0


def cmd_base_print() -> int:
    cwd = _cwd()
    try:
        print(base_store.get_base(cwd))
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_base_set(ref: str, *, fetch: bool) -> int:
    cwd = _cwd()
    try:
        stored = base_store.set_base(ref, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    base_store.clear_pending_rebase_onto(cwd)
    print(f"base set to '{stored}'")
    return 0


def cmd_base_reset() -> int:
    cwd = _cwd()
    try:
        ref = base_store.reset_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    base_store.clear_pending_rebase_onto(cwd)
    print(f"base reset to '{ref}'")
    return 0


def cmd_base_default_print() -> int:
    cwd = _cwd()
    try:
        print(base_store.get_effective_default(cwd))
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_base_default_set(ref: str, *, fetch: bool) -> int:
    cwd = _cwd()
    try:
        stored = base_store.set_custom_default(ref, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"default set to '{stored}'")
    return 0


def cmd_base_default_reset() -> int:
    cwd = _cwd()
    try:
        ref = base_store.reset_custom_default(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"default reset to '{ref}'")
    return 0


def cmd_rebase(*, fetch: bool) -> int:
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    try:
        base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    pending = base_store.get_pending_rebase_onto(cwd)
    if pending is not None:
        print(
            f"warning: stale --onto intent for '{pending}' exists "
            "(finished with git directly?) — base unchanged; "
            f"run 'mr base set {pending}' to adopt or 'mr rebase --abort' to drop it",
            file=sys.stderr,
        )
    try:
        gitops.ensure_fresh_base(base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Inherit stdio so conflicts/editors behave like plain `git rebase`.
    return gitops.exec_rebase(base, cwd)


def cmd_rebase_onto(new_base: str, *, fetch: bool) -> int:
    """Retarget the current branch onto *new_base*, replaying old-base..HEAD.

    Uses ``git rebase --onto <new> <old>`` so commits already squashed
    into the new base via the old base are not replayed. The mr-base
    pointer switches only after the rebase completes; conflicts leave the
    old base in place and stash the intent for ``mr rebase --continue``.
    """
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    current = gitops.current_branch(cwd)
    if current is None:
        print("error: detached HEAD — checkout a branch first", file=sys.stderr)
        return 2
    op = gitops.operation_in_progress(cwd)
    if op is not None:
        print(f"error: '{current}' worktree is mid-{op} — resolve it first", file=sys.stderr)
        return 2
    if not gitops.is_clean(cwd):
        print("error: working tree has uncommitted changes", file=sys.stderr)
        return 2
    try:
        old_base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parsed_new = gitops.parse_remote_ref(new_base, cwd)
    local_new = parsed_new[1] if parsed_new is not None else new_base
    if current == local_new:
        print(
            f"error: already on base branch '{current}' — there is nothing to transplant",
            file=sys.stderr,
        )
        return 2

    try:
        gitops.ensure_fresh_base(new_base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if fetch:
        parsed_old = gitops.parse_remote_ref(old_base, cwd)
        if parsed_old is not None:
            remote, branch = parsed_old
            fetched = gitops.fetch_remote(remote, branch, cwd)
            if fetched.returncode != 0:
                detail = (fetched.stderr or "").strip() if fetched.stderr else ""
                print(
                    f"warning: failed to fetch old base '{old_base}': "
                    f"{detail or 'exit ' + str(fetched.returncode)} — continuing",
                    file=sys.stderr,
                )
    try:
        gitops.resolve_to_commit(old_base, cwd)
    except gitops.GitError:
        print(f"error: base '{old_base}' does not resolve to a commit", file=sys.stderr)
        return 2
    try:
        to_replay = gitops.rev_list_count(f"{old_base}..HEAD", cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if to_replay == 0:
        try:
            stored = base_store.set_base(new_base, cwd, fetch=False)
        except gitops.GitError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        base_store.clear_pending_rebase_onto(cwd)
        print(f"Nothing to replay — '{current}' has no commits beyond {old_base}.")
        print(f"base set to '{stored}'")
        return 0

    base_store.set_pending_rebase_onto(new_base.strip(), cwd)
    rc = gitops.exec_rebase_onto(new_base, old_base, cwd)
    if rc == 0:
        if gitops.operation_in_progress(cwd) is not None:
            print(
                "Rebase step finished but another operation is in progress — "
                "pending base kept; run 'mr rebase --continue' when done.",
                file=sys.stderr,
            )
            return rc
        try:
            stored = base_store.set_base(new_base, cwd, fetch=False)
        except gitops.GitError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        base_store.clear_pending_rebase_onto(cwd)
        print(f"Rebased {to_replay} commit(s) onto '{new_base}' — base set to '{stored}'.")
        return 0
    if gitops.operation_in_progress(cwd) is None:
        # Rebase never started (not a conflict) — drop the intent we just wrote.
        base_store.clear_pending_rebase_onto(cwd)
        return rc
    print(
        f"Rebase stopped with conflicts in '{current}'. Finish it yourself:",
        file=sys.stderr,
    )
    print("  mr rebase --continue   # after resolving conflicts", file=sys.stderr)
    print("  mr rebase --abort      # to give up (base stays on old base)", file=sys.stderr)
    return rc


def _cmd_rebase_resume(*, mode: str) -> int:
    """Shared ``--continue`` / ``--skip`` handling with pending-base apply."""
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    pending = base_store.get_pending_rebase_onto(cwd)
    if mode == "skip":
        rc = gitops.exec_rebase_skip(cwd)
    else:
        rc = gitops.exec_rebase_continue(cwd)
    if rc != 0 or gitops.operation_in_progress(cwd) is not None:
        if pending is not None and gitops.operation_in_progress(cwd) is None:
            print(
                f"error: no rebase in progress, but pending --onto '{pending}' exists "
                "— you likely finished with 'git rebase --continue'; "
                f"run 'mr base set {pending}' to adopt or 'mr rebase --abort' "
                "to drop it",
                file=sys.stderr,
            )
        return rc
    if pending is None:
        return 0
    try:
        stored = base_store.set_base(pending, cwd, fetch=False)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    base_store.clear_pending_rebase_onto(cwd)
    print(f"base set to '{stored}'")
    return 0


def cmd_rebase_continue() -> int:
    """Continue an in-progress rebase; apply a pending ``--onto`` base when done."""
    return _cmd_rebase_resume(mode="continue")


def cmd_rebase_skip() -> int:
    """Skip the current patch; apply a pending ``--onto`` base when done."""
    return _cmd_rebase_resume(mode="skip")


def cmd_rebase_abort() -> int:
    """Abort the in-progress rebase and drop any pending ``--onto`` base."""
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    pending = base_store.get_pending_rebase_onto(cwd)
    rc = gitops.exec_rebase_abort(cwd)
    base_store.clear_pending_rebase_onto(cwd)
    if pending is not None:
        print(f"Dropped pending base '{pending}'.")
    return rc


def cmd_reset(*, mode: str = "mixed", fetch: bool) -> int:
    """Reset the current branch to this worktree's base."""
    if mode not in ("soft", "mixed", "hard"):
        print(f"error: invalid reset mode '{mode}' (expected soft|mixed|hard)", file=sys.stderr)
        return 2
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    try:
        base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        gitops.ensure_fresh_base(base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Inherit stdio so output behaves like plain `git reset`.
    return gitops.exec_reset(mode, base, cwd)


def cmd_squash(*, message: str | None, fetch: bool) -> int:
    """Squash ``<base>..HEAD`` into a single commit on top of the merge-base."""
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    current = gitops.current_branch(cwd)
    if current is None:
        print("error: detached HEAD — checkout a branch first", file=sys.stderr)
        return 2
    try:
        base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    op = gitops.operation_in_progress(cwd)
    if op is not None:
        print(f"error: '{current}' worktree is mid-{op} — resolve it first", file=sys.stderr)
        return 2
    if not gitops.is_clean(cwd):
        print("error: working tree has uncommitted changes", file=sys.stderr)
        return 2
    try:
        gitops.ensure_fresh_base(base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        mb = gitops.merge_base(base, cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        to_squash = gitops.rev_list_count(f"{base}..HEAD", cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if to_squash == 0:
        print(f"Nothing to squash — '{current}' has no commits beyond {base}.")
        return 0
    if message is not None:
        msg = message
    else:
        if to_squash == 1:
            print(f"Nothing to squash — '{current}' is already a single commit.")
            return 0
        try:
            fallback = gitops.last_commit_message(cwd)
        except gitops.GitError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        prompted = _ask_squash_message(fallback)
        if prompted is None:
            print("Aborted.", file=sys.stderr)
            return 130
        msg = prompted
    rs = gitops.reset_soft_to(mb, cwd)
    if rs.returncode != 0:
        if rs.stderr:
            print(rs.stderr.rstrip(), file=sys.stderr)
        return rs.returncode
    co = gitops.commit(msg, cwd)
    if co.returncode != 0:
        if co.stderr:
            print(co.stderr.rstrip(), file=sys.stderr)
        print(
            "error: commit failed after soft reset. Complete it yourself with:",
            file=sys.stderr,
        )
        print("  git commit   # to conclude the squash", file=sys.stderr)
        print("  git reset --hard ORIG_HEAD   # to restore the original commits", file=sys.stderr)
        return co.returncode
    print(f"Squashed {to_squash} commit(s) into one on '{current}'.")
    return 0


def _default_message(subjects: Sequence[str]) -> str:
    subject = subjects[0]
    rest = [s for s in subjects[1:] if s]
    if not rest:
        return subject
    return subject + "\n\n" + "\n".join(rest)


def _ask_squash_message(default: str) -> str | None:
    try:
        interactive = sys.stdin.isatty()
    except (OSError, ValueError):
        return default
    if not interactive:
        return default
    print("Default commit message:")
    print(default)
    try:
        typed = input("Commit message (empty keeps default): ")
    except EOFError:
        return default
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return None
    if not typed.strip():
        return default
    return typed.strip()


def cmd_merge(
    *,
    message: str | None,
    strategy: str | None,
    push: bool | None,
    fetch: bool,
) -> int:
    """Rebase the current branch onto its base, then merge into the base worktree."""
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    current = gitops.current_branch(cwd)
    if current is None:
        print("error: detached HEAD — checkout a branch first", file=sys.stderr)
        return 2
    try:
        base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    resolved_strategy = strategy if strategy is not None else config_store.get_merge_strategy()
    if push is True:
        push_mode = "always"
    elif push is False:
        push_mode = "never"
    else:
        push_mode = config_store.get_merge_push()

    parsed = gitops.parse_remote_ref(base, cwd)
    if parsed is not None:
        remote, remote_branch = parsed
        local_base = remote_branch
        if not gitops.branch_exists(local_base, cwd):
            print(
                f"error: no local branch '{local_base}' for remote base '{base}' "
                f"— create it and check it out in a worktree first",
                file=sys.stderr,
            )
            return 2
    else:
        remote = None
        local_base = base

    if current == local_base:
        print(
            f"error: already on base branch '{current}' — "
            "merge would be a no-op (merge-base equals HEAD)",
            file=sys.stderr,
        )
        return 2

    op = gitops.operation_in_progress(cwd)
    if op is not None:
        print(
            f"error: '{current}' worktree is mid-{op} — resolve it first",
            file=sys.stderr,
        )
        return 2
    if not gitops.is_clean(cwd):
        print("error: working tree has uncommitted changes", file=sys.stderr)
        return 2

    try:
        gitops.ensure_fresh_base(base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        gitops.resolve_to_commit(local_base, cwd)
    except gitops.GitError:
        print(f"error: base '{base}' does not resolve to a commit", file=sys.stderr)
        return 2
    try:
        gitops.merge_base(local_base, cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    base_wt = gitops.find_worktree_for_branch(local_base, cwd)
    if base_wt is None:
        print(
            f"error: no worktree has '{local_base}' checked out "
            f"— check it out in a worktree first (e.g. git worktree add)",
            file=sys.stderr,
        )
        return 2

    owner = gitops.current_branch(base_wt)
    if owner != local_base:
        print(
            f"error: '{local_base}' worktree ({base_wt}) is detached or "
            "mid-rebase/merge — resolve it first",
            file=sys.stderr,
        )
        return 2
    op = gitops.operation_in_progress(base_wt)
    if op is not None:
        print(
            f"error: '{local_base}' worktree ({base_wt}) is mid-{op} — resolve it first",
            file=sys.stderr,
        )
        return 2
    if not gitops.is_clean(base_wt):
        print(
            f"error: '{local_base}' worktree ({base_wt}) has uncommitted changes",
            file=sys.stderr,
        )
        return 2
    try:
        head_sha = gitops.rev_parse("HEAD", base_wt)
        base_sha = gitops.rev_parse(local_base, base_wt)
    except gitops.GitError:
        print(
            f"error: '{local_base}' worktree ({base_wt}) is detached or "
            "mid-rebase/merge — resolve it first",
            file=sys.stderr,
        )
        return 2
    if head_sha != base_sha:
        print(
            f"error: '{local_base}' worktree ({base_wt}) is detached or "
            "mid-rebase/merge — resolve it first",
            file=sys.stderr,
        )
        return 2

    if parsed is not None and remote is not None:
        ff = gitops.merge_ff_only(base, base_wt)
        if ff.returncode != 0:
            try:
                behind = gitops.rev_list_count(f"{local_base}..{base}", base_wt)
            except gitops.GitError:
                behind = 1
            if behind > 0:
                if ff.stderr:
                    print(ff.stderr.rstrip(), file=sys.stderr)
                print(
                    f"error: cannot fast-forward '{local_base}' to '{base}' "
                    f"({base_wt} is diverged or behind) — resolve it first",
                    file=sys.stderr,
                )
                return 2
            print(
                f"Note: local '{local_base}' is ahead of {base} "
                f"— merging onto local '{local_base}'.",
                file=sys.stderr,
            )
        else:
            try:
                ahead = gitops.rev_list_count(f"{base}..{local_base}", base_wt)
            except gitops.GitError:
                ahead = 0
            if ahead > 0:
                print(
                    f"Note: local '{local_base}' is ahead of {base} "
                    f"— merging onto local '{local_base}'.",
                    file=sys.stderr,
                )

    print(f"Rebasing '{current}' onto {local_base}...")
    rc = gitops.exec_rebase(local_base, cwd)
    if rc != 0:
        print(
            f"Rebase stopped with conflicts in '{current}'. Finish it yourself:",
            file=sys.stderr,
        )
        print("  git rebase --continue   # after resolving conflicts", file=sys.stderr)
        print("or abandon with: git rebase --abort", file=sys.stderr)
        return rc

    try:
        to_merge = gitops.rev_list_count(f"{local_base}..HEAD", cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if to_merge == 0:
        print(f"Nothing to merge — '{current}' has no commits beyond {local_base}.")
        return 0

    if message is not None:
        msg = message
    else:
        try:
            subjects = gitops.commit_subjects(f"{local_base}..HEAD", cwd)
        except gitops.GitError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if not subjects:
            print(f"Nothing to merge — '{current}' has no commits beyond {local_base}.")
            return 0
        fallback_msg = _default_message(subjects)
        if resolved_strategy == "squash":
            prompted = _ask_squash_message(fallback_msg)
            if prompted is None:
                print("Aborted.", file=sys.stderr)
                return 130
            msg = prompted
        else:
            msg = fallback_msg

    if resolved_strategy == "squash":
        print(f"Rebase clean ({to_merge} commit(s)). Squashing into {local_base}...")
        sq = gitops.merge_squash(current, base_wt)
        if sq.returncode != 0:
            if sq.stderr:
                print(sq.stderr.rstrip(), file=sys.stderr)
            print(
                f"error: squash-merge stopped with conflicts in '{base_wt}'. "
                "Resolve them there, then complete with:",
                file=sys.stderr,
            )
            print(f"  git -C {base_wt} commit", file=sys.stderr)
            print(f"or abandon with: git -C {base_wt} reset --hard HEAD", file=sys.stderr)
            return sq.returncode
        co = gitops.commit(msg, base_wt)
        if co.returncode != 0:
            if co.stderr:
                print(co.stderr.rstrip(), file=sys.stderr)
            print(
                f"error: commit failed in '{base_wt}'. Complete it yourself with:",
                file=sys.stderr,
            )
            print(f"  git -C {base_wt} commit", file=sys.stderr)
            print(f"or abandon with: git -C {base_wt} reset --hard HEAD", file=sys.stderr)
            return co.returncode
    else:
        print(f"Rebase clean ({to_merge} commit(s)). Merging into {local_base}...")
        mg = gitops.merge_no_ff(current, msg, base_wt)
        if mg.returncode != 0:
            if mg.stderr:
                print(mg.stderr.rstrip(), file=sys.stderr)
            print(
                f"Merge stopped with conflicts in '{base_wt}'. Resolve them there, "
                "then complete with:",
                file=sys.stderr,
            )
            print(f"  git -C {base_wt} commit   # to conclude the merge", file=sys.stderr)
            print(f"or abandon with: git -C {base_wt} merge --abort", file=sys.stderr)
            return mg.returncode

    if not gitops.is_clean(cwd):
        print(
            "error: working tree has uncommitted changes — "
            f"not realigning '{current}' to {local_base}",
            file=sys.stderr,
        )
        return 2
    # Realign the feature branch with the merged base so it isn't left diverged
    # (the squash landed the base's tree identical to the branch's, and a
    # --no-ff merge has the branch as a parent — either way moving the pointer
    # is safe and the working tree is untouched).
    rs = gitops.reset_to(local_base, cwd)
    if rs.returncode != 0:
        if rs.stderr:
            print(rs.stderr.rstrip(), file=sys.stderr)
        return rs.returncode

    if resolved_strategy == "squash":
        print(f"Squashed {to_merge} commit(s) onto {local_base}.")
    else:
        print(f"Merged {to_merge} commit(s) onto {local_base} (--no-ff).")

    do_push = push_mode == "always" or (push_mode == "auto" and parsed is not None)
    if do_push:
        if parsed is None or remote is None:
            print(f"Skipped push (base '{base}' is not a remote branch).")
        else:
            pr = gitops.push(remote, local_base, base_wt)
            if pr.returncode != 0:
                print(
                    f"Warning: push failed — the commit is local on {local_base}",
                    file=sys.stderr,
                )
                if pr.stderr:
                    print(pr.stderr.rstrip(), file=sys.stderr)
            else:
                print(f"Pushed {local_base} to {remote}.")
    else:
        if push is False:
            print(f"Skipped push (--no-push) — {local_base} has local-only commits.")

    print(
        f"Done. You are on '{current}', realigned to {local_base} "
        f"(the '{local_base}' worktree was updated: {base_wt})."
    )
    print(f"Delete the feature branch with: git branch -D {current}")
    return 0


def cmd_publish(
    *,
    fetch: bool,
    push: bool,
    fill: bool,
    yes: bool,
    draft: bool,
    title: str | None,
    description: str | None,
    labels: Sequence[str] | None,
    assignees: Sequence[str] | None,
    reviewers: Sequence[str] | None,
    remove_source_branch: bool,
    extra: Sequence[str] | None,
) -> int:
    """Push the current branch (unless skipped) and open a GitLab MR via glab."""
    cwd = _cwd()
    try:
        gitops.repo_root(cwd)
    except gitops.GitError as exc:
        print(f"error: not a git repository: {exc}", file=sys.stderr)
        return 2
    current = gitops.current_branch(cwd)
    if current is None:
        print("error: detached HEAD — checkout a branch first", file=sys.stderr)
        return 2
    try:
        base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parsed = gitops.parse_remote_ref(base, cwd)
    if parsed is None:
        print(
            f"error: base '{base}' is not a remote branch "
            "— set one first (e.g. mr base set origin/main)",
            file=sys.stderr,
        )
        return 2
    remote, target = parsed
    if current == target:
        print(
            f"error: already on base branch '{current}' — there is nothing to publish",
            file=sys.stderr,
        )
        return 2

    op = gitops.operation_in_progress(cwd)
    if op is not None:
        print(
            f"error: '{current}' worktree is mid-{op} — resolve it first",
            file=sys.stderr,
        )
        return 2
    if not gitops.is_clean(cwd):
        print("error: working tree has uncommitted changes", file=sys.stderr)
        return 2

    try:
        gitops.ensure_fresh_base(base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if glabops.find_glab() is None:
        print(f"error: glab not found on PATH ({glabops.INSTALL_HINT})", file=sys.stderr)
        return 2

    if push:
        upstream = gitops.upstream_ref(cwd)
        if upstream is None:
            print(f"Pushing '{current}' to {remote}...")
            pr = gitops.push_set_upstream(remote, current, cwd)
            if pr.returncode != 0:
                if pr.stderr:
                    print(pr.stderr.rstrip(), file=sys.stderr)
                print(
                    f"error: failed to push '{current}' to '{remote}'",
                    file=sys.stderr,
                )
                return pr.returncode
            print(f"Pushed '{current}' to {remote} (upstream set).")
        else:
            try:
                ahead = gitops.rev_list_count(f"{upstream}..HEAD", cwd)
            except gitops.GitError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if ahead > 0:
                print(f"Pushing {ahead} commit(s) to {upstream}...")
                pr = gitops.push_current(cwd)
                if pr.returncode != 0:
                    if pr.stderr:
                        print(pr.stderr.rstrip(), file=sys.stderr)
                    print(
                        f"error: failed to push '{current}' to '{upstream}'",
                        file=sys.stderr,
                    )
                    return pr.returncode
                print(f"Pushed '{current}' to {upstream}.")
            else:
                print(f"Branch '{current}' already pushed to {upstream}.")
    else:
        print(f"Skipped push (--no-push) — assuming '{current}' is on {remote}.")

    forwarded = list(extra or [])
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    glab_args = glabops.build_create_args(
        target,
        fill=fill,
        yes=yes,
        draft=draft,
        title=title,
        description=description,
        labels=labels,
        assignees=assignees,
        reviewers=reviewers,
        remove_source_branch=remove_source_branch,
        extra=forwarded,
    )
    # Inherit stdio so glab's interactive prompts/editors behave like plain `glab`.
    return glabops.exec_create(glab_args, cwd)


def cmd_config_list() -> int:
    values = config_store.read_config()
    for key in sorted(config_store.ALLOWED):
        print(f"{key}={values.get(key, config_store.DEFAULTS[key])}")
    return 0


def cmd_config_set(key: str, value: str) -> int:
    try:
        config_store.set_value(key, value)
    except config_store.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{key}={value}")
    return 0


def cmd_config_reset(key: str | None) -> int:
    try:
        config_store.reset_value(key)
    except config_store.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if key is None:
        print("config reset")
    else:
        print(f"{key} reset")
    return 0


def _resolve_shells(shells: Sequence[str] | None) -> list[str] | None:
    """Deduplicated shells, or the current ``$SHELL``; None (+stderr) if unknown."""
    if shells:
        resolved: list[str] = []
        for shell in shells:
            if shell not in resolved:
                resolved.append(shell)
        return resolved
    detected = detect_shell()
    if detected is None:
        print(
            "error: cannot detect shell from $SHELL — pass --shell bash|zsh",
            file=sys.stderr,
        )
        return None
    return [detected]


def cmd_completion_install(shells: Sequence[str] | None, *, dry_run: bool = False) -> int:
    """Install mr + mr-diff completion into the rc file(s)."""
    resolved = _resolve_shells(shells)
    if resolved is None:
        return 2
    return install_completion(resolved, dry_run=dry_run)


def cmd_completion_uninstall(shells: Sequence[str] | None) -> int:
    """Remove the managed completion block from the rc file(s)."""
    resolved = _resolve_shells(shells)
    if resolved is None:
        return 2
    return uninstall_completion(resolved)


def main(argv: Sequence[str] | None = None) -> int:
    completed = handle_print_completion("mr", argv)
    if completed is not None:
        return completed
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args.branch, args.base, fetch=not args.no_fetch)
    if args.command == "rebase":
        if args.onto is not None:
            return cmd_rebase_onto(args.onto, fetch=not args.no_fetch)
        if args.continue_op:
            return cmd_rebase_continue()
        if args.skip_op:
            return cmd_rebase_skip()
        if args.abort_op:
            return cmd_rebase_abort()
        return cmd_rebase(fetch=not args.no_fetch)
    if args.command == "reset":
        if args.soft:
            reset_mode = "soft"
        elif args.hard:
            reset_mode = "hard"
        else:
            reset_mode = "mixed"
        return cmd_reset(mode=reset_mode, fetch=not args.no_fetch)
    if args.command == "squash":
        return cmd_squash(message=args.message, fetch=not args.no_fetch)
    if args.command == "merge":
        if args.squash and args.no_ff:
            print("error: --squash and --no-ff are mutually exclusive", file=sys.stderr)
            return 2
        if args.push and args.no_push:
            print("error: --push and --no-push are mutually exclusive", file=sys.stderr)
            return 2
        if args.squash:
            strategy = "squash"
        elif args.no_ff:
            strategy = "merge"
        else:
            strategy = None
        if args.push:
            push: bool | None = True
        elif args.no_push:
            push = False
        else:
            push = None
        return cmd_merge(
            message=args.message,
            strategy=strategy,
            push=push,
            fetch=not args.no_fetch,
        )
    if args.command == "publish":
        return cmd_publish(
            fetch=not args.no_fetch,
            push=not args.no_push,
            fill=args.fill,
            yes=args.yes,
            draft=args.draft,
            title=args.title,
            description=args.description,
            labels=args.labels,
            assignees=args.assignees,
            reviewers=args.reviewers,
            remove_source_branch=args.remove_source_branch,
            extra=args.extra,
        )
    if args.command == "config":
        if args.config_command == "set":
            return cmd_config_set(args.key, args.value)
        if args.config_command == "reset":
            return cmd_config_reset(args.key)
        return cmd_config_list()
    if args.command == "completion":
        if args.completion_command == "install":
            return cmd_completion_install(args.shells, dry_run=args.dry_run)
        if args.completion_command == "uninstall":
            return cmd_completion_uninstall(args.shells)
        return completion_status()
    if args.command == "base":
        if args.base_command == "set":
            return cmd_base_set(args.base, fetch=not args.no_fetch)
        if args.base_command == "reset":
            return cmd_base_reset()
        if args.base_command == "default":
            if args.default_command == "set":
                return cmd_base_default_set(args.ref, fetch=not args.no_fetch)
            if args.default_command == "reset":
                return cmd_base_default_reset()
            return cmd_base_default_print()
        return cmd_base_print()
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
