# AGENTS.md — Contributor Contract for this repo

This repo is a monorepo of small personal CLI helpers (`mr`, `mr-diff`, …).
Agents and humans follow the same rules below.

## 1. Project map

```text
pyproject.toml          # single project, one [project.scripts] entry per CLI
src/utilities/
  git.py                # ALL git subprocess I/O (no git calls elsewhere)
  base_store.py         # per-worktree base pointer (shared by mr + mr-diff)
  config_store.py       # global mr config (~/.config/mr/config)
  glab.py               # glab subprocess wrapper (optional dep, publish only)
  completion.py         # --print-completion + `mr completion install` logic (shared)
  completions/          # <prog>.bash + <prog>.zsh scripts (package data, see §6)
  cli_<name>.py         # ONE argparse CLI per file, with build_parser() + main()
tests/
  conftest.py           # tmp git repo + origin fixtures (use them, don't hand-roll)
  test_<name>.py
AGENTS.md               # this file
README.md               # minimal landing page (see §9, not a usage reference)
```

## 2. Hard constraints

- Python `>=3.9`. Always add `from __future__ import annotations` and avoid
  3.10+ runtime syntax (e.g. `match`, `X | Y` in evaluated positions).
  `tuple[str, str] | None` in annotations is OK because of the future import.
- Runtime dependencies: **stdlib only** (`argparse`, `subprocess`, `pathlib`, …).
  Dev tools (`pytest`, `ruff`, `mypy`) live in `[dependency-groups] dev`.
- No shell scripts for CLIs. All CLIs are Python modules with type annotations.
  (Completion scripts under `completions/` are package *data*, not CLIs — see §6.)
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
5. Add completion: `src/utilities/completions/<name>.bash` + `<name>.zsh`
   (copy the closest existing script), register `<name>` in
   `completion.SUPPORTED_PROGRAMS`, and extend `tests/test_completion.py`.
   The `completions/*` package-data glob already covers the new files.
6. Update `README.md` only if §9 requires it (new/removed CLI, install
   change). Never add flags, examples, or behavior notes to `README.md`.

## 4. fetch semantics (shared by `mr new`, future `mr rebase`)

- Only fetch when the base parses as `<known-remote>/<branch>` via
  `parse_remote_ref` (first-`/` split + membership in `git remote`).
- Fetch form: `git fetch <remote> <branch>` (narrow, not full fetch).
- `--no-fetch` flag on every command that calls `ensure_fresh_base`.
- Offline/fetch failure → hard error, exit non-zero.

## 5. `mr-diff` semantics

- Review scope = diff against `git merge-base <base> HEAD`, NOT literal `base...HEAD`,
  so staged + unstaged working-tree changes are included:
  `git diff --find-renames <merge-base>` / `--name-status` / `--name-only`.
- Untracked (non-ignored) files are ALWAYS included as new files (`A <path>`);
  never `git add` them. `file` renders them via
  `git diff --no-index -- /dev/null <path>` (exit 1 normalized to 0).
  Ignored files stay hidden via `--exclude-standard`.
- `list` merges tracked + untracked rows and sorts by final path
  (rename destination for `R` rows). `# base:` goes to stderr; stdout is parseable.
- `file` takes a single file only; directories are rejected (exit 2).
  `file` inherits stdio (pager/color like git); `list` captures and prints.

## 6. Shell completion (bash + zsh)

- Scripts live as real shell files in `src/utilities/completions/<prog>.{bash,zsh}`
  (correct IDE highlighting; never embed scripts in Python strings). They are
  served by `completion.py:render_completion()` via
  `<prog> --print-completion {bash,zsh}`, loaded with `importlib.resources`.
- They are **package data**: keep them covered by
  `[tool.setuptools.package-data]` in `pyproject.toml`, or installed copies
  (`uv tool`, pipx) will silently miss them. When in doubt, verify with a
  wheel build (`uv build --wheel`, then `unzip -l` the wheel).
- `mr completion install|uninstall|status` manages ONE marked block per rc file
  covering every CLI in `completion.SUPPORTED_PROGRAMS` — keep it joint,
  don't fragment one block per CLI.
- Rule: **any new subcommand, flag, or positional arg MUST update every affected
  completion script (bash + zsh) in the same commit**, plus `tests/test_completion.py`.
- Dynamic candidates (branches, files) resolve in-shell with **read-only** `git`
  calls only — never fetch, never write, fail silent outside repos.
  Python-side candidate helpers (if needed) go in `git.py` via `run_git`
  and must never raise (return `[]` outside repos).
- Verify edited scripts with `bash -n` / `zsh -n` on top of the pytest suite.

## 7. Quality gates (run before every commit)

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
```

Style: `ruff` defaults (`line-length = 100`, `target-version = py39`),
`mypy strict = true`. Fix warnings instead of adding ignores.

## 8. Commits

- Conventional commits: `feat(mr): ...`, `fix(mr-diff): ...`, `chore(...)`, `docs(...)`.
- One logical change per commit; update tests + README in the same commit as behavior.
  README changes follow §9 (most behavior changes need no README edit).
- Do not commit `.venv/`, `*.egg-info/`, `__pycache__/`, or `mr-base` files.

## 9. README policy (keep it minimal)

`README.md` is a landing page for first-time visitors, not a manual.
Keep it under ~50 lines: what it is, install, 4-line quickstart,
where to find full help (`--help`), completion one-liner, `AGENTS.md` pointer.

- Update `README.md` ONLY when: adding/removing a CLI, changing install
  steps, or changing completion setup. Nothing else qualifies.
- NEVER in `README.md`: exhaustive flag lists, per-subcommand examples,
  edge cases, error semantics, storage paths, fetch rules, or behavior
  notes. That detail belongs in `--help` text, code docstrings, `AGENTS.md`
  (§4–§6), or tests — all of which stay in sync with the code.
- New flags/subcommands MUST update `--help` + completion scripts + tests
  in the same commit, and MUST NOT touch `README.md`.
