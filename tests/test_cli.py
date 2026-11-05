import os
from pathlib import Path

import pytest

from reporipple import __version__
from reporipple.cli import build_parser, main


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_version_reports_installed_package_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"reporipple {__version__}\n"


def test_html_impact_map_can_be_written_and_opened(monkeypatch, tmp_path):
    write(tmp_path, "src/store.py", "def load(): return 1\n")
    write(tmp_path, "src/service.py", "from store import load\n")
    report = tmp_path / "impact.html"
    opened = []
    monkeypatch.setattr("reporipple.cli.webbrowser.open", lambda url: opened.append(url) or True)

    assert (
        main(
            [
                str(tmp_path),
                "--changed",
                "src/store.py",
                "--format",
                "html",
                "--output",
                str(report),
                "--open",
            ]
        )
        == 0
    )

    assert report.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert opened == [report.resolve().as_uri()]


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["--open"], "--open requires --format html/all"),
        (["--format", "all"], "--format all requires --output DIRECTORY"),
        (
            ["--format", "html", "--output", "impact.html", "--explain-preview"],
            "HTML impact maps are deterministic",
        ),
    ],
)
def test_rejects_incompatible_html_options(arguments, message, capsys):
    assert main(arguments) == 1

    assert message in capsys.readouterr().err


def test_all_format_writes_one_review_bundle(monkeypatch, tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    write(repository, "src/store.py", "def load(): return 1\n")
    write(repository, "src/service.py", "from store import load\n")
    reports = tmp_path / "reports"
    opened = []
    monkeypatch.setattr("reporipple.cli.webbrowser.open", lambda url: opened.append(url) or True)

    assert (
        main(
            [
                str(repository),
                "--changed",
                "src/store.py",
                "--format",
                "all",
                "--output",
                str(reports),
                "--open",
            ]
        )
        == 0
    )

    assert {path.name for path in reports.iterdir()} == {"impact.md", "impact.json", "impact.html"}
    assert opened == [(reports / "impact.html").resolve().as_uri()]


def test_all_format_keeps_previous_bundle_when_staging_fails(monkeypatch, tmp_path, capsys):
    repository = tmp_path / "repository"
    repository.mkdir()
    write(repository, "src/store.py", "def load(): return 1\n")
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in ("impact.md", "impact.json", "impact.html"):
        write(reports, name, f"old {name}\n")

    real_write_text = Path.write_text

    def fail_during_staging(path, content, *args, **kwargs):
        if "-staging-" in path.parent.name and path.name == "impact.json":
            raise OSError("simulated staging failure")
        return real_write_text(path, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_during_staging)

    assert (
        main(
            [
                str(repository),
                "--changed",
                "src/store.py",
                "--format",
                "all",
                "--output",
                str(reports),
            ]
        )
        == 1
    )

    assert "simulated staging failure" in capsys.readouterr().err
    assert {
        path.name: path.read_text(encoding="utf-8") for path in reports.iterdir()
    } == {
        "impact.md": "old impact.md\n",
        "impact.json": "old impact.json\n",
        "impact.html": "old impact.html\n",
    }
    assert list(tmp_path.glob(".reports-staging-*")) == []


def test_all_format_restores_previous_bundle_when_publish_fails(monkeypatch, tmp_path, capsys):
    repository = tmp_path / "repository"
    repository.mkdir()
    write(repository, "src/store.py", "def load(): return 1\n")
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in ("impact.md", "impact.json", "impact.html"):
        write(reports, name, f"old {name}\n")

    real_replace = os.replace

    def fail_staged_publish(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if "-staging-" in source_path.name and destination_path == reports:
            raise OSError("simulated publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr("reporipple.cli.os.replace", fail_staged_publish)

    assert (
        main(
            [
                str(repository),
                "--changed",
                "src/store.py",
                "--format",
                "all",
                "--output",
                str(reports),
            ]
        )
        == 1
    )

    assert "simulated publish failure" in capsys.readouterr().err
    assert {
        path.name: path.read_text(encoding="utf-8") for path in reports.iterdir()
    } == {
        "impact.md": "old impact.md\n",
        "impact.json": "old impact.json\n",
        "impact.html": "old impact.html\n",
    }
    assert list(tmp_path.glob(".reports-staging-*")) == []
    assert list(tmp_path.glob(".reports-backup-*")) == []


def test_all_format_refuses_to_replace_unrelated_directory_contents(tmp_path, capsys):
    repository = tmp_path / "repository"
    repository.mkdir()
    write(repository, "src/store.py", "def load(): return 1\n")
    reports = tmp_path / "reports"
    write(reports, "keep.txt", "do not replace\n")

    assert (
        main(
            [
                str(repository),
                "--changed",
                "src/store.py",
                "--format",
                "all",
                "--output",
                str(reports),
            ]
        )
        == 1
    )

    assert "contains unrelated files" in capsys.readouterr().err
    assert (reports / "keep.txt").read_text(encoding="utf-8") == "do not replace\n"


def test_all_format_rejects_a_symlinked_destination(tmp_path, capsys):
    repository = tmp_path / "repository"
    repository.mkdir()
    write(repository, "src/store.py", "def load(): return 1\n")
    actual_reports = tmp_path / "actual-reports"
    actual_reports.mkdir()
    reports = tmp_path / "reports"
    try:
        reports.symlink_to(actual_reports, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    assert (
        main(
            [
                str(repository),
                "--changed",
                "src/store.py",
                "--format",
                "all",
                "--output",
                str(reports),
            ]
        )
        == 1
    )

    assert "not a regular directory" in capsys.readouterr().err
    assert list(actual_reports.iterdir()) == []


def test_open_warning_preserves_written_report_when_browser_launch_fails(
    monkeypatch, tmp_path, capsys
):
    write(tmp_path, "src/store.py", "def load(): return 1\n")
    report = tmp_path / "impact.html"

    def fail_to_open(_url):
        raise OSError("browser executable is unavailable")

    monkeypatch.setattr("reporipple.cli.webbrowser.open", fail_to_open)

    assert (
        main(
            [
                str(tmp_path),
                "--changed",
                "src/store.py",
                "--format",
                "html",
                "--output",
                str(report),
                "--open",
            ]
        )
        == 0
    )

    assert report.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "browser executable is unavailable" in capsys.readouterr().err


def test_output_help_distinguishes_file_and_bundle_directory():
    help_text = " ".join(build_parser().format_help().split())

    assert "one report to FILE" in help_text
    assert "bundle to DIRECTORY" in help_text
