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


def test_effective_default_without_custom(git_repo: Path) -> None:
    assert base_store.get_custom_default(git_repo) is None
    assert base_store.get_effective_default(git_repo) == "origin/main"


def test_custom_default_overrides_get_base_and_reset(git_repo: Path) -> None:
    subprocess.run(["git", "branch", "develop", "main"], cwd=str(git_repo), check=True)
    subprocess.run(["git", "branch", "other", "main"], cwd=str(git_repo), check=True)
    assert base_store.set_custom_default("develop", git_repo, fetch=False) == "develop"
    assert base_store.get_effective_default(git_repo) == "develop"
    assert base_store.get_base(git_repo) == "develop"
    base_store.set_base("other", git_repo, fetch=False)
    assert base_store.get_base(git_repo) == "other"
    assert base_store.reset_base(git_repo) == "develop"
    assert base_store.reset_custom_default(git_repo) == "origin/main"
    assert base_store.get_custom_default(git_repo) is None
    assert base_store.get_effective_default(git_repo) == "origin/main"


def test_custom_default_shared_across_worktrees(git_repo: Path, tmp_path: Path) -> None:
    subprocess.run(["git", "branch", "develop", "main"], cwd=str(git_repo), check=True)
    base_store.set_custom_default("develop", git_repo, fetch=False)

    wt2 = tmp_path / "wt2"
    subprocess.run(
        ["git", "worktree", "add", str(wt2), "-b", "wt2-branch"], cwd=str(git_repo), check=True
    )
    try:
        assert base_store.get_effective_default(wt2) == "develop"
        assert base_store.get_base(wt2) == "develop"
        base_store.set_base("origin/main", wt2, fetch=False)
        assert base_store.get_base(wt2) == "origin/main"
        # Per-worktree override does not leak; repo default is unchanged.
        assert base_store.get_effective_default(git_repo) == "develop"
        assert base_store.get_base(git_repo) == "develop"
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt2)], cwd=str(git_repo), check=True
        )
