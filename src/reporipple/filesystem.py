"""Bounded repository file reads that never follow symbolic links."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath


def read_repository_bytes(root: Path, relative: str, limit: int) -> bytes:
    """Read a regular repository file without traversing symlinks.

    On platforms with ``openat``-style support, each path component is opened relative to an
    already-open directory descriptor. This closes the check/open race that a separate symlink
    check would leave behind. Other platforms use a boundary-checked fallback.
    """
    relative_path = PurePosixPath(relative)
    parts = relative_path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise OSError(f"unsafe repository-relative path: {relative}")
    if relative_path.is_absolute():
        raise OSError(f"repository path must be relative: {relative}")

    if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        return _read_with_directory_descriptors(root, parts, limit)
    return _read_with_resolved_path(root, parts, limit)


def _read_with_directory_descriptors(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        file_flags |= os.O_BINARY

    directory_fd = os.open(root, directory_flags)
    try:
        for component in parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd

        file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise OSError("repository path is not a regular file")
            with os.fdopen(file_fd, "rb", closefd=False) as repository_file:
                return repository_file.read(limit + 1)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)


def _read_with_resolved_path(root: Path, parts: tuple[str, ...], limit: int) -> bytes:
    root = root.resolve()
    path = root.joinpath(*parts)
    current = root
    for component in parts:
        current /= component
        if current.is_symlink():
            raise OSError("repository path contains a symbolic link")

    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OSError("could not resolve repository path") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OSError("repository path resolves outside the repository") from exc
    if not resolved.is_file():
        raise OSError("repository path is not a regular file")
    with resolved.open("rb") as repository_file:
        return repository_file.read(limit + 1)
