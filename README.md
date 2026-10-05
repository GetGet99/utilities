# utilities — my CLI helpers

Small Python CLIs (stdlib only) for day-to-day git work: `mr` + `mr-diff`.

## Install

Requires Python ≥ 3.9.

```sh
uv tool install --editable .
```

This provides `mr` and `mr-diff` on `PATH`.

## Use

```sh
mr new my-feature origin/main   # create + switch to branch from base
mr rebase                       # rebase current branch onto its base
mr-diff list                    # files changed vs base (committed + unstaged + untracked)
mr-diff file path/to/file       # patch for one file (pager/color like git)
```

Base is per-worktree and shared by `mr` and `mr-diff`.
Full flags live in the CLIs, not here:

```sh
mr --help; mr <command> --help; mr-diff --help
```

## Shell completion

```sh
mr completion install   # managed block in your rc file (bash/zsh)
mr completion status     # check what's installed where
```

Restart your shell afterwards. Details: `mr completion --help`.

## Contributing

See `AGENTS.md` for the contributor contract.
