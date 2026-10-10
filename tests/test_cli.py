import pytest

from reporipple import __version__
from reporipple.cli import main


def test_version_reports_installed_package_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"reporipple {__version__}\n"
