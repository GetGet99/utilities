"""Shell completion scripts for ``mr`` and ``mr-diff`` (bash + zsh).

The scripts live as data files under ``utilities/completions/`` (``.bash`` /
``.zsh`` so IDEs highlight them) and are printed by
``mr --print-completion {bash,zsh}``. Install with
``mr completion install``. Dynamic candidates (branch refs, review files)
are resolved in-shell with read-only ``git`` calls so every ``<TAB>``
stays fast (no Python startup) and never fetches or writes.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

COMPLETION_SHELLS: tuple[str, ...] = ("bash", "zsh")
SUPPORTED_PROGRAMS: tuple[str, ...] = ("mr", "mr-diff")

COMPLETION_BLOCK_BEGIN = "# >>> utilities completion >>>"
COMPLETION_BLOCK_END = "# <<< utilities completion <<<"

COMPLETION_DIR = "completions"


def _script_text(prog: str, shell: str) -> str:
    """Load the ``<prog>.<shell>`` completion script shipped as package data."""
    ref = resources.files("utilities").joinpath(f"{COMPLETION_DIR}/{prog}.{shell}")
    return ref.read_text(encoding="utf-8")


def render_completion(prog: str, shell: str) -> str:
    """Return the completion script for *prog* (``mr``|``mr-diff``)."""
    if prog not in SUPPORTED_PROGRAMS:
        raise ValueError(f"unknown program '{prog}' (expected mr|mr-diff)")
    if shell not in COMPLETION_SHELLS:
        raise ValueError(f"unknown shell '{shell}' (expected bash|zsh)")
    return _script_text(prog, shell)


def print_completion(prog: str, shell: str) -> int:
    """Print the completion script; return 0 or 2 on bad shell/program."""
    try:
        script = render_completion(prog, shell)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(script)
    if not script.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def handle_print_completion(prog: str, argv: Sequence[str] | None) -> int | None:
    """Pre-scan *argv* for ``--print-completion``; print and return exit code.

    Returns None when the flag is absent so the caller continues with normal
    argparse dispatch. Supports ``--print-completion SHELL`` and
    ``--print-completion=SHELL``. Runs before ``parse_args`` because the
    subparsers are ``required=True`` and would otherwise reject a bare flag.
    Only honors the flag as the first argument so ``mr new x``-style calls
    are never hijacked.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return None
    first = args[0]
    shell: str | None = None
    if first == "--print-completion":
        if len(args) < 2:
            print("error: --print-completion needs bash|zsh", file=sys.stderr)
            return 2
        shell = args[1]
    elif first.startswith("--print-completion="):
        shell = first.partition("=")[2]
    else:
        return None
    if not shell:
        print("error: --print-completion needs bash|zsh", file=sys.stderr)
        return 2
    return print_completion(prog, shell)


def _eval_line(prog: str, shell: str) -> str:
    """The rc line sourcing *prog*'s completion, e.g. ``eval "$(mr ...)"``."""
    return f'eval "$({prog} --print-completion {shell})"'


def rc_block(shell: str) -> str:
    """Expected managed rc block for *shell* (covers mr + mr-diff)."""
    if shell not in COMPLETION_SHELLS:
        raise ValueError(f"unknown shell '{shell}' (expected bash|zsh)")
    lines = [
        COMPLETION_BLOCK_BEGIN,
        "# Tab-completion for `mr` / `mr-diff`.",
        "# Managed by `mr completion install`; remove with `mr completion uninstall`.",
        *[_eval_line(prog, shell) for prog in SUPPORTED_PROGRAMS],
        COMPLETION_BLOCK_END,
    ]
    return "\n".join(lines) + "\n"


def rc_file(shell: str) -> Path:
    """Rc file owning *shell*'s interactive config (``~/.zshrc``/``~/.bashrc``).

    Honors ``$ZDOTDIR`` for zsh and ``$HOME`` for both, so tests can point
    them at a temp dir. Raises ValueError for unknown shells.
    """
    if shell == "zsh":
        zdotdir = os.environ.get("ZDOTDIR", "").strip()
        base = Path(zdotdir) if zdotdir else Path.home()
        return base / ".zshrc"
    if shell == "bash":
        return Path.home() / ".bashrc"
    raise ValueError(f"unknown shell '{shell}' (expected bash|zsh)")


def detect_shell() -> str | None:
    """Basename of ``$SHELL`` when it is a supported shell, else None."""
    name = os.environ.get("SHELL", "").strip().rsplit("/", 1)[-1]
    return name if name in COMPLETION_SHELLS else None


class CompletionError(RuntimeError):
    """Raised when an rc file cannot be read or written."""


def _read_rc(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise CompletionError(f"cannot read '{path}': {exc}") from exc


def _strip_block(text: str) -> str:
    """Remove every managed block (markers inclusive); collapse spare blanks."""
    while COMPLETION_BLOCK_BEGIN in text:
        before, _, rest = text.partition(COMPLETION_BLOCK_BEGIN)
        _, sep, after = rest.partition(COMPLETION_BLOCK_END)
        if not sep:
            # Unterminated marker: drop from the marker to end of file.
            text = before.rstrip("\n") + ("\n" if before.strip() else "")
            break
        merged = before.rstrip("\n") + "\n" + after.lstrip("\n")
        while "\n\n\n" in merged:
            merged = merged.replace("\n\n\n", "\n\n")
        text = merged.lstrip("\n") if not merged.strip() else merged
    return text


def _strip_bare_eval_lines(text: str, shell: str) -> str:
    """Drop hand-added (unmarked) copies of our eval lines (install adopts them)."""
    wanted = {_eval_line(prog, shell) for prog in SUPPORTED_PROGRAMS}
    kept = [line for line in text.splitlines(keepends=True) if line.strip() not in wanted]
    return "".join(kept)


def _backup(path: Path) -> Path:
    backup = path.with_name(path.name + ".bak")
    shutil.copy2(path, backup)
    return backup


def _write_rc(path: Path, text: str) -> Path | None:
    """Write *text* to *path* (creating parents); return backup path or None."""
    backup: Path | None = None
    if path.exists():
        backup = _backup(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return backup


def install_completion(shells: Sequence[str], *, dry_run: bool = False) -> int:
    """Install the managed completion block for *shells*; return exit code.

    Idempotent: re-running reports "already installed" without touching the
    file. Hand-added copies of the same eval lines are adopted into the
    managed block instead of being duplicated.
    """
    rc = 0
    for shell in shells:
        try:
            path = rc_file(shell)
            expected = rc_block(shell)
            original = _read_rc(path)
        except (ValueError, CompletionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            rc = 2
            continue
        cleaned = _strip_bare_eval_lines(_strip_block(original), shell)
        if expected in original and cleaned == _strip_block(original):
            # Exact block present and no stray hand-added copies: nothing to do.
            print(f"already installed: {shell} completion in '{path}'")
            continue
        body = cleaned.rstrip("\n")
        updated = (body + "\n\n" if body else "") + expected
        if updated == original:
            print(f"already installed: {shell} completion in '{path}'")
            continue
        if dry_run:
            print(f"would install: {shell} completion in '{path}'")
            continue
        try:
            backup = _write_rc(path, updated)
        except (CompletionError, OSError) as exc:
            print(f"error: cannot write '{path}': {exc}", file=sys.stderr)
            rc = 2
            continue
        detail = f" (backup: '{backup}')" if backup is not None else ""
        print(f"installed: {shell} completion in '{path}'{detail}")
        print("  restart your shell (or open a new tab) to pick it up")
    return rc


def uninstall_completion(shells: Sequence[str]) -> int:
    """Remove the managed completion block for *shells*; return exit code."""
    rc = 0
    for shell in shells:
        try:
            path = rc_file(shell)
            original = _read_rc(path)
        except (ValueError, CompletionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            rc = 2
            continue
        if COMPLETION_BLOCK_BEGIN not in original:
            print(f"not installed: no utilities block in '{path}'")
            continue
        updated = _strip_block(original)
        if not updated.strip():
            updated = ""
        try:
            backup = _write_rc(path, updated)
        except (CompletionError, OSError) as exc:
            print(f"error: cannot write '{path}': {exc}", file=sys.stderr)
            rc = 2
            continue
        detail = f" (backup: '{backup}')" if backup is not None else ""
        print(f"removed: {shell} completion from '{path}'{detail}")
    return rc


def completion_status(shells: Sequence[str] | None = None) -> int:
    """Report install state per shell; always returns 0."""
    targets = list(shells) if shells else list(COMPLETION_SHELLS)
    for shell in targets:
        try:
            path = rc_file(shell)
            expected = rc_block(shell)
            original = _read_rc(path)
        except (ValueError, CompletionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        wanted = {_eval_line(prog, shell) for prog in SUPPORTED_PROGRAMS}
        bare = any(line.strip() in wanted for line in original.splitlines())
        if expected in original:
            state = "installed"
        elif COMPLETION_BLOCK_BEGIN in original:
            state = "stale (markers present but block differs — re-run install)"
        elif bare:
            state = "manual (unmanaged lines — run install to adopt)"
        else:
            state = "missing"
        print(f"{shell}: {state} ('{path}')")
    return 0
