"""Git integration for selecting changed files."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class GitError(RuntimeError):
    """Raised when repository change discovery fails."""


ChangeStatus = Literal["added", "copied", "deleted", "modified", "renamed", "type-changed"]


@dataclass(frozen=True)
class FileChange:
    """One logical path change reported by Git.

    ``path`` is the current path, except for deletions where it is the removed path.
    Renames and copies also expose their source through ``old_path``. Historical content is
    populated for deleted files and rename sources so a repository scanner can include files
    that no longer exist in the checkout.
    """

    status: ChangeStatus
    path: str
    old_path: str | None = None
    previous_content: str | None = None


@dataclass(frozen=True)
class ChangeSet:
    """Structured result of Git change discovery."""

    changes: tuple[FileChange, ...]

    @property
    def paths(self) -> list[str]:
        """Return every affected path, including both sides of a rename."""
        paths = {change.path for change in self.changes}
        paths.update(change.old_path for change in self.changes if change.old_path is not None)
        return sorted(paths)

    @property
    def previous_files(self) -> dict[str, str]:
        """Return removed paths and their content from before the change."""
        return {
            change.old_path or change.path: change.previous_content
            for change in self.changes
            if change.previous_content is not None
            and (change.status == "deleted" or change.old_path is not None)
        }


def discover_changes(root: Path, base: str | None = None) -> ChangeSet:
    """Discover repository changes and retain content that disappeared.

    With a base revision, the comparison starts at its merge base with ``HEAD``. User-provided
    revisions are first resolved to a commit ID and are never forwarded to ``git diff``. Without
    a base, the comparison includes staged, unstaged, and untracked work. A clean checkout falls
    back to its latest commit so the result remains useful in CI and fresh clones.
    """
    _ensure_git_repository(root)

    if base is not None:
        resolved_base = _resolve_base(root, base)
        head = _head_revision(root)
        if head is None:
            raise GitError("cannot compare --base in a repository without commits")
        comparison_base = _merge_base(root, resolved_base, head)
        changes = _diff_changes(root, comparison_base, head)
        return _with_previous_content(root, changes, comparison_base)

    head = _head_revision(root)
    changes = _diff_index(root) if head is None else _diff_changes(root, head)
    changes.extend(_untracked_changes(root))
    if changes:
        return _with_previous_content(root, changes, head)

    if head is None:
        return ChangeSet(())

    parent = _first_parent(root, head)
    if parent is not None:
        return _with_previous_content(root, _diff_changes(root, parent, head), parent)

    # A root commit has no historical tree, but its additions are still useful to analyze.
    return ChangeSet(tuple(_root_commit_changes(root, head)))


def changed_files(root: Path, base: str | None = None) -> list[str]:
    """Return changed paths relative to root.

    This compatibility wrapper now includes deletions and both the old and new path of a rename.
    Use :func:`discover_changes` when callers also need statuses or historical file contents.
    """
    return discover_changes(root, base).paths


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
    top_level = Path(result.stdout.strip()).resolve()
    if root.resolve() != top_level:
        raise GitError(f"repository path must be the Git top level: {top_level}")


def _resolve_base(root: Path, base: str) -> str:
    if not base:
        raise GitError("base revision must not be empty")
    if base.startswith("-"):
        raise GitError("base revision must not start with '-'")
    if "\0" in base:
        raise GitError("base revision must not contain a NUL byte")

    result = _run_git(
        root,
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{base}^{{commit}}"],
        check=False,
    )
    if result.returncode != 0:
        raise GitError(f"invalid base revision: {base!r}")
    revision = result.stdout.decode("ascii", errors="strict").strip()
    if not revision:
        raise GitError(f"invalid base revision: {base!r}")
    return revision


def _head_revision(root: Path) -> str | None:
    result = _run_git(
        root,
        ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("ascii", errors="strict").strip()


def _merge_base(root: Path, left: str, right: str) -> str:
    result = _run_git(root, ["merge-base", left, right], check=False)
    if result.returncode != 0:
        raise GitError("base revision and HEAD do not have a merge base")
    revision = result.stdout.decode("ascii", errors="strict").strip()
    if not revision:
        raise GitError("base revision and HEAD do not have a merge base")
    return revision


def _first_parent(root: Path, revision: str) -> str | None:
    result = _run_git(
        root,
        ["rev-parse", "--verify", "--quiet", f"{revision}^1"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("ascii", errors="strict").strip()


def _diff_changes(root: Path, start: str, end: str | None = None) -> list[FileChange]:
    revisions = [start] if end is None else [start, end]
    result = _run_git(
        root,
        [
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--diff-filter=ACMRTD",
            *revisions,
            "--",
        ],
    )
    return _parse_name_status(result.stdout)


def _diff_index(root: Path) -> list[FileChange]:
    result = _run_git(
        root,
        [
            "diff",
            "--cached",
            "--name-status",
            "-z",
            "--find-renames",
            "--diff-filter=ACMRTD",
            "--",
        ],
    )
    return _parse_name_status(result.stdout)


def _root_commit_changes(root: Path, revision: str) -> list[FileChange]:
    result = _run_git(
        root,
        [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "-r",
            "--name-status",
            "-z",
            "--find-renames",
            "--diff-filter=ACMRTD",
            revision,
            "--",
        ],
    )
    return _parse_name_status(result.stdout)


def _untracked_changes(root: Path) -> list[FileChange]:
    result = _run_git(root, ["ls-files", "--others", "--exclude-standard", "-z", "--"])
    return [
        FileChange(status="added", path=_decode_path(path))
        for path in result.stdout.split(b"\0")
        if path
    ]


def _parse_name_status(payload: bytes) -> list[FileChange]:
    fields = payload.split(b"\0")
    if fields and not fields[-1]:
        fields.pop()

    changes: list[FileChange] = []
    position = 0
    while position < len(fields):
        raw_status = fields[position]
        position += 1
        status_code = raw_status[:1].decode("ascii", errors="strict")
        status = _status_name(status_code)

        if status_code in {"C", "R"}:
            if position + 1 >= len(fields):
                raise GitError("git returned an incomplete rename or copy record")
            old_path = _decode_path(fields[position])
            path = _decode_path(fields[position + 1])
            position += 2
            changes.append(FileChange(status=status, path=path, old_path=old_path))
        else:
            if position >= len(fields):
                raise GitError("git returned an incomplete path record")
            path = _decode_path(fields[position])
            position += 1
            changes.append(FileChange(status=status, path=path))

    return changes


def _status_name(status: str) -> ChangeStatus:
    statuses: dict[str, ChangeStatus] = {
        "A": "added",
        "C": "copied",
        "D": "deleted",
        "M": "modified",
        "R": "renamed",
        "T": "type-changed",
    }
    try:
        return statuses[status]
    except KeyError as exc:
        raise GitError(f"git returned an unsupported change status: {status!r}") from exc


def _decode_path(path: bytes) -> str:
    return Path(os.fsdecode(path)).as_posix()


def _with_previous_content(
    root: Path,
    changes: list[FileChange],
    previous_revision: str | None,
) -> ChangeSet:
    if previous_revision is None:
        return ChangeSet(tuple(changes))

    hydrated: list[FileChange] = []
    for change in changes:
        historical_path = change.old_path if change.old_path is not None else change.path
        if change.status not in {"deleted", "renamed"}:
            hydrated.append(change)
            continue
        content = _file_at_revision(root, previous_revision, historical_path)
        hydrated.append(
            FileChange(
                status=change.status,
                path=change.path,
                old_path=change.old_path,
                previous_content=content,
            )
        )
    return ChangeSet(tuple(hydrated))


def _file_at_revision(root: Path, revision: str, path: str) -> str:
    result = _run_git(root, ["cat-file", "blob", f"{revision}:{path}"])
    return result.stdout.decode("utf-8", errors="replace")


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(message or f"git {' '.join(arguments)} failed")
    return result
