"""``mr-diff`` CLI: full review-scope diff vs the worktree's base.

Shows committed-on-branch changes PLUS staged/unstaged working-tree changes
PLUS untracked (non-ignored) files as new files, by diffing against
``git merge-base <base> HEAD`` with rename detection forced on.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from utilities import base_store
from utilities import git as gitops
from utilities.completion import handle_print_completion


def _cwd() -> Path:
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mr-diff", description="Review-scope diff of current branch vs base"
    )
    parser.add_argument(
        "--print-completion",
        choices=["bash", "zsh"],
        default=None,
        help="Print shell completion script and exit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="List files changed vs base")
    p_list.add_argument(
        "--name-only", action="store_true", help="Print paths only (default: name-status)."
    )
    p_file = sub.add_parser("file", help="Show diff for one file vs base")
    p_file.add_argument("path", help="Path to a file (repo-relative or absolute)")
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


def _sort_key(line: str) -> str:
    """Sort key for a ``list`` row: the final path (rename destination for ``R``)."""
    return line.split("\t")[-1] if "\t" in line else line


def cmd_list(*, name_only: bool) -> int:
    cwd = _cwd()
    resolved = _resolve_merge_base(cwd)
    if resolved is None:
        return 2
    base, mb = resolved
    try:
        if name_only:
            tracked = gitops.diff_name_only(mb, cwd)
        else:
            tracked = gitops.diff_name_status(mb, cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rows = [line for line in (line.strip() for line in tracked.splitlines()) if line]
    try:
        untracked = gitops.list_untracked(cwd)
    except gitops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if name_only:
        rows.extend(untracked)
    else:
        rows.extend(f"A\t{path}" for path in untracked)
    for row in sorted(rows, key=_sort_key):
        sys.stdout.write(row + "\n")
    short = mb[:12]
    print(f"# base: {base} (merge-base {short})", file=sys.stderr)
    return 0


def cmd_file(path: str) -> int:
    cwd = _cwd()
    resolved = _resolve_merge_base(cwd)
    if resolved is None:
        return 2
    base, mb = resolved
    candidate = Path(path) if Path(path).is_absolute() else cwd / path
    try:
        if candidate.is_dir():
            print(f"error: '{path}' is a directory — pass a single file", file=sys.stderr)
            return 2
    except OSError as exc:
        print(f"error: cannot stat '{path}': {exc}", file=sys.stderr)
        return 2
    print(f"# base: {base} (merge-base {mb[:12]})", file=sys.stderr)
    # Inherit stdio so git pager/color behave like plain `git diff`.
    if gitops.is_untracked(path, cwd):
        return gitops.exec_untracked_patch(path, cwd)
    return gitops.exec_diff_patch(mb, cwd, path)


def main(argv: Sequence[str] | None = None) -> int:
    completed = handle_print_completion("mr-diff", argv)
    if completed is not None:
        return completed
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
