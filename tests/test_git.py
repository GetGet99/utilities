"""Tests for git helpers: slash-safety, default branch, fetch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import git as gitops


def test_parse_remote_ref_ignores_slash_branch_without_remote(git_repo: Path) -> None:
    assert gitops.parse_remote_ref("feat/my-new-feature", git_repo) is None
    assert gitops.parse_remote_ref("main", git_repo) is None


def test_parse_remote_ref_splits_on_first_slash(git_repo: Path) -> None:
    assert gitops.parse_remote_ref("origin/main", git_repo) == ("origin", "main")
    assert gitops.parse_remote_ref("origin/feature/foo", git_repo) == ("origin", "feature/foo")


def test_parse_remote_ref_unknown_remote_returns_none(git_repo: Path) -> None:
    assert gitops.parse_remote_ref("upstream/main", git_repo) is None


def test_default_branch_is_main(git_repo: Path) -> None:
    assert gitops.default_branch(git_repo) == "main"
    assert gitops.default_remote_base(git_repo) == "origin/main"


def test_ensure_fresh_base_fetches_remote(tmp_path: Path) -> None:
    # origin advances after clone; ensure_fresh_base must pull the new commit.
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(seed)], check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(seed), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(seed), check=True)
    (seed / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(seed), check=True)
    subprocess.run(["git", "commit", "-m", "a"], cwd=str(seed), check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=str(seed), check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(seed), check=True)

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(clone), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone), check=True)

    # Advance origin.
    (seed / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(seed), check=True)
    subprocess.run(["git", "commit", "-m", "b"], cwd=str(seed), check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(seed), check=True)

    before = gitops.resolve_to_commit("origin/main", clone)
    gitops.ensure_fresh_base("origin/main", clone, fetch=True)
    after = gitops.resolve_to_commit("origin/main", clone)
    assert before != after

    # --no-fetch equivalent leaves the ref untouched.
    (seed / "c.txt").write_text("c\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(seed), check=True)
    subprocess.run(["git", "commit", "-m", "c"], cwd=str(seed), check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(seed), check=True)
    gitops.ensure_fresh_base("origin/main", clone, fetch=False)
    assert gitops.resolve_to_commit("origin/main", clone) == after


def test_ensure_fresh_base_hard_fails_on_bad_ref(git_repo: Path) -> None:
    with pytest.raises(gitops.GitError):
        gitops.ensure_fresh_base("origin/does-not-exist", git_repo, fetch=True)
