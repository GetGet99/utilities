"""``mr`` CLI: easy branch creation + per-worktree base pointer."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from utilities import base_store
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
        help="Base ref (default: origin/<default-branch>). Accepts local or origin/<branch>.",
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
    base_sub.add_parser("reset", help="Reset base to origin/<default-branch>")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "new":
        return cmd_new(args.branch, args.base, fetch=not args.no_fetch)
    if args.command == "base":
        if args.base_command == "set":
            return cmd_base_set(args.base, fetch=not args.no_fetch)
        if args.base_command == "reset":
            return cmd_base_reset()
        return cmd_base_print()
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
