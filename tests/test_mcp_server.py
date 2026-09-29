import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from reporipple.cli import main
from reporipple.mcp_server import RepoRippleMCPService, create_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def sample_repository(root: Path) -> None:
    write(root, "src/store.py", "def load(): return 1\n")
    write(root, "src/service.py", "from store import load\n")
    write(root, "tests/test_service.py", "from service import load\n")


def test_forecast_change_reuses_deterministic_analysis(tmp_path):
    repository = tmp_path / "project"
    repository.mkdir()
    sample_repository(repository)
    service = RepoRippleMCPService(tmp_path)

    result = service.forecast_change(["src/store.py"], repository="project")

    assert result.repository == "project"
    assert result.changed_files == ["src/store.py"]
    assert [(item.path, item.distance) for item in result.impacted_files] == [
        ("src/service.py", 1),
        ("tests/test_service.py", 2),
    ]
    assert result.suggested_tests == ["tests/test_service.py"]


def test_analyze_worktree_reads_actual_git_changes(tmp_path):
    repository = tmp_path / "project"
    repository.mkdir()
    sample_repository(repository)
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    write(repository, "src/store.py", "def load(): return 2\n")

    result = RepoRippleMCPService(tmp_path).analyze_worktree(repository="project")

    assert result.changed_files == ["src/store.py"]
    assert result.impacted_files[0].path == "src/service.py"


def test_analyze_worktree_traces_dependents_of_a_deleted_file(tmp_path):
    repository = tmp_path / "project"
    repository.mkdir()
    sample_repository(repository)
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    (repository / "src/store.py").unlink()

    result = RepoRippleMCPService(tmp_path).analyze_worktree(repository="project")

    assert result.changed_files == ["src/store.py"]
    assert [(item.path, item.distance) for item in result.impacted_files] == [
        ("src/service.py", 1),
        ("tests/test_service.py", 2),
    ]


def test_cli_traces_dependents_of_a_deleted_file(tmp_path, capsys):
    sample_repository(tmp_path)
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    (tmp_path / "src/store.py").unlink()

    assert main([str(tmp_path), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["changed_files"] == ["src/store.py"]
    assert [item["path"] for item in payload["impacted_files"]] == [
        "src/service.py",
        "tests/test_service.py",
    ]


def test_analyze_worktree_traces_stale_dependents_after_a_rename(tmp_path):
    repository = tmp_path / "project"
    repository.mkdir()
    write(repository, "src/legacy.py", "VALUE = 1\n")
    write(repository, "src/consumer.py", "from legacy import VALUE\n")
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "initial")
    git(repository, "mv", "src/legacy.py", "src/current.py")

    result = RepoRippleMCPService(tmp_path).analyze_worktree(repository="project")

    assert result.changed_files == ["src/current.py", "src/legacy.py"]
    assert [(item.path, item.distance) for item in result.impacted_files] == [
        ("src/consumer.py", 1)
    ]


def test_rejects_repository_and_changed_paths_outside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    repository = allowed / "project"
    outside = tmp_path / "outside"
    repository.mkdir(parents=True)
    outside.mkdir()
    write(repository, "src/app.py", "value = 1\n")
    service = RepoRippleMCPService(allowed)

    with pytest.raises(ValueError, match="outside the allowed root"):
        service.forecast_change(["src/app.py"], repository=str(outside))
    with pytest.raises(ValueError, match="outside the allowed root"):
        service.forecast_change(["src/app.py"], repository="../outside")
    with pytest.raises(ValueError, match="outside the repository"):
        service.forecast_change(["../secret.py"], repository="project")
    with pytest.raises(ValueError, match="repository-relative"):
        service.forecast_change([str(repository / "src/app.py")], repository="project")


def test_rejects_symlinked_repository_outside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the allowed root"):
        RepoRippleMCPService(allowed).forecast_change(["app.py"], repository="linked")


@pytest.mark.anyio
async def test_server_advertises_two_read_only_tools_with_structured_output(tmp_path):
    sample_repository(tmp_path)

    async with Client(create_server(tmp_path)) as client:
        catalog = await client.list_tools()
        tools = {tool.name: tool for tool in catalog.tools}
        result = await client.call_tool(
            "forecast_change",
            {"changed_files": ["src/store.py"]},
        )

    assert set(tools) == {"forecast_change", "analyze_worktree"}
    assert tools["forecast_change"].annotations.read_only_hint is True
    assert tools["forecast_change"].annotations.open_world_hint is False
    assert tools["forecast_change"].output_schema["title"] == "ImpactReportPayload"
    assert result.is_error is False
    assert result.structured_content["changed_files"] == ["src/store.py"]
    assert result.structured_content["impacted_files"][0]["path"] == "src/service.py"


@pytest.mark.anyio
async def test_server_returns_a_tool_error_for_out_of_root_access(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        result = await client.call_tool(
            "forecast_change",
            {"changed_files": ["src/app.py"], "repository": ".."},
        )

    assert result.is_error is True
    assert result.structured_content is None


@pytest.mark.anyio
async def test_cli_serves_valid_mcp_over_stdio(tmp_path):
    sample_repository(tmp_path)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "reporipple.cli", "mcp", "--root", str(tmp_path)],
    )

    async with Client(parameters, read_timeout_seconds=5) as client:
        catalog = await client.list_tools()

    assert {tool.name for tool in catalog.tools} == {"forecast_change", "analyze_worktree"}


def test_mcp_cli_passes_the_allowed_root(monkeypatch, tmp_path):
    received: list[Path] = []

    monkeypatch.setattr("reporipple.mcp_server.run_server", received.append)

    assert main(["mcp", "--root", str(tmp_path)]) == 0
    assert received == [tmp_path.resolve()]


def test_analyze_worktree_rejects_option_like_git_base(tmp_path):
    with pytest.raises(ValueError, match="Git revision"):
        RepoRippleMCPService(tmp_path).analyze_worktree(base="--output=/tmp/file")
