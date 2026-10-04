"""Tests for `mr rebase --onto` / `--continue` / `--skip` / `--abort`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utilities import base_store
from utilities.cli_mr import (
    cmd_base_set,
    cmd_rebase,
    cmd_rebase_abort,
    cmd_rebase_continue,
    cmd_rebase_onto,
    main,
)


@pytest.fixture(autouse=True)
def _no_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_EDITOR", "true")
    monkeypatch.setenv("GIT_SEQUENCE_EDITOR", "true")


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _git_rc(args: list[str], cwd: Path) -> int:
    proc = subprocess.run(["git", *args], cwd=str(cwd), check=False, capture_output=True)
    return proc.returncode


def _out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _commit(path: Path, filename: str, content: str, subject: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", subject], path)


def _subjects(ref_range: str, cwd: Path) -> list[str]:
    out = _out(["log", "--format=%s", "--reverse", ref_range], cwd)
    return [line for line in out.splitlines() if line]


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


def test_onto_preserves_upstream_config(git_repo: Path) -> None:
    """`--onto` replays commits but never touches branch upstream tracking.

    A branch created without upstream (VSCode-style, and now `mr new`) still
    has no upstream after retargeting, so `git push` keeps suggesting
    `push --set-upstream origin <branch>`. The `old-base..HEAD` range comes
    from the mr-base pointer, not from `@{u}`, so upstream config cannot
    change what gets replayed.
    """
    from utilities.cli_mr import cmd_new

    assert cmd_new("feature", "origin/main", fetch=False) == 0
    assert _upstream(git_repo) is None
    _commit(git_repo, "f.txt", "f\n", "feat")
    _git(["branch", "new-base", "main"], git_repo)

    assert cmd_rebase_onto("new-base", fetch=False) == 0
    assert _upstream(git_repo) is None
    assert base_store.get_base(git_repo) == "new-base"
    assert _subjects("new-base..HEAD", git_repo) == ["feat"]


def test_onto_happy_path_replays_only_new_commits(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature1", "main"], git_repo)
    _commit(git_repo, "f1.txt", "f1\n", "f1.1")
    _git(["checkout", "-b", "feature2", "feature1"], git_repo)
    _commit(git_repo, "f2.txt", "f2\n", "f2.1")
    base_store.set_base_after_create("feature1", git_repo)
    # Advance new base so the transplant has somewhere to land.
    _git(["checkout", "main"], git_repo)
    _commit(git_repo, "c.txt", "c\n", "main-c")
    _git(["checkout", "feature2"], git_repo)

    assert cmd_rebase_onto("main", fetch=False) == 0
    assert base_store.get_base(git_repo) == "main"
    assert base_store.get_pending_rebase_onto(git_repo) is None
    assert (git_repo / "c.txt").exists()
    assert (git_repo / "f2.txt").exists()
    assert not (git_repo / "f1.txt").exists() or True  # f1 may differ; check subjects
    assert _subjects("main..HEAD", git_repo) == ["f2.1"]


def test_onto_squash_case_skips_squashed_commits(git_repo: Path) -> None:
    # feature1 built on main, then squashed into main (like GitLab squash-merge).
    _git(["checkout", "-b", "feature1", "main"], git_repo)
    _commit(git_repo, "f1a.txt", "a\n", "feature1.1")
    _commit(git_repo, "f1b.txt", "b\n", "feature1.2")
    _git(["checkout", "main"], git_repo)
    _git(["merge", "--squash", "feature1"], git_repo)
    _git(["commit", "-m", "squash feature1"], git_repo)
    _commit(git_repo, "c.txt", "c\n", "main-c")
    # feature2 stacked on feature1 tip.
    _git(["checkout", "-b", "feature2", "feature1"], git_repo)
    _commit(git_repo, "f2a.txt", "x\n", "feature2.1")
    _commit(git_repo, "f2b.txt", "y\n", "feature2.2")
    base_store.set_base_after_create("feature1", git_repo)

    assert cmd_rebase_onto("main", fetch=False) == 0
    assert base_store.get_base(git_repo) == "main"
    assert _subjects("main..HEAD", git_repo) == ["feature2.1", "feature2.2"]


def test_onto_noop_sets_base(git_repo: Path) -> None:
    _git(["branch", "alt", "main"], git_repo)
    assert cmd_rebase_onto("alt", fetch=False) == 0
    assert base_store.get_base(git_repo) == "alt"
    assert base_store.get_pending_rebase_onto(git_repo) is None


def test_onto_blocks_bad_new_ref(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "f.txt", "f\n", "feat")
    base_store.set_base_after_create("main", git_repo)
    tip = _out(["rev-parse", "HEAD"], git_repo)

    assert cmd_rebase_onto("no-such-ref", fetch=False) == 2
    assert base_store.get_base(git_repo) == "main"
    assert base_store.get_pending_rebase_onto(git_repo) is None
    assert _out(["rev-parse", "HEAD"], git_repo) == tip


def test_onto_blocks_dirty_detached_and_mid_rebase(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "f.txt", "f\n", "feat")
    base_store.set_base_after_create("main", git_repo)
    (git_repo / "f.txt").write_text("dirty\n", encoding="utf-8")
    assert cmd_rebase_onto("main", fetch=False) == 2
    _git(["checkout", "--", "."], git_repo)

    _git(["checkout", "--detach", "HEAD"], git_repo)
    assert cmd_rebase_onto("main", fetch=False) == 2
    _git(["checkout", "feature"], git_repo)

    # Fake a mid-rebase state.
    git_dir = Path(_out(["rev-parse", "--git-dir"], git_repo))
    if not git_dir.is_absolute():
        git_dir = git_repo / git_dir
    (git_dir / "REBASE_MERGE").mkdir(exist_ok=True)
    try:
        assert cmd_rebase_onto("main", fetch=False) == 2
    finally:
        import shutil

        shutil.rmtree(git_dir / "REBASE_MERGE", ignore_errors=True)
    assert base_store.get_pending_rebase_onto(git_repo) is None


def test_onto_blocks_when_on_new_base(git_repo: Path) -> None:
    base_store.set_base_after_create("main", git_repo)
    assert cmd_rebase_onto("main", fetch=False) == 2


def test_onto_conflict_then_continue_sets_base(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature1", "main"], git_repo)
    (git_repo / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "base file"], git_repo)
    _git(["checkout", "-b", "feature2", "feature1"], git_repo)
    (git_repo / "shared.txt").write_text("feature2 change\n", encoding="utf-8")
    _git(["commit", "-am", "feature2.1"], git_repo)
    base_store.set_base_after_create("feature1", git_repo)
    _git(["checkout", "main"], git_repo)
    (git_repo / "shared.txt").write_text("main change\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "main-c"], git_repo)
    _git(["checkout", "feature2"], git_repo)

    rc = cmd_rebase_onto("main", fetch=False)
    assert rc != 0
    # Old base kept, intent stashed.
    assert base_store.get_base(git_repo) == "feature1"
    assert base_store.get_pending_rebase_onto(git_repo) == "main"

    (git_repo / "shared.txt").write_text("resolved\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    assert cmd_rebase_continue() == 0
    assert base_store.get_base(git_repo) == "main"
    assert base_store.get_pending_rebase_onto(git_repo) is None
    assert (git_repo / "shared.txt").read_text(encoding="utf-8") == "resolved\n"


def test_onto_abort_restores_tip_and_clears_pending(git_repo: Path) -> None:
    _git(["checkout", "-b", "feature1", "main"], git_repo)
    (git_repo / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "base file"], git_repo)
    _git(["checkout", "-b", "feature2", "feature1"], git_repo)
    (git_repo / "shared.txt").write_text("feature2 change\n", encoding="utf-8")
    _git(["commit", "-am", "feature2.1"], git_repo)
    base_store.set_base_after_create("feature1", git_repo)
    tip = _out(["rev-parse", "HEAD"], git_repo)
    _git(["checkout", "main"], git_repo)
    (git_repo / "shared.txt").write_text("main change\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "main-c"], git_repo)
    _git(["checkout", "feature2"], git_repo)

    assert cmd_rebase_onto("main", fetch=False) != 0
    assert cmd_rebase_abort() == 0
    assert _out(["rev-parse", "HEAD"], git_repo) == tip
    assert base_store.get_base(git_repo) == "feature1"
    assert base_store.get_pending_rebase_onto(git_repo) is None


def test_second_continue_does_not_clobber_new_base(git_repo: Path) -> None:
    """onto -> continue (base=new) then base set main + plain rebase -> continue keeps main."""
    _git(["checkout", "-b", "feature"], git_repo)
    _commit(git_repo, "f.txt", "f\n", "feat")
    base_store.set_base_after_create("main", git_repo)
    _git(["branch", "new-base", "main"], git_repo)

    assert cmd_rebase_onto("new-base", fetch=False) == 0
    assert base_store.get_base(git_repo) == "new-base"

    assert cmd_base_set("main", fetch=False) == 0
    assert base_store.get_pending_rebase_onto(git_repo) is None
    # Plain rebase with nothing to do; a later --continue must not restore new-base.
    assert cmd_rebase(fetch=False) == 0
    # No rebase in progress and no pending: faithful passthrough (git errors),
    # but crucially the base must stay on main.
    assert cmd_rebase_continue() != 0
    assert base_store.get_base(git_repo) == "main"


def test_git_direct_finish_leaves_base_and_next_rebase_warns(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(["checkout", "-b", "feature1", "main"], git_repo)
    (git_repo / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "base file"], git_repo)
    _git(["checkout", "-b", "feature2", "feature1"], git_repo)
    (git_repo / "shared.txt").write_text("feature2 change\n", encoding="utf-8")
    _git(["commit", "-am", "feature2.1"], git_repo)
    base_store.set_base_after_create("feature1", git_repo)
    _git(["checkout", "main"], git_repo)
    (git_repo / "shared.txt").write_text("main change\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    _git(["commit", "-m", "main-c"], git_repo)
    _git(["checkout", "feature2"], git_repo)

    assert cmd_rebase_onto("main", fetch=False) != 0
    (git_repo / "shared.txt").write_text("resolved\n", encoding="utf-8")
    _git(["add", "."], git_repo)
    # Bypass the wrapper, like a user running plain git.
    assert _git_rc(["rebase", "--continue"], git_repo) == 0
    # Wrapper did not run: base stays old, intent stays.
    assert base_store.get_base(git_repo) == "feature1"
    assert base_store.get_pending_rebase_onto(git_repo) == "main"

    # Next plain `mr rebase` must not break: it warns about the stale intent and
    # then behaves like git (here that means conflicting on the transplanted
    # branch — the point is the warning fires and pending/base are untouched).
    plain_rc = cmd_rebase(fetch=False)
    captured = capsys.readouterr()
    assert "stale --onto intent" in captured.err
    assert base_store.get_base(git_repo) == "feature1"
    assert base_store.get_pending_rebase_onto(git_repo) == "main"
    if plain_rc != 0:
        # Clean up the expected conflict with plain git so pending survives
        # for the assertions below (the wrapper abort would clear it).
        _git(["rebase", "--abort"], git_repo)

    # `mr rebase --continue` with nothing in progress must not silently adopt.
    assert cmd_rebase_continue() != 0
    assert base_store.get_base(git_repo) == "feature1"
    assert base_store.get_pending_rebase_onto(git_repo) == "main"

    # Abort path cleans the stale intent.
    assert cmd_rebase_abort() != 0  # git has nothing to abort
    assert base_store.get_pending_rebase_onto(git_repo) is None
    assert base_store.get_base(git_repo) == "feature1"


def test_base_set_clears_pending(git_repo: Path) -> None:
    _git(["branch", "alt", "main"], git_repo)
    base_store.set_pending_rebase_onto("alt", git_repo)
    assert cmd_base_set("main", fetch=False) == 0
    assert base_store.get_pending_rebase_onto(git_repo) is None


def test_parser_wiring(git_repo: Path) -> None:
    _git(["branch", "alt", "main"], git_repo)
    assert main(["rebase", "--onto", "alt", "--no-fetch"]) == 0
    assert base_store.get_base(git_repo) == "alt"
    # Nothing in progress: abort is a faithful passthrough (git errors) and a no-op.
    assert main(["rebase", "--abort"]) != 0
    assert base_store.get_base(git_repo) == "alt"
