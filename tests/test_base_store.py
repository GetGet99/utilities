"""Tests for per-worktree base storage."""

from __future__ import annotations

import subprocess
from pathlib import Path

from utilities import base_store


def test_get_base_defaults_to_origin_main(git_repo: Path) -> None:
    assert base_store.get_base(git_repo) == "origin/main"


def test_set_and_reset_base(git_repo: Path) -> None:
    assert base_store.set_base("origin/main", git_repo) == "origin/main"
    assert base_store.get_base(git_repo) == "origin/main"
    assert base_store.reset_base(git_repo) == "origin/main"


def test_bases_are_per_worktree(git_repo: Path, tmp_path: Path) -> None:
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(git_repo), check=True)
    base_store.set_base("origin/main", git_repo)

    wt2 = tmp_path / "wt2"
    subprocess.run(
        ["git", "worktree", "add", str(wt2), "-b", "wt2-branch"], cwd=str(git_repo), check=True
    )
    try:
        # New worktree starts from default, independent of the first worktree.
        assert base_store.get_base(wt2) == "origin/main"
        subprocess.run(["git", "branch", "other", "main"], cwd=str(git_repo), check=True)
        base_store.set_base("other", wt2, fetch=False)
        assert base_store.get_base(wt2) == "other"
        assert base_store.get_base(git_repo) == "origin/main"
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt2)], cwd=str(git_repo), check=True
        )
