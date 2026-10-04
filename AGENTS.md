# AGENTS.md — Contributor Contract for this repo

This repo is a monorepo of small personal CLI helpers (`mr`, `mr-diff`, …).
Agents and humans follow the same rules below.

## 1. Project map

```text
pyproject.toml          # single project, one [project.scripts] entry per CLI
src/utilities/
  git.py                # ALL git subprocess I/O (no git calls elsewhere)
  base_store.py         # per-worktree base pointer (shared by mr + mr-diff)
  cli_<name>.py         # ONE argparse CLI per file, with build_parser() + main()
tests/
  conftest.py           # tmp git repo + origin fixtures (use them, don't hand-roll)
  test_<name>.py
AGENTS.md               # this file
README.md               # user-facing usage
```

## 2. Hard constraints

- Python `>=3.9`. Always add `from __future__ import annotations` and avoid
  3.10+ runtime syntax (e.g. `match`, `X | Y` in evaluated positions).
  `tuple[str, str] | None` in annotations is OK because of the future import.
- Runtime dependencies: **stdlib only** (`argparse`, `subprocess`, `pathlib`, …).
  Dev tools (`pytest`, `ruff`, `mypy`) live in `[dependency-groups] dev`.
- No shell scripts for CLIs. All CLIs are Python modules with type annotations.
- All git access goes through `src/utilities/git.py` (`run_git` wrapper).
  Never call `subprocess` + `git` directly from a `cli_*.py`, except the
  pager-sensitive `git diff` exec already isolated in `git.exec_diff_patch`
  / `cli_mr_diff.cmd_file`.
- Base pointer: always use `base_store.get_base/set_base/reset_base`.
  Storage is `<worktree-git-dir>/mr-base` (per-worktree, no central JSON, no locks).
- Errors: `print(f"error: ...", file=sys.stderr)` + return `2` for usage/validation
  failures. Let git's own stderr through for checkout/rebase conflicts.

## 3. Adding a new CLI (recipe)

1. Create `src/utilities/cli_<name>.py` with:
   - `build_parser() -> argparse.ArgumentParser` (prog = CLI name),
   - `main(argv: Sequence[str] | None = None) -> int` + `sys.exit(main())` guard,
   - thin `cmd_*` functions returning exit codes (testable without subprocess mocks).
2. Register in `pyproject.toml` under `[project.scripts]`:
   `my-cli = "utilities.cli_<name>:main"`, then **re-run the install**
   (`uv pip install -e .` in `.venv`, or `pipx reinstall` / `uv tool install --editable .`
   for PATH installs). Pure `.py` edits in existing modules take effect
   immediately on editable installs, but new console-script launchers are only
   generated at install time — so a new CLI will not exist as a command until
   you reinstall.
3. Reuse helpers: `git.ensure_fresh_base()` for any remote-base fetch
   (fetch failure HARD-FAILS — never silently continue on stale refs),
   `git.parse_remote_ref()` for `remote/branch` detection (must check `git remote`
   list so `feat/foo` is NOT treated as remote `feat`).
4. Add `tests/test_<name>.py` using `git_repo` fixture from `conftest.py`.
   Cover: happy path, branch-exists / bad-ref blocks, per-worktree isolation if stateful.
5. Update `README.md` usage section.

## 4. fetch semantics (shared by `mr new`, future `mr rebase`)

- Only fetch when the base parses as `<known-remote>/<branch>` via
  `parse_remote_ref` (first-`/` split + membership in `git remote`).
- Fetch form: `git fetch <remote> <branch>` (narrow, not full fetch).
- `--no-fetch` flag on every command that calls `ensure_fresh_base`.
- Offline/fetch failure → hard error, exit non-zero.

## 5. `mr-diff` semantics

- GitLab-style = diff against `git merge-base <base> HEAD`, NOT literal `base...HEAD`,
  so staged + unstaged working-tree changes are included:
  `git diff <merge-base>` / `git diff --name-status <merge-base>`.
- Untracked files are hidden (GitLab parity) with a stderr hint; never `git add` them.
- `file` subcommand inherits stdio (pager/color like git); `list` captures and prints.

## 6. Quality gates (run before every commit)

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
```

Style: `ruff` defaults (`line-length = 100`, `target-version = py39`),
`mypy strict = true`. Fix warnings instead of adding ignores.

## 7. Commits

- Conventional commits: `feat(mr): ...`, `fix(mr-diff): ...`, `chore(...)`, `docs(...)`.
- One logical change per commit; update tests + README in the same commit as behavior.
- Do not commit `.venv/`, `*.egg-info/`, `__pycache__/`, or `mr-base` files.
