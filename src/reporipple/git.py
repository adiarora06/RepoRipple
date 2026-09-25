"""Git integration for selecting changed files."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when repository change discovery fails."""


def changed_files(root: Path, base: str | None = None) -> list[str]:
    """Return changed paths relative to root.

    With a base revision, compares the merge base to HEAD. Without one, includes staged,
    unstaged, and untracked work. If the worktree is clean, the latest commit is analyzed.
    """
    _ensure_git_repository(root)
    if base:
        return _run_paths(root, ["diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"])

    paths = set(_run_paths(root, ["diff", "--name-only", "--diff-filter=ACMR"]))
    paths.update(_run_paths(root, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"]))
    paths.update(_run_paths(root, ["ls-files", "--others", "--exclude-standard"]))
    if paths:
        return sorted(paths)

    # A clean checkout should still produce a useful report for its latest change.
    result = subprocess.run(
        ["git", "rev-parse", "HEAD~1"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return _run_paths(root, ["diff", "--name-only", "--diff-filter=ACMR", "HEAD~1..HEAD"])
    return _run_paths(root, ["show", "--pretty=", "--name-only", "--diff-filter=ACMR", "HEAD"])


def _ensure_git_repository(root: Path) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(f"{root} is not inside a Git repository")


def _run_paths(root: Path, arguments: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
