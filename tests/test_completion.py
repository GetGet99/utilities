"""Tests for shell completion (`--print-completion`) + branch listers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import git as gitops
from utilities.cli_mr import main as mr_main
from utilities.cli_mr_diff import main as mr_diff_main
from utilities.completion import (
    COMPLETION_SHELLS,
    handle_print_completion,
    render_completion,
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def test_render_mr_zsh_has_subcommands_and_branch_helper() -> None:
    script = render_completion("mr", "zsh")
    assert script.startswith("#compdef mr")
    for command in ("new", "base", "rebase", "reset", "merge", "publish", "config"):
        assert command in script
    assert "--onto" in script
    assert "--no-fetch" in script
    assert "git branch" in script
    assert "merge.strategy" in script
    assert "compdef _mr mr" in script


def test_render_mr_bash_registers_completion() -> None:
    script = render_completion("mr", "bash")
    assert "complete -F _mr_completion mr" in script
    assert "COMPREPLY" in script
    assert "git branch" in script
    assert "--onto" in script
    assert "merge.push" in script


def test_render_mr_diff_covers_list_and_review_files() -> None:
    for shell in COMPLETION_SHELLS:
        script = render_completion("mr-diff", shell)
        assert "list" in script
        assert "--name-only" in script
        assert "mr-diff list --name-only" in script
        assert "ls-files" in script


def test_render_rejects_unknown_shell_and_program() -> None:
    with pytest.raises(ValueError):
        render_completion("mr", "fish")
    with pytest.raises(ValueError):
        render_completion("mrx", "zsh")


def test_handle_print_completion_absent_returns_none() -> None:
    assert handle_print_completion("mr", ["new", "foo"]) is None
    assert handle_print_completion("mr", []) is None


def test_handle_print_completion_bad_shell() -> None:
    assert handle_print_completion("mr", ["--print-completion", "fish"]) == 2


def test_handle_print_completion_missing_value() -> None:
    assert handle_print_completion("mr", ["--print-completion"]) == 2
    assert handle_print_completion("mr", ["--print-completion="]) == 2


def test_handle_print_completion_equals_form(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_print_completion("mr", ["--print-completion=zsh"]) == 0
    assert "#compdef mr" in capsys.readouterr().out


def test_handle_print_completion_only_honors_first_arg(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Must not hijack real subcommands that happen to mention the flag text.
    assert handle_print_completion("mr", ["new", "x", "--print-completion"]) is None
    assert capsys.readouterr().out == ""


def test_main_print_completion_roundtrip(capsys: pytest.CaptureFixture[str]) -> None:
    assert mr_main(["--print-completion", "zsh"]) == 0
    assert "#compdef mr" in capsys.readouterr().out
    assert mr_main(["--print-completion", "bash"]) == 0
    assert "complete -F _mr_completion mr" in capsys.readouterr().out
    assert mr_diff_main(["--print-completion", "zsh"]) == 0
    assert "#compdef mr-diff" in capsys.readouterr().out
    assert mr_main(["--print-completion", "fish"]) == 2


def test_list_local_branches(git_repo: Path) -> None:
    _git(["branch", "feat/foo"], git_repo)
    names = gitops.list_local_branches(git_repo)
    assert "main" in names
    assert "feat/foo" in names
    assert names == sorted(names)


def test_list_remote_branches_includes_pushed_branch(git_repo: Path) -> None:
    _git(["branch", "feature-x"], git_repo)
    _git(["push", "origin", "feature-x"], git_repo)
    names = gitops.list_remote_branches(git_repo)
    assert "origin/main" in names
    assert "origin/feature-x" in names
    assert all(" -> " not in name for name in names)


def test_list_completion_refs_merges_both(git_repo: Path) -> None:
    _git(["branch", "feat/foo"], git_repo)
    refs = gitops.list_completion_refs(git_repo)
    assert "main" in refs
    assert "feat/foo" in refs
    assert "origin/main" in refs


def test_listers_return_empty_outside_repo(tmp_path: Path) -> None:
    assert gitops.list_local_branches(tmp_path) == []
    assert gitops.list_remote_branches(tmp_path) == []
    assert gitops.list_completion_refs(tmp_path) == []
