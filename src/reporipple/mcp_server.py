"""Read-only Model Context Protocol tools for RepoRipple."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from reporipple import __version__
from reporipple.analysis import analyze_impact
from reporipple.git import changed_files
from reporipple.models import ImpactReport
from reporipple.scanner import scan_repository

LOGGER = logging.getLogger(__name__)

RepositoryArgument = Annotated[
    str,
    Field(
        description=(
            "Repository directory, relative to the server's allowed root. "
            "Absolute paths are accepted only when they remain inside that root."
        ),
        max_length=4096,
    ),
]
ChangedFilesArgument = Annotated[
    list[str],
    Field(
        description="Repository-relative files that are expected to change.",
        min_length=1,
        max_length=500,
    ),
]
MaxDepthArgument = Annotated[
    int,
    Field(description="Maximum reverse-dependency traversal depth.", ge=1, le=20),
]
BaseArgument = Annotated[
    str | None,
    Field(description="Optional Git revision to compare with HEAD.", max_length=256),
]


class ImpactedFilePayload(BaseModel):
    """One file reached by reverse-dependency traversal."""

    path: str
    distance: int
    via: list[str]


class ImpactReportPayload(BaseModel):
    """Structured RepoRipple analysis returned to an MCP client."""

    repository: str
    changed_files: list[str]
    impacted_files: list[ImpactedFilePayload]
    suggested_tests: list[str]
    documentation_to_review: list[str]
    risk_level: Literal["low", "medium", "high"]
    risk_reasons: list[str]
    graph_files: int
    graph_edges: int
    warnings: list[str]

    @classmethod
    def from_report(cls, report: ImpactReport) -> ImpactReportPayload:
        """Convert the core dataclass without changing the deterministic result."""
        return cls.model_validate(report.to_dict())


class RepositoryAccess:
    """Resolve tool inputs while keeping every repository inside one allowed root."""

    def __init__(self, root: Path) -> None:
        try:
            resolved = root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"allowed root does not exist: {root}") from exc
        if not resolved.is_dir():
            raise ValueError(f"allowed root is not a directory: {resolved}")
        self.root = resolved

    def repository(self, requested: str = ".") -> Path:
        """Resolve an existing directory under the configured root."""
        if not requested or "\x00" in requested:
            raise ValueError("repository must be a non-empty path")

        supplied = Path(requested).expanduser()
        candidate = supplied if supplied.is_absolute() else self.root / supplied
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"repository does not exist: {requested}") from exc

        if not resolved.is_dir():
            raise ValueError(f"repository is not a directory: {requested}")
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                f"repository is outside the allowed root: {requested}"
            ) from exc
        return resolved

    @staticmethod
    def changed_paths(repository: Path, requested: list[str]) -> list[str]:
        """Validate and normalize repository-relative changed paths."""
        normalized: set[str] = set()
        for value in requested:
            if not value or "\x00" in value:
                raise ValueError("changed files must contain non-empty paths")
            supplied = Path(value)
            if supplied.is_absolute():
                raise ValueError(f"changed file must be repository-relative: {value}")

            candidate = (repository / supplied).resolve(strict=False)
            try:
                relative = candidate.relative_to(repository)
            except ValueError as exc:
                raise ValueError(f"changed file is outside the repository: {value}") from exc
            if relative == Path("."):
                raise ValueError("changed file must identify a file, not the repository root")
            normalized.add(relative.as_posix())

        return sorted(normalized)


class RepoRippleMCPService:
    """Transport-independent implementation behind the MCP tools."""

    def __init__(self, root: Path) -> None:
        self.access = RepositoryAccess(root)

    def forecast_change(
        self,
        changed: list[str],
        *,
        repository: str = ".",
        max_depth: int = 4,
    ) -> ImpactReportPayload:
        """Analyze proposed file changes without requiring a Git diff."""
        repo = self.access.repository(repository)
        paths = self.access.changed_paths(repo, changed)
        graph = scan_repository(repo)
        return ImpactReportPayload.from_report(
            analyze_impact(repo, graph, paths, max_depth=max_depth)
        )

    def analyze_worktree(
        self,
        *,
        repository: str = ".",
        base: str | None = None,
        max_depth: int = 4,
    ) -> ImpactReportPayload:
        """Analyze the repository's current Git changes or a base comparison."""
        repo = self.access.repository(repository)
        invalid_base = base is not None and (
            not base or base.startswith("-") or any(ch.isspace() for ch in base)
        )
        if invalid_base:
            raise ValueError("base must be a non-empty Git revision without whitespace")
        paths = self.access.changed_paths(repo, changed_files(repo, base))
        graph = scan_repository(repo)
        return ImpactReportPayload.from_report(
            analyze_impact(repo, graph, paths, max_depth=max_depth)
        )


def create_server(root: Path) -> MCPServer:
    """Create a RepoRipple MCP server constrained to ``root``."""
    service = RepoRippleMCPService(root)
    server = MCPServer(
        "reporipple",
        title="RepoRipple",
        description="Deterministic, read-only repository change-impact analysis.",
        instructions=(
            "Use forecast_change before editing to estimate a proposed change's blast radius. "
            "Use analyze_worktree after editing to inspect the actual Git changes. "
            "Results are deterministic and include dependency paths, risk reasons, and tests."
        ),
        version=__version__,
        log_level="WARNING",
    )
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @server.tool(
        title="Forecast a code change",
        annotations=read_only,
        structured_output=True,
    )
    def forecast_change(
        changed_files: ChangedFilesArgument,
        repository: RepositoryArgument = ".",
        max_depth: MaxDepthArgument = 4,
    ) -> ImpactReportPayload:
        """Estimate the blast radius of proposed repository-relative file changes."""
        return service.forecast_change(
            changed_files,
            repository=repository,
            max_depth=max_depth,
        )

    @server.tool(
        title="Analyze current Git changes",
        annotations=read_only,
        structured_output=True,
    )
    def analyze_worktree(
        repository: RepositoryArgument = ".",
        base: BaseArgument = None,
        max_depth: MaxDepthArgument = 4,
    ) -> ImpactReportPayload:
        """Analyze worktree changes, or compare HEAD with an optional Git base revision."""
        return service.analyze_worktree(
            repository=repository,
            base=base,
            max_depth=max_depth,
        )

    return server


def run_server(root: Path) -> None:
    """Run RepoRipple over stdio without writing non-protocol data to stdout."""
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    LOGGER.info("Starting RepoRipple MCP server with allowed root %s", root)
    create_server(root).run(transport="stdio")
