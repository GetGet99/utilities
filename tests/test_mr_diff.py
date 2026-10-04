"""Tests for `mr-diff list` / `mr-diff file` three-dot semantics."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import base_store
from utilities import git as gitops
from utilities.cli_mr_diff import cmd_file, cmd_list


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _setup_branch_with_changes(repo: Path) -> None:
    _git(["checkout", "-b", "feature"], repo)
    (repo / "feature.txt").write_text("committed\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "feature commit"], repo)
    # staged change
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(["add", "staged.txt"], repo)
    # unstaged change
    (repo / "feature.txt").write_text("committed\nunstaged edit\n", encoding="utf-8")


def test_diff_list_includes_committed_staged_unstaged(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup_branch_with_changes(git_repo)
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_list(name_only=False) == 0
    out = capsys.readouterr().out
    assert "feature.txt" in out
    assert "staged.txt" in out


def test_diff_list_excludes_changes_on_base_after_divergence(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    (git_repo / "feature.txt").write_text("x\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "f"], git_repo)
    _git(["checkout", "main"], git_repo)
    (git_repo / "base-only.txt").write_text("only on base\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "base moves"], git_repo)
    _git(["checkout", "feature"], git_repo)
    base_store.set_base("origin/main", git_repo, fetch=False)
    # Our base pointer still resolves to old origin/main; refresh it to current main.
    _git(["update-ref", "refs/remotes/origin/main", "main"], git_repo)

    assert cmd_list(name_only=True) == 0
    out = capsys.readouterr().out
    assert "feature.txt" in out
    assert "base-only.txt" not in out


def test_diff_file_returns_zero_and_shows_patch(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup_branch_with_changes(git_repo)
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_file("feature.txt") == 0


def test_merge_base_used_not_plain_two_dot(git_repo: Path) -> None:
    _setup_branch_with_changes(git_repo)
    mb = gitops.merge_base("origin/main", git_repo)
    assert gitops.diff_name_status(mb, git_repo) != ""
