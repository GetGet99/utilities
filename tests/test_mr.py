"""Tests for `mr new` / `mr base` (VSCode-parity + edge cases)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import base_store
from utilities.cli_mr import (
    cmd_base_default_reset,
    cmd_base_default_set,
    cmd_base_reset,
    cmd_base_set,
    cmd_new,
    cmd_rebase,
    main,
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _upstream(cwd: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    name = proc.stdout.strip()
    return name or None


def test_mr_new_from_remote_base_sets_no_upstream(git_repo: Path) -> None:
    """`mr new` from a remote base must not track the base (VSCode-style).

    Regression: `git checkout -b <branch> origin/main` auto-sets upstream to
    origin/main (branch.autoSetupMerge), so plain `git push` failed with an
    "upstream does not match" error suggesting `push origin HEAD:main` — which
    could push to the wrong branch. New branches must have no upstream so
    `git push` suggests `push --set-upstream origin <branch>` instead.
    """
    assert cmd_new("feature-no-track", "origin/main", fetch=False) == 0
    assert _upstream(git_repo) is None


def test_mr_new_from_default_remote_base_sets_no_upstream(git_repo: Path) -> None:
    assert cmd_new("feature-default-no-track", None, fetch=False) == 0
    assert base_store.get_base(git_repo) == "origin/main"
    assert _upstream(git_repo) is None


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


def test_mr_rebase_replays_onto_updated_base(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    (git_repo / "feat.txt").write_text("feat\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "feat"], git_repo)
    _git(["checkout", "main"], git_repo)
    (git_repo / "main2.txt").write_text("main2\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "main2"], git_repo)
    _git(["checkout", "feature"], git_repo)
    assert cmd_base_set("main", fetch=False) == 0
    assert cmd_rebase(fetch=False) == 0
    assert (git_repo / "main2.txt").exists()
    assert (git_repo / "feat.txt").exists()


def test_mr_rebase_noop_on_clean_base(git_repo: Path) -> None:
    assert cmd_rebase(fetch=False) == 0
    assert gitops_current_branch(git_repo) == "main"


def test_mr_rebase_blocks_on_bad_base(git_repo: Path) -> None:
    base_store.set_base_after_create("no-such-base", git_repo)
    assert cmd_rebase(fetch=False) == 2


def test_mr_base_default_flow(git_repo: Path) -> None:
    assert base_store.get_effective_default(git_repo) == "origin/main"
    _git(["branch", "develop", "main"], git_repo)
    assert cmd_base_default_set("develop", fetch=False) == 0
    assert base_store.get_effective_default(git_repo) == "develop"
    # No per-worktree base yet: falls back to the custom default.
    assert base_store.get_base(git_repo) == "develop"
    # `mr new` without a base uses the custom default.
    assert cmd_new("f1", None, fetch=False) == 0
    assert base_store.get_base(git_repo) == "develop"
    # `mr base reset` returns to the custom default, not origin/main.
    _git(["branch", "other", "main"], git_repo)
    assert cmd_base_set("other", fetch=False) == 0
    assert base_store.get_base(git_repo) == "other"
    assert cmd_base_reset() == 0
    assert base_store.get_base(git_repo) == "develop"
    # Dropping the custom default restores origin/<default-branch>.
    assert cmd_base_default_reset() == 0
    assert base_store.get_effective_default(git_repo) == "origin/main"


def test_mr_base_default_set_rejects_bad_ref(git_repo: Path) -> None:
    assert cmd_base_default_set("no-such-ref", fetch=False) == 2
    assert base_store.get_custom_default(git_repo) is None


def test_mr_base_default_print_and_parser_wiring(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(["branch", "alt", "main"], git_repo)
    assert main(["base", "default", "set", "alt", "--no-fetch"]) == 0
    capsys.readouterr()
    assert main(["base", "default"]) == 0
    assert capsys.readouterr().out.strip() == "alt"
    assert main(["base", "default", "reset"]) == 0
    capsys.readouterr()
    assert main(["base", "default"]) == 0
    assert capsys.readouterr().out.strip() == "origin/main"
    assert main(["rebase", "--no-fetch"]) == 0
