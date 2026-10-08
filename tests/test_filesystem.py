from pathlib import Path

import pytest

from reporipple.filesystem import read_repository_bytes


def test_repository_reader_rejects_absolute_paths(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(OSError, match="must be relative"):
        read_repository_bytes(tmp_path, outside.as_posix(), 100)
