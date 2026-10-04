"""``mr`` CLI: easy branch creation + per-worktree base pointer."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from utilities import base_store, config_store
from utilities import git as gitops


def _cwd() -> Path:
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mr", description="Branch + base-branch helper")
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
    p_rebase.add_argument(
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
        help="Squash/merge commit message (default: built from branch subjects).",
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
    result = gitops.run_git(["checkout", "-b", branch, resolved_base], cwd, check=False)
    if result.returncode != 0:
        # Let git's own message (e.g. "would be overwritten by checkout") go to stderr.
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return result.returncode
    base_store.set_base_after_create(resolved_base, cwd)
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
    print(f"base set to '{stored}'")
    return 0


def cmd_base_reset() -> int:
    cwd = _cwd()
    try:
        ref = base_store.reset_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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
    try:
        gitops.ensure_fresh_base(base, cwd, fetch=fetch)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Inherit stdio so conflicts/editors behave like plain `git rebase`.
    return gitops.exec_rebase(base, cwd)


def _default_message(subjects: Sequence[str]) -> str:
    subject = subjects[0]
    rest = [s for s in subjects[1:] if s]
    if not rest:
        return subject
    return subject + "\n\n" + "\n".join(rest)


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
        msg = _default_message(subjects)

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args.branch, args.base, fetch=not args.no_fetch)
    if args.command == "rebase":
        return cmd_rebase(fetch=not args.no_fetch)
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
    if args.command == "config":
        if args.config_command == "set":
            return cmd_config_set(args.key, args.value)
        if args.config_command == "reset":
            return cmd_config_reset(args.key)
        return cmd_config_list()
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
