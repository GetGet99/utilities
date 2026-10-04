"""``mr-diff`` CLI: GitLab-style three-dot diff vs the worktree's base.

Shows committed-on-branch changes PLUS staged/unstaged working-tree changes
by diffing against ``git merge-base <base> HEAD``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from utilities import base_store
from utilities import git as gitops


def _cwd() -> Path:
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mr-diff", description="GitLab-style diff of current branch vs base"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="List files changed vs base")
    p_list.add_argument(
        "--name-only", action="store_true", help="Print paths only (default: name-status)."
    )
    p_file = sub.add_parser("file", help="Show diff for one file vs base")
    p_file.add_argument("path", help="Path to file (repo-relative or absolute)")
    return parser


def _resolve_merge_base(cwd: Path) -> tuple[str, str] | None:
    """Return (base, merge_base_sha), printing errors to stderr."""
    try:
        base = base_store.get_base(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    try:
        gitops.resolve_to_commit(base, cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    try:
        mb = gitops.merge_base(base, cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    return (base, mb)


def cmd_list(*, name_only: bool) -> int:
    cwd = _cwd()
    resolved = _resolve_merge_base(cwd)
    if resolved is None:
        return 2
    base, mb = resolved
    flag = "--name-only" if name_only else "--name-status"
    result = gitops.run_git(["diff", flag, mb], cwd, check=False)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return result.returncode
    if result.stdout:
        sys.stdout.write(result.stdout if result.stdout.endswith("\n") else result.stdout + "\n")
    short = mb[:12]
    print(f"# base: {base} (merge-base {short})", file=sys.stderr)
    untracked = gitops.run_git(["ls-files", "--others", "--exclude-standard"], cwd, check=False)
    if untracked.returncode == 0 and untracked.stdout.strip():
        count = len(untracked.stdout.splitlines())
        print(
            f"# note: {count} untracked file(s) hidden (GitLab parity) — see git status",
            file=sys.stderr,
        )
    return 0


def cmd_file(path: str) -> int:
    cwd = _cwd()
    resolved = _resolve_merge_base(cwd)
    if resolved is None:
        return 2
    base, mb = resolved
    print(f"# base: {base} (merge-base {mb[:12]})", file=sys.stderr)
    # Inherit stdio so git pager/color behave like plain `git diff`.
    completed = subprocess.run(["git", "diff", mb, "--", path], cwd=str(cwd), check=False)
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(name_only=args.name_only)
    if args.command == "file":
        return cmd_file(args.path)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
