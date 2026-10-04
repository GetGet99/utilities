# utilities — personal CLI helpers

Small Python CLIs (stdlib only) for day-to-day git work. Starts with `mr` + `mr-diff`.

## Install

Requires Python ≥ 3.9.

```sh
# isolated (recommended)
pipx install -e .

# or inside a venv (this repo uses uv, but any venv works)
uv venv .venv && uv pip install -e .
```

This provides `mr` and `mr-diff` on `PATH`.

## `mr` — branch + base helper

```sh
mr new my-feature                  # from <effective-default>, then switch to it
mr new my-feature main              # from local base
mr new my-feature origin/main       # from remote base (fetches origin/main first)
mr new my-feature origin/main --no-fetch   # skip fetch (offline)

mr base                             # print this worktree's base
mr base set main                    # change base (fetches if remote)
mr base set origin/main --no-fetch
mr base reset                       # back to the effective default

mr base default                     # print repo-level default (or origin/<default-branch>)
mr base default set develop         # change repo default for all worktrees (fetches if remote)
mr base default set origin/develop --no-fetch
mr base default reset               # back to origin/<default-branch>

mr rebase                           # git rebase onto this worktree's base (fetches if remote)
mr rebase --no-fetch                # skip fetch (offline)

mr merge                            # rebase onto base, then squash-merge into the base worktree
mr merge -m "ship it"               # custom squash/merge message
mr merge --no-ff                    # regular merge commit instead of squash
mr merge --no-fetch                 # skip fetch (offline)
mr merge --push / --no-push         # override push policy (default: auto)

mr config list                      # global behavior defaults
mr config set merge.strategy merge  # default merge mode: squash | merge
mr config set merge.push never      # default push policy: auto | always | never
mr config reset [key]               # drop one key (or all global config)
```

Notes:

- Base is **per-worktree** (stored at `<worktree-git-dir>/mr-base`), shared by
  `mr` and `mr-diff`. Two worktrees of the same repo can have different bases.
- Repo default is **shared by all worktrees** (stored at `<common-git-dir>/mr-default`).
  When set, `mr new` without a base and `mr base reset` use it instead of
  `origin/<default-branch>`.
- `mr new` blocks when: the branch already exists, the base doesn't resolve,
  or `git checkout -b` refuses (e.g. uncommitted changes would be overwritten).
- `mr rebase` rebases the current branch onto this worktree's base with stdio
  inherited, so conflicts/editors behave like plain `git rebase`.
- Remote bases (`origin/<branch>`) are refreshed with `git fetch <remote> <branch>`
  before use; fetch failure hard-fails. Branch names with slashes like
  `feat/foo` are never mistaken for a remote.
- `mr merge` rebases the current branch onto the local base, then merges inside
  the worktree that owns the base branch (which must exist — the merge aborts
  otherwise). Running it while on the base itself is blocked, as are dirty or
  mid-rebase/merge worktrees on either side. Remote bases (`origin/main`) are
  fast-forwarded into the base worktree first (diverged/behind aborts); local
  bases are used as-is. Push policy is `auto` by default: push only when the
  base is a remote ref. The feature branch is realigned onto the base
  afterwards (never auto-deleted).

## `mr-diff` — MR-style/PR-style diff vs base (committed + staged + unstaged)

```sh
mr-diff list               # name-status of everything changed since merge-base
mr-diff list --name-only  # paths only
mr-diff file path/to/file # patch for one file (pager/color like git)
```

Untracked files are hidden (GitLab parity) with a stderr hint.

## Future CLIs

One module per CLI (`src/utilities/cli_<name>.py`) + one line in
`pyproject.toml` `[project.scripts]`. See `AGENTS.md` for the contributor contract.
