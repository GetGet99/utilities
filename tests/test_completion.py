"""Tests for shell completion (`--print-completion`, `completion install`)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import git as gitops
from utilities.cli_mr import main as mr_main
from utilities.cli_mr_diff import main as mr_diff_main
from utilities.completion import (
    COMPLETION_BLOCK_BEGIN,
    COMPLETION_BLOCK_END,
    COMPLETION_SHELLS,
    completion_status,
    detect_shell,
    handle_print_completion,
    install_completion,
    rc_block,
    rc_file,
    render_completion,
    uninstall_completion,
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def test_render_mr_zsh_has_subcommands_and_branch_helper() -> None:
    script = render_completion("mr", "zsh")
    assert script.startswith("#compdef mr")
    for command in (
        "new",
        "base",
        "rebase",
        "reset",
        "squash",
        "merge",
        "publish",
        "config",
        "completion",
    ):
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
    assert "squash" in script
    assert "--message" in script


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


def test_scripts_load_from_package_data() -> None:
    """Every (prog, shell) combo loads a non-empty script ending in newline."""
    from importlib import resources

    for prog in ("mr", "mr-diff"):
        for shell in COMPLETION_SHELLS:
            ref = resources.files("utilities").joinpath(f"completions/{prog}.{shell}")
            assert ref.is_file(), f"missing package data: completions/{prog}.{shell}"
            text = ref.read_text(encoding="utf-8")
            assert text.strip(), f"empty package data: completions/{prog}.{shell}"
            assert text.endswith("\n")
            assert render_completion(prog, shell) == text


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


def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME (and away ZDOTDIR) at a temp dir for rc-file tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ZDOTDIR", raising=False)
    return home


def test_rc_block_covers_both_progs() -> None:
    block = rc_block("zsh")
    assert block.startswith(COMPLETION_BLOCK_BEGIN + "\n")
    assert block.endswith(COMPLETION_BLOCK_END + "\n")
    assert 'eval "$(mr --print-completion zsh)"' in block
    assert 'eval "$(mr-diff --print-completion zsh)"' in block
    with pytest.raises(ValueError):
        rc_block("fish")


def test_rc_file_paths_and_zdotdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    assert rc_file("zsh") == home / ".zshrc"
    assert rc_file("bash") == home / ".bashrc"
    monkeypatch.setenv("ZDOTDIR", str(home / "zdot"))
    assert rc_file("zsh") == home / "zdot" / ".zshrc"
    # bash ignores ZDOTDIR.
    assert rc_file("bash") == home / ".bashrc"
    with pytest.raises(ValueError):
        rc_file("fish")


def test_detect_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert detect_shell() == "zsh"
    monkeypatch.setenv("SHELL", "/usr/local/bin/bash")
    assert detect_shell() == "bash"
    monkeypatch.setenv("SHELL", "/bin/fish")
    assert detect_shell() is None
    monkeypatch.delenv("SHELL", raising=False)
    assert detect_shell() is None


def test_install_creates_rc_with_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    assert install_completion(["zsh"]) == 0
    text = (home / ".zshrc").read_text(encoding="utf-8")
    assert rc_block("zsh") in text


def test_install_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    assert install_completion(["zsh"]) == 0
    first = (home / ".zshrc").read_text(encoding="utf-8")
    assert install_completion(["zsh"]) == 0
    assert "already installed" in capsys.readouterr().out
    assert (home / ".zshrc").read_text(encoding="utf-8") == first


def test_install_adopts_bare_eval_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    rc = home / ".zshrc"
    rc.write_text('# my config\neval "$(mr --print-completion zsh)"\n', encoding="utf-8")
    assert install_completion(["zsh"]) == 0
    text = rc.read_text(encoding="utf-8")
    assert text.count('eval "$(mr --print-completion zsh)"') == 1
    assert COMPLETION_BLOCK_BEGIN in text
    assert "# my config" in text


def test_install_replaces_stale_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    rc = home / ".zshrc"
    rc.write_text(
        f"{COMPLETION_BLOCK_BEGIN}\n# ancient\n{COMPLETION_BLOCK_END}\n",
        encoding="utf-8",
    )
    assert install_completion(["zsh"]) == 0
    text = rc.read_text(encoding="utf-8")
    assert "# ancient" not in text
    assert rc_block("zsh") in text
    assert text.count(COMPLETION_BLOCK_BEGIN) == 1


def test_install_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    assert install_completion(["zsh"], dry_run=True) == 0
    assert not (home / ".zshrc").exists()


def test_uninstall_removes_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    rc = home / ".zshrc"
    rc.write_text("# keep me\n", encoding="utf-8")
    assert install_completion(["zsh"]) == 0
    assert uninstall_completion(["zsh"]) == 0
    text = rc.read_text(encoding="utf-8")
    assert COMPLETION_BLOCK_BEGIN not in text
    assert "# keep me" in text
    # Backup was taken on a pre-existing file.
    assert (home / ".zshrc.bak").exists()


def test_uninstall_missing_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolated_home(tmp_path, monkeypatch)
    assert uninstall_completion(["zsh"]) == 0


def test_completion_status_reports_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolated_home(tmp_path, monkeypatch)
    assert completion_status(["zsh"]) == 0
    assert "zsh: missing" in capsys.readouterr().out
    assert install_completion(["zsh"]) == 0
    assert completion_status(["zsh"]) == 0
    assert "zsh: installed" in capsys.readouterr().out


def test_completion_status_detects_manual_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    (home / ".zshrc").write_text('eval "$(mr --print-completion zsh)"\n', encoding="utf-8")
    assert completion_status(["zsh"]) == 0
    assert "zsh: manual" in capsys.readouterr().out


def test_main_completion_install_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    assert mr_main(["completion", "install", "--shell", "zsh"]) == 0
    assert rc_block("zsh") in (home / ".zshrc").read_text(encoding="utf-8")
    assert mr_main(["completion", "status"]) == 0
    assert mr_main(["completion", "uninstall", "--shell", "zsh"]) == 0
    assert COMPLETION_BLOCK_BEGIN not in (home / ".zshrc").read_text(encoding="utf-8")


def test_main_completion_install_detects_current_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolated_home(tmp_path, monkeypatch)
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert mr_main(["completion", "install"]) == 0
    assert rc_block("bash") in (home / ".bashrc").read_text(encoding="utf-8")


def test_main_completion_install_unknown_shell_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_home(tmp_path, monkeypatch)
    monkeypatch.setenv("SHELL", "/bin/fish")
    assert mr_main(["completion", "install"]) == 2
