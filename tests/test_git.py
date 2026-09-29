import subprocess
from pathlib import Path

import pytest

from reporipple.git import GitError, changed_files, discover_changes


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def initialize_repository(root: Path) -> None:
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")


def test_detects_worktree_staged_and_untracked_changes(tmp_path):
    initialize_repository(tmp_path)
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
    initialize_repository(tmp_path)
    (tmp_path / "first.py").write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "first")
    (tmp_path / "second.py").write_text("value = 2\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "second")

    assert changed_files(tmp_path) == ["second.py"]


def test_clean_repository_with_one_commit_reports_root_commit(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "first.py").write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "first")

    assert changed_files(tmp_path) == ["first.py"]


def test_deleted_file_includes_content_from_head(tmp_path):
    initialize_repository(tmp_path)
    previous = "from app import run\n"
    deleted = tmp_path / "deleted.py"
    deleted.write_text(previous, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    deleted.unlink()

    result = discover_changes(tmp_path)

    assert result.paths == ["deleted.py"]
    assert result.previous_files == {"deleted.py": previous}
    assert result.changes[0].status == "deleted"
    assert result.changes[0].previous_content == previous
    assert changed_files(tmp_path) == ["deleted.py"]


def test_rename_includes_both_paths_and_content_from_head(tmp_path):
    initialize_repository(tmp_path)
    previous = "def legacy():\n    return True\n"
    (tmp_path / "old_name.py").write_text(previous, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    git(tmp_path, "mv", "old_name.py", "new_name.py")

    result = discover_changes(tmp_path)

    assert result.paths == ["new_name.py", "old_name.py"]
    assert result.previous_files == {"old_name.py": previous}
    assert len(result.changes) == 1
    assert result.changes[0].status == "renamed"
    assert result.changes[0].old_path == "old_name.py"
    assert result.changes[0].path == "new_name.py"


def test_base_comparison_uses_merge_base_for_removed_content(tmp_path):
    initialize_repository(tmp_path)
    deleted_content = "DELETED = True\n"
    renamed_content = "RENAMED = True\n"
    (tmp_path / "deleted.py").write_text(deleted_content, encoding="utf-8")
    (tmp_path / "before.py").write_text(renamed_content, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    base = git_output(tmp_path, "rev-parse", "HEAD")

    (tmp_path / "deleted.py").unlink()
    git(tmp_path, "mv", "before.py", "after.py")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "delete and rename")

    result = discover_changes(tmp_path, base)

    assert result.paths == ["after.py", "before.py", "deleted.py"]
    assert result.previous_files == {
        "before.py": renamed_content,
        "deleted.py": deleted_content,
    }
    assert {(change.status, change.old_path, change.path) for change in result.changes} == {
        ("deleted", None, "deleted.py"),
        ("renamed", "before.py", "after.py"),
    }


@pytest.mark.parametrize("base", ["--help", "--output=/tmp/reporipple-owned"])
def test_rejects_option_like_base_before_running_diff(tmp_path, base):
    initialize_repository(tmp_path)
    (tmp_path / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    with pytest.raises(GitError, match="must not start"):
        discover_changes(tmp_path, base)


def test_invalid_base_has_a_clear_error(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    with pytest.raises(GitError, match="invalid base revision"):
        discover_changes(tmp_path, "does-not-exist")

    with pytest.raises(GitError, match="must not be empty"):
        discover_changes(tmp_path, "")


def test_nul_delimited_output_preserves_newlines_in_paths(tmp_path):
    initialize_repository(tmp_path)
    path = "line\nbreak.py"
    (tmp_path / path).write_text("value = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")

    (tmp_path / path).write_text("value = 2\n", encoding="utf-8")

    assert changed_files(tmp_path) == [path]
