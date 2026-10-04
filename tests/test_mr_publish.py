"""Tests for `mr publish` (push + `glab mr create`)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from utilities import base_store, cli_mr
from utilities import git as gitops
from utilities.cli_mr import cmd_publish, main


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _ref_exists(ref: str, cwd: Path) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _commit(path: Path, filename: str, content: str, subject: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", subject], path)


def _make_fake_glab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a fake `glab` on PATH that logs argv (one line per call)."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "glab-args.log"
    if log.exists():
        log.unlink()
    script = bindir / "glab"
    script.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexit 0\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    return log


def _feature(repo: Path, branch: str = "feature") -> None:
    _git(["checkout", "-b", branch], repo)
    _commit(repo, "feat.txt", "feat\n", "feat commit")
    base_store.set_base_after_create("origin/main", repo)


def _glab_log(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def _publish_kwargs(**overrides):  # type: ignore[no-untyped-def]
    kwargs = {
        "fetch": False,
        "push": True,
        "fill": False,
        "yes": False,
        "draft": False,
        "title": None,
        "description": None,
        "labels": None,
        "assignees": None,
        "reviewers": None,
        "remove_source_branch": False,
        "extra": None,
    }
    kwargs.update(overrides)
    return kwargs


def test_publish_pushes_new_branch_and_strips_remote(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    assert not _ref_exists("refs/remotes/origin/feature", git_repo)

    assert cmd_publish(**_publish_kwargs()) == 0

    assert _ref_exists("refs/remotes/origin/feature", git_repo)
    assert gitops.upstream_ref(git_repo) == "origin/feature"
    calls = _glab_log(log)
    assert len(calls) == 1
    assert "--target-branch main" in calls[0]
    assert "origin/main" not in calls[0]


def test_publish_skips_push_when_in_sync(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    assert cmd_publish(**_publish_kwargs()) == 0
    capsys.readouterr()
    assert cmd_publish(**_publish_kwargs()) == 0
    out = capsys.readouterr().out
    assert "already pushed" in out
    assert len(_glab_log(log)) == 2


def test_publish_pushes_ahead_commits(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    assert cmd_publish(**_publish_kwargs()) == 0
    before = _out(["rev-parse", "refs/remotes/origin/feature"], git_repo)
    _commit(git_repo, "feat2.txt", "more\n", "second commit")
    assert cmd_publish(**_publish_kwargs()) == 0
    after = _out(["rev-parse", "refs/remotes/origin/feature"], git_repo)
    assert before != after
    assert len(_glab_log(log)) == 2


def test_publish_no_push_skips_git_push(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    assert cmd_publish(**_publish_kwargs(push=False)) == 0
    assert not _ref_exists("refs/remotes/origin/feature", git_repo)
    assert len(_glab_log(log)) == 1


def test_publish_fails_when_base_not_remote(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "feat.txt", "feat\n", "feat commit")
    base_store.set_base_after_create("main", git_repo)
    assert cmd_publish(**_publish_kwargs()) == 2
    assert _glab_log(log) == []


def test_publish_fails_when_on_base(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    base_store.set_base_after_create("origin/main", git_repo)
    assert gitops.current_branch(git_repo) == "main"
    assert cmd_publish(**_publish_kwargs()) == 2
    assert _glab_log(log) == []


def test_publish_blocks_dirty_tree(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    (git_repo / "feat.txt").write_text("dirty\n", encoding="utf-8")
    assert cmd_publish(**_publish_kwargs()) == 2
    assert _glab_log(log) == []


def test_publish_blocks_detached_head(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    _git(["checkout", "--detach", "HEAD"], git_repo)
    assert cmd_publish(**_publish_kwargs()) == 2
    assert _glab_log(log) == []


def test_publish_missing_glab(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _feature(git_repo)
    monkeypatch.setattr(cli_mr.glabops, "find_glab", lambda: None)
    assert cmd_publish(**_publish_kwargs(push=False)) == 2
    err = capsys.readouterr().err
    assert "glab not found" in err


def test_publish_fetch_failure_hard_fails(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _git(["remote", "add", "bad", "/nonexistent/path.git"], git_repo)
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "feat.txt", "feat\n", "feat commit")
    base_store.set_base_after_create("bad/main", git_repo)
    assert cmd_publish(**_publish_kwargs(fetch=True, push=False)) == 2
    assert _glab_log(log) == []


def test_publish_forwards_flags_and_extra(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    assert (
        cmd_publish(
            **_publish_kwargs(
                push=False,
                fill=True,
                yes=True,
                draft=True,
                title="T",
                description="D",
                labels=["bug", "ui"],
                assignees=["alice"],
                reviewers=["bob"],
                remove_source_branch=True,
                extra=["--", "--reviewer", "carol"],
            )
        )
        == 0
    )
    calls = _glab_log(log)
    assert len(calls) == 1
    argv = calls[0]
    for flag in (
        "--fill",
        "--yes",
        "--draft",
        "--title T",
        "--description D",
        "--label bug",
        "--label ui",
        "--assignee alice",
        "--reviewer bob",
        "--reviewer carol",
        "--remove-source-branch",
    ):
        assert flag in argv


def test_publish_parser_wiring(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _make_fake_glab(tmp_path, monkeypatch)
    _feature(git_repo)
    assert (
        main(
            [
                "publish",
                "--no-fetch",
                "--no-push",
                "--fill",
                "--yes",
                "--draft",
                "--title",
                "T",
                "--remove-source-branch",
            ]
        )
        == 0
    )
    capsys.readouterr()
    calls = _glab_log(log)
    assert len(calls) == 1
    assert "--target-branch main" in calls[0]
    assert "--fill" in calls[0]
    # --no-push means the branch was never pushed to origin.
    assert not _ref_exists("refs/remotes/origin/feature", git_repo)
