"""Tests for `mr reset` (reset current branch to this worktree's base)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import base_store
from utilities.cli_mr import cmd_base_set, cmd_reset, main


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _git_out(args: list[str], cwd: Path) -> str:
    out = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _head(cwd: Path) -> str:
    return _git_out(["rev-parse", "HEAD"], cwd)


def _make_feature_with_extra_commit(git_repo: Path) -> str:
    """Create `feature` with one extra commit; return main's SHA for comparison."""
    main_sha = _head(git_repo)
    _git(["checkout", "-b", "feature"], git_repo)
    (git_repo / "feat.txt").write_text("feat\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "feat"], git_repo)
    assert cmd_base_set("main", fetch=False) == 0
    return main_sha


def test_reset_mixed_default_keeps_worktree(git_repo: Path) -> None:
    main_sha = _make_feature_with_extra_commit(git_repo)
    assert cmd_reset(fetch=False) == 0
    assert _head(git_repo) == main_sha
    # Committed file survives as an untracked working-tree file.
    assert (git_repo / "feat.txt").exists()
    assert _git_out(["branch", "--show-current"], git_repo) == "feature"


def test_reset_explicit_mixed_flag(git_repo: Path) -> None:
    main_sha = _make_feature_with_extra_commit(git_repo)
    assert main(["reset", "--mixed", "--no-fetch"]) == 0
    assert _head(git_repo) == main_sha
    assert (git_repo / "feat.txt").exists()


def test_reset_soft_keeps_index(git_repo: Path) -> None:
    main_sha = _make_feature_with_extra_commit(git_repo)
    assert cmd_reset(mode="soft", fetch=False) == 0
    assert _head(git_repo) == main_sha
    staged = _git_out(["diff", "--cached", "--name-only"], git_repo)
    assert "feat.txt" in staged.splitlines()


def test_reset_hard_discards_worktree_changes(git_repo: Path) -> None:
    main_sha = _make_feature_with_extra_commit(git_repo)
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    assert cmd_reset(mode="hard", fetch=False) == 0
    assert _head(git_repo) == main_sha
    assert (git_repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert not (git_repo / "feat.txt").exists()


def test_reset_fetches_remote_base(git_repo: Path, tmp_path: Path) -> None:
    origin = git_repo.parent / "origin.git"
    # Advance origin/main from a second clone so local origin/main is stale.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(other), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(other), check=True)
    (other / "remote.txt").write_text("remote\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(other), check=True)
    subprocess.run(["git", "commit", "-m", "remote"], cwd=str(other), check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(other), check=True)

    stale = _git_out(["rev-parse", "origin/main"], git_repo)
    # Sanity: local remote-tracking ref is behind the true origin/main.
    fresh = _git_out(["rev-parse", "HEAD"], other)
    assert stale != fresh

    _git(["checkout", "-b", "feature"], git_repo)
    (git_repo / "feat.txt").write_text("feat\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "feat"], git_repo)
    assert cmd_base_set("origin/main", fetch=False) == 0

    assert cmd_reset(mode="hard", fetch=True) == 0
    assert _head(git_repo) == fresh
    assert (git_repo / "remote.txt").exists()


def test_reset_no_fetch_uses_stale_remote_ref(git_repo: Path, tmp_path: Path) -> None:
    origin = git_repo.parent / "origin.git"
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(other), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(other), check=True)
    (other / "remote.txt").write_text("remote\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(other), check=True)
    subprocess.run(["git", "commit", "-m", "remote"], cwd=str(other), check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(other), check=True)

    stale = _git_out(["rev-parse", "origin/main"], git_repo)
    _git(["checkout", "-b", "feature"], git_repo)
    (git_repo / "feat.txt").write_text("feat\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "feat"], git_repo)
    assert cmd_base_set("origin/main", fetch=False) == 0

    assert main(["reset", "--hard", "--no-fetch"]) == 0
    assert _head(git_repo) == stale


def test_reset_blocks_on_bad_base(git_repo: Path) -> None:
    base_store.set_base_after_create("no-such-base", git_repo)
    assert cmd_reset(fetch=False) == 2


def test_reset_blocks_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "lonely"
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "a"], cwd=str(repo), check=True)
    monkeypatch.chdir(repo)
    assert cmd_reset(fetch=False) == 2


def test_reset_invalid_mode_rejected(git_repo: Path) -> None:
    assert cmd_reset(mode="bogus", fetch=False) == 2  # type: ignore[arg-type]


def test_reset_parser_wiring(git_repo: Path) -> None:
    _make_feature_with_extra_commit(git_repo)
    assert main(["reset", "--soft", "--no-fetch"]) == 0
    with pytest.raises(SystemExit):
        main(["reset", "--soft", "--hard"])
