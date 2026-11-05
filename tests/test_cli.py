import pytest

from reporipple import __version__
from reporipple.cli import main


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
