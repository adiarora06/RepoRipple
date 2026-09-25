"""Domain models for repository scans and impact reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str
    kind: str


@dataclass
class RepositoryGraph:
    files: set[str] = field(default_factory=set)
    edges: list[DependencyEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def reverse_dependencies(self) -> dict[str, set[str]]:
        reverse: dict[str, set[str]] = {path: set() for path in self.files}
        for edge in self.edges:
            reverse.setdefault(edge.target, set()).add(edge.source)
        return reverse


@dataclass(frozen=True)
class ImpactedFile:
    path: str
    distance: int
    via: tuple[str, ...]


@dataclass
class ImpactReport:
    repository: str
    changed_files: list[str]
    impacted_files: list[ImpactedFile]
    suggested_tests: list[str]
    documentation_to_review: list[str]
    risk_level: RiskLevel
    risk_reasons: list[str]
    graph_files: int
    graph_edges: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
