"""Tests for `mr squash` (squash branch commits into a single commit)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from utilities import base_store
from utilities import git as gitops
from utilities.cli_mr import _ask_squash_message, cmd_base_set, cmd_squash, main


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _commit(path: Path, filename: str, content: str, subject: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", subject], path)


def _commit_with_body(path: Path, filename: str, content: str, message: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", message], path)


def _feature_with_commits(git_repo: Path, subjects: list[str]) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    for i, subject in enumerate(subjects):
        _commit(git_repo, f"feat{i}.txt", f"{subject}\n", subject)
    assert cmd_base_set("main", fetch=False) == 0


def test_squash_keeps_last_message(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["first", "second", "third"])
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["rev-list", "--count", "main..HEAD"], git_repo) == "1"
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "third"
    assert (git_repo / "feat0.txt").exists()
    assert (git_repo / "feat1.txt").exists()
    assert (git_repo / "feat2.txt").exists()


def test_squash_keeps_last_message_body(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "a.txt", "a\n", "first")
    _commit_with_body(git_repo, "b.txt", "b\n", "last subject\n\nlast body line")
    assert cmd_base_set("main", fetch=False) == 0
    assert cmd_squash(message=None, fetch=False) == 0
    body = _out(["log", "--format=%B", "-n", "1", "HEAD"], git_repo)
    assert "last subject" in body
    assert "last body line" in body
    assert "first" not in body


def test_squash_message_override(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["first", "second"])
    assert cmd_squash(message="custom msg", fetch=False) == 0
    assert _out(["rev-list", "--count", "main..HEAD"], git_repo) == "1"
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "custom msg"


def test_squash_single_commit_noop(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["only"])
    before = _out(["rev-parse", "HEAD"], git_repo)
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["rev-parse", "HEAD"], git_repo) == before
    assert _out(["rev-list", "--count", "main..HEAD"], git_repo) == "1"


def test_squash_single_commit_with_message_rewords(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["only"])
    assert cmd_squash(message="reworded", fetch=False) == 0
    assert _out(["rev-list", "--count", "main..HEAD"], git_repo) == "1"
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "reworded"


def test_squash_nothing_to_squash(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    base_store.set_base_after_create("main", git_repo)
    before = _out(["rev-parse", "HEAD"], git_repo)
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["rev-parse", "HEAD"], git_repo) == before


def test_squash_blocks_dirty_worktree(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["first", "second"])
    (git_repo / "feat0.txt").write_text("dirty\n", encoding="utf-8")
    before = _out(["rev-parse", "HEAD"], git_repo)
    assert cmd_squash(message=None, fetch=False) == 2
    assert _out(["rev-parse", "HEAD"], git_repo) == before


def test_squash_blocks_detached_head(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["first", "second"])
    _git(["checkout", "--detach", "HEAD"], git_repo)
    assert cmd_squash(message=None, fetch=False) == 2


def test_squash_blocks_mid_operation(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["first", "second"])
    (gitops.git_dir(git_repo) / "REBASE_MERGE").mkdir(exist_ok=True)
    try:
        assert cmd_squash(message=None, fetch=False) == 2
    finally:
        shutil.rmtree(gitops.git_dir(git_repo) / "REBASE_MERGE", ignore_errors=True)


def test_squash_blocks_bad_base(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "f.txt", "f\n", "feat")
    base_store.set_base_after_create("no-such-base", git_repo)
    assert cmd_squash(message=None, fetch=False) == 2


def test_squash_parser_wiring(git_repo: Path) -> None:
    _feature_with_commits(git_repo, ["first", "second"])
    assert main(["squash", "--no-fetch"]) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "second"
    assert main(["squash", "-m", "again", "--no-fetch"]) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "again"


def _tty(monkeypatch: object, reply: str | None, *, exc: object = None) -> None:
    import builtins
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)  # type: ignore[attr-defined]
    if exc is not None:

        def _raise(_prompt: str = "") -> str:
            raise exc  # type: ignore[misc]

        monkeypatch.setattr(builtins, "input", _raise)  # type: ignore[attr-defined]
    else:
        monkeypatch.setattr(builtins, "input", lambda _prompt="": reply)  # type: ignore[attr-defined]


def test_squash_interactive_custom_message(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _feature_with_commits(git_repo, ["first", "second"])
    _tty(monkeypatch, "typed message")
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "typed message"


def test_squash_interactive_empty_keeps_fallback(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _feature_with_commits(git_repo, ["first", "second"])
    _tty(monkeypatch, "")
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "second"


def test_squash_interactive_whitespace_keeps_fallback(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _feature_with_commits(git_repo, ["first", "second"])
    _tty(monkeypatch, "   ")
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "second"


def test_squash_interactive_eof_keeps_fallback(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _feature_with_commits(git_repo, ["first", "second"])
    _tty(monkeypatch, None, exc=EOFError())
    assert cmd_squash(message=None, fetch=False) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "second"


def test_squash_interactive_abort(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _feature_with_commits(git_repo, ["first", "second"])
    before = _out(["rev-parse", "HEAD"], git_repo)
    _tty(monkeypatch, None, exc=KeyboardInterrupt())
    assert cmd_squash(message=None, fetch=False) == 130
    assert _out(["rev-parse", "HEAD"], git_repo) == before
    assert _out(["rev-list", "--count", "main..HEAD"], git_repo) == "2"


def test_squash_explicit_message_never_prompts(git_repo: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import builtins
    import sys

    _feature_with_commits(git_repo, ["first", "second"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)  # type: ignore[attr-defined]

    def _fail(_prompt: str = "") -> str:
        raise AssertionError("must not prompt when -m is given")

    monkeypatch.setattr(builtins, "input", _fail)  # type: ignore[attr-defined]
    assert cmd_squash(message="explicit", fetch=False) == 0
    assert _out(["log", "--format=%s", "-n", "1", "HEAD"], git_repo) == "explicit"


def test_ask_non_interactive_returns_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)  # type: ignore[attr-defined]
    assert _ask_squash_message("fallback") == "fallback"
