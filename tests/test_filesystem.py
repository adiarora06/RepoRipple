from pathlib import Path

import pytest

import reporipple.filesystem as filesystem
from reporipple.filesystem import read_repository_bytes


def test_repository_reader_rejects_absolute_paths(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(OSError, match="must be relative"):
        read_repository_bytes(tmp_path, outside.as_posix(), 100)


@pytest.mark.parametrize("relative", ["", "../outside.txt", "safe/../../outside.txt"])
def test_repository_reader_rejects_unsafe_relative_paths(
    tmp_path: Path,
    relative: str,
) -> None:
    with pytest.raises(OSError, match="unsafe repository-relative path"):
        read_repository_bytes(tmp_path, relative, 100)


def test_repository_reader_never_follows_a_symlinked_file(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    with pytest.raises(OSError):
        read_repository_bytes(tmp_path, "link.txt", 100)


def test_repository_reader_never_follows_a_symlinked_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "private.txt").write_text("private", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    with pytest.raises(OSError):
        read_repository_bytes(tmp_path, "link/private.txt", 100)


def test_repository_reader_rejects_non_regular_files(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()

    with pytest.raises(OSError, match="not a regular file"):
        read_repository_bytes(tmp_path, "directory", 100)


def test_repository_reader_reads_at_most_limit_plus_one_bytes(tmp_path: Path) -> None:
    (tmp_path / "payload.bin").write_bytes(b"abcdef")

    assert read_repository_bytes(tmp_path, "payload.bin", 3) == b"abcd"


def test_resolved_path_fallback_preserves_security_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    monkeypatch.setattr(filesystem.os, "supports_dir_fd", set())

    assert read_repository_bytes(tmp_path, "safe.txt", 100) == b"safe"
    with pytest.raises(OSError, match="symbolic link"):
        read_repository_bytes(tmp_path, "link.txt", 100)
