"""Shared pytest fixtures: temp git repos with an `origin` remote."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _git_ok(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), check=False, capture_output=True, text=True)


@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A repo with initial commit on `main`, plus a bare `origin` remote.

    Yields the worktree path, with cwd chdir'd into it.
    """
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", "--initial-branch=main", str(origin)], tmp_path)

    work = tmp_path / "work"
    _git(["init", "--initial-branch=main", str(work)], tmp_path)
    _git(["config", "user.email", "test@example.com"], work)
    _git(["config", "user.name", "Test"], work)
    _git(["config", "commit.gpgsign", "false"], work)
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "."], work)
    _git(["commit", "-m", "init"], work)
    _git(["remote", "add", "origin", str(origin)], work)
    _git(["push", "-u", "origin", "main"], work)
    _git(["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], work)

    monkeypatch.chdir(work)
    yield work


@pytest.fixture()
def git_repo_with_feature(git_repo: Path) -> Path:
    """Repo with a second commit on `main` (pushed) for fetch tests."""
    (git_repo / "second.txt").write_text("second\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "second"], git_repo)
    _git(["push", "origin", "main"], git_repo)
    return git_repo
