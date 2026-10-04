"""Optional ``glab`` (GitLab CLI) integration for ``mr publish``.

``glab`` is NOT installed with this project (stdlib-only runtime deps).
It is detected at runtime via :func:`find_glab` (``shutil.which``), so a
venv install keeps working — PATH lookup still finds a system-wide
``glab``. When missing, callers must fail with a helpful install hint.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

INSTALL_HINT = "install glab: https://gitlab.com/gitlab-org/cli#installation"


def find_glab() -> str | None:
    """Absolute path of the ``glab`` binary, or None when not on PATH."""
    return shutil.which("glab")


def build_create_args(
    target_branch: str,
    *,
    fill: bool = False,
    yes: bool = False,
    draft: bool = False,
    title: str | None = None,
    description: str | None = None,
    labels: Sequence[str] | None = None,
    assignees: Sequence[str] | None = None,
    reviewers: Sequence[str] | None = None,
    remove_source_branch: bool = False,
    extra: Sequence[str] | None = None,
) -> list[str]:
    """Argv for ``glab mr create --target-branch <target>`` with passthrough flags."""
    args: list[str] = ["mr", "create", "--target-branch", target_branch]
    if fill:
        args.append("--fill")
    if yes:
        args.append("--yes")
    if draft:
        args.append("--draft")
    if title is not None:
        args += ["--title", title]
    if description is not None:
        args += ["--description", description]
    for label in labels or []:
        args += ["--label", label]
    for assignee in assignees or []:
        args += ["--assignee", assignee]
    for reviewer in reviewers or []:
        args += ["--reviewer", reviewer]
    if remove_source_branch:
        args.append("--remove-source-branch")
    args += list(extra or [])
    return args


def exec_create(args: Sequence[str], cwd: Path) -> int:
    """Run ``glab <args>`` with inherited stdio so prompts/editors work.

    Returns the glab exit code.
    """
    glab = find_glab()
    if glab is None:  # pragma: no cover — callers check first for a nicer error
        raise RuntimeError(f"glab not found on PATH ({INSTALL_HINT})")
    result = subprocess.run(
        [glab, *args],
        cwd=str(cwd),
        text=True,
        capture_output=False,
        check=False,
    )
    return result.returncode
