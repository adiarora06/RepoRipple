import subprocess
from pathlib import Path

from reporipple.git import changed_files


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_detects_worktree_staged_and_untracked_changes(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "staged.py").write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    (tmp_path / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "staged.py").write_text("value = 2\n", encoding="utf-8")
    git(tmp_path, "add", "staged.py")
    (tmp_path / "new.py").write_text("value = 3\n", encoding="utf-8")

    assert changed_files(tmp_path) == ["new.py", "staged.py", "tracked.py"]


def test_clean_repository_falls_back_to_latest_commit(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "first.py").write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "first")
    (tmp_path / "second.py").write_text("value = 2\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "second")

    assert changed_files(tmp_path) == ["second.py"]
