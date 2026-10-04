"""Tests for `mr new` / `mr base` (VSCode-parity + edge cases)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import base_store
from utilities.cli_mr import cmd_base_reset, cmd_base_set, cmd_new


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def test_mr_new_creates_branch_from_default_base(git_repo: Path) -> None:
    assert cmd_new("feature-a", None, fetch=False) == 0
    assert gitops_current_branch(git_repo) == "feature-a"
    assert base_store.get_base(git_repo) == "origin/main"


def gitops_current_branch(cwd: Path) -> str:
    out = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def test_mr_new_with_custom_base(git_repo: Path) -> None:
    _git(["branch", "custom-base", "main"], git_repo)
    assert cmd_new("feature-b", "custom-base", fetch=False) == 0
    assert gitops_current_branch(git_repo) == "feature-b"
    assert base_store.get_base(git_repo) == "custom-base"


def test_mr_new_blocks_when_branch_exists(git_repo: Path) -> None:
    _git(["branch", "taken", "main"], git_repo)
    assert cmd_new("taken", None, fetch=False) == 2
    assert gitops_current_branch(git_repo) == "main"


def test_mr_new_blocks_when_base_does_not_resolve(git_repo: Path) -> None:
    assert cmd_new("feature-c", "no-such-base", fetch=False) == 2
    assert gitops_current_branch(git_repo) == "main"


def test_mr_new_no_default_base_is_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repo with no remotes and no stored base: exit 2, no traceback."""
    repo = tmp_path / "lonely"
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "a"], cwd=str(repo), check=True)
    monkeypatch.chdir(repo)
    assert cmd_new("feature-x", None, fetch=False) == 2
    assert gitops_current_branch(repo) == "main"


def test_mr_new_blocks_when_checkout_would_overwrite(git_repo: Path) -> None:
    # Uncommitted change to a tracked file that differs on the base blocks checkout.
    _git(["checkout", "-b", "other"], git_repo)
    (git_repo / "README.md").write_text("other content\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "other"], git_repo)
    _git(["checkout", "main"], git_repo)
    (git_repo / "README.md").write_text("dirty conflicting content\n", encoding="utf-8")
    assert cmd_new("fresh", "other", fetch=False) != 0


def test_mr_base_set_and_reset(git_repo: Path) -> None:
    _git(["branch", "alt", "main"], git_repo)
    assert cmd_base_set("alt", fetch=False) == 0
    assert base_store.get_base(git_repo) == "alt"
    assert cmd_base_reset() == 0
    assert base_store.get_base(git_repo) == "origin/main"


def test_mr_base_set_rejects_bad_ref(git_repo: Path) -> None:
    assert cmd_base_set("no-such-ref", fetch=False) == 2
