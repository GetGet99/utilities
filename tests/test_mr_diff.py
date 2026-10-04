"""Tests for `mr-diff list` / `mr-diff file` review-scope semantics."""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from utilities import base_store
from utilities import git as gitops
from utilities.cli_mr_diff import cmd_file, cmd_list


@contextlib.contextmanager
def _no_pager() -> Iterator[None]:
    """Force ``git diff`` to write plain output (never invoke a pager)."""
    old = os.environ.get("GIT_PAGER")
    os.environ["GIT_PAGER"] = "cat"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("GIT_PAGER", None)
        else:
            os.environ["GIT_PAGER"] = old


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
    with _no_pager():
        assert cmd_file("feature.txt") == 0


def test_merge_base_used_not_plain_two_dot(git_repo: Path) -> None:
    _setup_branch_with_changes(git_repo)
    mb = gitops.merge_base("origin/main", git_repo)
    assert gitops.diff_name_status(mb, git_repo) != ""


def test_diff_list_includes_untracked_as_new_and_sorted(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup_branch_with_changes(git_repo)
    (git_repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (git_repo / "a-untracked.txt").write_text("untracked\n", encoding="utf-8")
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_list(name_only=False) == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line and not line.startswith("#")]
    assert "A\ta-untracked.txt" in rows
    assert "A\tuntracked.txt" in rows
    assert "A\tstaged.txt" in rows  # staged-new renders as new
    keys = [(row.split("\t")[-1]) for row in rows]
    assert keys == sorted(keys)


def test_diff_list_name_only_includes_untracked(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup_branch_with_changes(git_repo)
    (git_repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_list(name_only=True) == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line and not line.startswith("#")]
    assert "untracked.txt" in rows
    assert rows == sorted(rows)
    assert not any("\t" in row for row in rows)


def test_diff_list_hides_ignored_files(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup_branch_with_changes(git_repo)
    (git_repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (git_repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (git_repo / "visible.txt").write_text("visible\n", encoding="utf-8")
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_list(name_only=True) == 0
    out = capsys.readouterr().out
    assert "visible.txt" in out
    assert "ignored.txt" not in out


def test_diff_list_detects_renames(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    _git(["mv", "README.md", "RENAMED.md"], git_repo)
    _git(["commit", "-m", "rename readme"], git_repo)
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_list(name_only=False) == 0
    out = capsys.readouterr().out
    rename_rows = [line for line in out.splitlines() if line.startswith("R")]
    assert rename_rows, f"expected a rename row, got:\n{out}"
    assert any("RENAMED.md" in row for row in rename_rows)


def test_diff_file_on_untracked_returns_zero(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    (git_repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    base_store.set_base("origin/main", git_repo, fetch=False)
    with _no_pager():
        assert cmd_file("untracked.txt") == 0


def test_diff_file_on_directory_fails(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup_branch_with_changes(git_repo)
    (git_repo / "subdir").mkdir(exist_ok=True)
    (git_repo / "subdir" / "nested.txt").write_text("nested\n", encoding="utf-8")
    base_store.set_base("origin/main", git_repo, fetch=False)
    assert cmd_file("subdir") == 2
    err = capsys.readouterr().err
    assert "directory" in err
