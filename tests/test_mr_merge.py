"""Tests for `mr merge` + `mr config`."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from utilities import base_store, config_store
from utilities import git as gitops
from utilities.cli_mr import cmd_config_reset, cmd_config_set, cmd_merge, main


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _commit(path: Path, filename: str, content: str, subject: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", subject], path)


def _add_base_worktree(repo: Path, tmp_path: Path, branch: str = "main") -> Path:
    """Add a linked worktree owning *branch* (caller must not be on *branch*)."""
    wt = tmp_path / f"wt-{branch}"
    _git(["worktree", "add", str(wt), branch], repo)
    return wt


def _feature_with_base(
    repo: Path, tmp_path: Path, *, base: str = "main", subjects: list[str] | None = None
) -> Path:
    """Checkout a feature branch with commits; then attach a base worktree.

    Returns the base worktree path. The feature branch's base is recorded
    without re-validating (mirrors `mr new` bookkeeping).
    """
    _git(["checkout", "-b", "feature"], repo)
    for i, subject in enumerate(subjects if subjects is not None else ["feat commit"]):
        _commit(repo, f"feat{i}.txt", f"{subject}\n", subject)
    local = (
        base.split("/", 1)[1]
        if "/" in base and base.split("/", 1)[0] in (_out(["remote"], repo).split())
        else base
    )
    base_wt = _add_base_worktree(repo, tmp_path, local)
    base_store.set_base_after_create(base, repo)
    return base_wt


def test_merge_squash_happy_path(git_repo: Path, tmp_path: Path) -> None:
    base_wt = _feature_with_base(git_repo, tmp_path, base="main")

    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 0

    assert (base_wt / "feat0.txt").exists()
    assert (git_repo / "feat0.txt").exists()
    assert _out(["rev-parse", "main"], git_repo) == _out(["rev-parse", "feature"], git_repo)
    assert _out(["rev-parse", "main"], base_wt) == _out(["rev-parse", "feature"], git_repo)
    assert _out(["log", "--format=%s", "-n", "1", "main"], base_wt) == "feat commit"


def test_merge_blocks_when_on_base(git_repo: Path) -> None:
    assert base_store.set_base("main", git_repo, fetch=False) == "main"
    assert _out(["branch", "--show-current"], git_repo) == "main"
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 2


def test_merge_nothing_to_merge(git_repo: Path, tmp_path: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    _add_base_worktree(git_repo, tmp_path, "main")
    base_store.set_base_after_create("main", git_repo)
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 0
    assert _out(["rev-parse", "main"], git_repo) == _out(["rev-parse", "feature"], git_repo)


def test_merge_blocks_dirty_current(git_repo: Path, tmp_path: Path) -> None:
    _feature_with_base(git_repo, tmp_path, base="main")
    (git_repo / "feat0.txt").write_text("dirty\n", encoding="utf-8")
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 2


def test_merge_blocks_dirty_base(git_repo: Path, tmp_path: Path) -> None:
    base_wt = _feature_with_base(git_repo, tmp_path, base="main")
    (base_wt / "README.md").write_text("dirty base\n", encoding="utf-8")
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 2


def test_merge_blocks_when_no_owner(git_repo: Path) -> None:
    _git(["branch", "alt", "main"], git_repo)
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "feat.txt", "feat\n", "feat commit")
    base_store.set_base_after_create("alt", git_repo)
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 2


def test_merge_no_ff_preserves_history(git_repo: Path, tmp_path: Path) -> None:
    base_wt = _feature_with_base(git_repo, tmp_path, base="main")
    assert cmd_merge(message=None, strategy="merge", push=False, fetch=False) == 0
    parents = _out(["rev-list", "--parents", "-n", "1", "main"], base_wt).split()
    assert len(parents) == 3  # merge commit + 2 parents


def test_merge_default_message_multi_commit(git_repo: Path, tmp_path: Path) -> None:
    base_wt = _feature_with_base(
        git_repo, tmp_path, base="main", subjects=["first subject", "second subject"]
    )
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 0
    body = _out(["log", "--format=%B", "-n", "1", "main"], base_wt)
    assert "first subject" in body
    assert "second subject" in body


def test_merge_remote_base_pushes(git_repo: Path, tmp_path: Path) -> None:
    base_wt = _feature_with_base(git_repo, tmp_path, base="origin/main")
    assert cmd_merge(message="ship it", strategy="squash", push=None, fetch=True) == 0
    assert (base_wt / "feat0.txt").exists()
    assert _out(["rev-parse", "main"], git_repo) == _out(["rev-parse", "origin/main"], git_repo)


def test_merge_local_base_does_not_push(git_repo: Path, tmp_path: Path) -> None:
    _feature_with_base(git_repo, tmp_path, base="main")
    assert cmd_merge(message=None, strategy="squash", push=None, fetch=False) == 0
    # origin/main must still point at the initial commit (no push happened).
    assert _out(["rev-parse", "origin/main"], git_repo) != _out(["rev-parse", "main"], git_repo)


def test_merge_fetch_failure_hard_fails(git_repo: Path, tmp_path: Path) -> None:
    _git(["remote", "add", "bad", "/nonexistent/path.git"], git_repo)
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "feat.txt", "feat\n", "feat commit")
    base_store.set_base_after_create("bad/main", git_repo)
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=True) == 2


def test_merge_detached_head(git_repo: Path) -> None:
    _git(["checkout", "--detach", "HEAD"], git_repo)
    assert gitops.current_branch(git_repo) is None
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 2


def test_merge_mid_rebase_blocks(git_repo: Path, tmp_path: Path) -> None:
    _feature_with_base(git_repo, tmp_path, base="main")
    # Fake a mid-rebase state in the current worktree.
    (gitops.git_dir(git_repo) / "REBASE_MERGE").mkdir(exist_ok=True)
    try:
        assert cmd_merge(message=None, strategy="squash", push=False, fetch=False) == 2
    finally:
        shutil.rmtree(gitops.git_dir(git_repo) / "REBASE_MERGE", ignore_errors=True)


def test_merge_diverged_aborts(git_repo: Path, tmp_path: Path) -> None:
    origin = _out(["remote", "get-url", "origin"], git_repo)
    base_wt = _feature_with_base(git_repo, tmp_path, base="origin/main")
    # Local main moves ahead (unpushed).
    _commit(base_wt, "local.txt", "local\n", "local ahead")
    # Origin moves ahead too, from a separate clone.
    clone = tmp_path / "clone2"
    subprocess.run(["git", "clone", origin, str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.c"], cwd=str(clone), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone), check=True)
    (clone / "remote.txt").write_text("r\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(clone), check=True)
    subprocess.run(["git", "commit", "-m", "remote ahead"], cwd=str(clone), check=True)
    subprocess.run(
        ["git", "push", "origin", "main"], cwd=str(clone), check=True, capture_output=True
    )
    before = _out(["rev-parse", "main"], base_wt)
    assert cmd_merge(message=None, strategy="squash", push=False, fetch=True) == 2
    # Base worktree untouched by the aborted merge.
    assert _out(["rev-parse", "main"], base_wt) == before
    assert not (base_wt / "feat0.txt").exists()


def test_merge_strategy_from_config(git_repo: Path, tmp_path: Path) -> None:
    base_wt = _feature_with_base(git_repo, tmp_path, base="main")
    assert cmd_config_set("merge.strategy", "merge") == 0
    assert cmd_merge(message=None, strategy=None, push=False, fetch=False) == 0
    parents = _out(["rev-list", "--parents", "-n", "1", "main"], base_wt).split()
    assert len(parents) == 3


def test_config_set_rejects_bad_values() -> None:
    assert cmd_config_set("nope.key", "x") == 2
    assert cmd_config_set("merge.strategy", "rebase") == 2
    assert cmd_config_set("merge.push", "sometimes") == 2


def test_config_roundtrip(capsys: pytest.CaptureFixture[str]) -> None:
    assert config_store.get_merge_strategy() == "squash"
    assert config_store.get_merge_push() == "auto"
    assert cmd_config_set("merge.push", "never") == 0
    assert config_store.get_merge_push() == "never"
    assert cmd_config_reset("merge.push") == 0
    assert config_store.get_merge_push() == "auto"
    assert cmd_config_set("merge.strategy", "merge") == 0
    assert cmd_config_reset(None) == 0
    assert config_store.read_config() == {}
    capsys.readouterr()


def test_config_parser_wiring(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "set", "merge.push", "never"]) == 0
    capsys.readouterr()
    assert main(["config", "list"]) == 0
    assert "merge.push=never" in capsys.readouterr().out
    assert main(["config", "reset", "merge.push"]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["merge", "--help"])
    assert exc.value.code == 0
