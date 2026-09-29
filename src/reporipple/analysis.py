"""Change-impact analysis over a repository dependency graph."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from reporipple.models import ImpactedFile, ImpactReport, RepositoryGraph, RiskLevel

HIGH_RISK_MARKERS = {
    "auth",
    "authorization",
    "billing",
    "checkout",
    "database",
    "migration",
    "payment",
    "permissions",
    "security",
}
SENSITIVE_TOKEN_ALIASES = {
    "auth": "auth",
    "authentication": "auth",
    "authentications": "auth",
    "authorization": "authorization",
    "authorizations": "authorization",
    "billing": "billing",
    "billings": "billing",
    "checkout": "checkout",
    "checkouts": "checkout",
    "database": "database",
    "databases": "database",
    "migration": "migration",
    "migrations": "migration",
    "payment": "payment",
    "payments": "payment",
    "permission": "permissions",
    "permissions": "permissions",
    "security": "security",
    "securities": "security",
}
CONFIG_NAMES = {
    "dockerfile",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements.txt",
    "vercel.json",
}
DOC_EXTENSIONS = {".md", ".mdx", ".rst"}


def analyze_impact(
    root: Path,
    graph: RepositoryGraph,
    changed: list[str],
    *,
    max_depth: int = 4,
) -> ImpactReport:
    """Trace reverse dependencies from changed files and produce review guidance."""
    normalized_changed = sorted({_normalize(path) for path in changed})
    impacted = _trace_impacted(graph, normalized_changed, max_depth)
    all_relevant = set(normalized_changed) | {item.path for item in impacted}
    tests = _suggest_tests(root, graph.files, all_relevant)
    docs = _documentation_to_review(root, normalized_changed, impacted)
    risk_level, reasons = _risk(normalized_changed, impacted, tests)

    return ImpactReport(
        repository=root.resolve().name,
        changed_files=normalized_changed,
        impacted_files=impacted,
        suggested_tests=tests,
        documentation_to_review=docs,
        risk_level=risk_level,
        risk_reasons=reasons,
        graph_files=len(graph.files),
        graph_edges=len(graph.edges),
        warnings=graph.warnings,
    )


def _trace_impacted(
    graph: RepositoryGraph, changed: list[str], max_depth: int
) -> list[ImpactedFile]:
    reverse = graph.reverse_dependencies
    changed_set = set(changed)
    queue: deque[tuple[str, int, tuple[str, ...]]] = deque(
        (path, 0, (path,)) for path in changed if path in graph.files
    )
    best_distance: dict[str, int] = {}
    best_path: dict[str, tuple[str, ...]] = {}

    while queue:
        current, distance, chain = queue.popleft()
        if distance >= max_depth:
            continue
        for dependent in sorted(reverse.get(current, set())):
            next_distance = distance + 1
            if dependent in changed_set:
                continue
            if dependent in best_distance and best_distance[dependent] <= next_distance:
                continue
            next_chain = (*chain, dependent)
            best_distance[dependent] = next_distance
            best_path[dependent] = next_chain
            queue.append((dependent, next_distance, next_chain))

    return [
        ImpactedFile(path=path, distance=best_distance[path], via=best_path[path])
        for path in sorted(best_distance, key=lambda item: (best_distance[item], item))
    ]


def _suggest_tests(root: Path, files: set[str], relevant: set[str]) -> list[str]:
    tests = {
        path
        for path in files
        if _is_test(path) and (path in relevant or _test_matches_source(path, relevant))
    }
    if tests:
        return sorted(tests)

    commands: list[str] = []
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        commands.append("pytest")
    if (root / "package.json").exists():
        commands.append("npm test")
    return commands


def _is_test(path: str) -> bool:
    lowered = path.lower()
    name = Path(path).name.lower()
    return (
        "tests" in Path(lowered).parts
        or "__tests__" in Path(lowered).parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _test_matches_source(test_path: str, relevant: set[str]) -> bool:
    test_stem = Path(test_path).stem.lower()
    for prefix in ("test_",):
        if test_stem.startswith(prefix):
            test_stem = test_stem[len(prefix) :]
    test_stem = test_stem.removesuffix(".test").removesuffix(".spec")
    return any(
        Path(source).stem.lower() == test_stem for source in relevant if not _is_test(source)
    )


def _documentation_to_review(
    root: Path, changed: list[str], impacted: list[ImpactedFile]
) -> list[str]:
    if all(Path(path).suffix.lower() in DOC_EXTENSIONS for path in changed):
        return []
    candidates = ["README.md", "docs", "CHANGELOG.md"]
    docs = [candidate for candidate in candidates if (root / candidate).exists()]
    if len(impacted) < 3 and not any(Path(path).name.lower() in CONFIG_NAMES for path in changed):
        return []
    return docs


def _risk(
    changed: list[str], impacted: list[ImpactedFile], tests: list[str]
) -> tuple[RiskLevel, list[str]]:
    reasons: list[str] = []
    score = 0
    names = {Path(path).name.lower() for path in changed}

    sensitive = sorted({concept for path in changed for concept in _sensitive_concepts(path)})
    if sensitive:
        score += 3
        reasons.append(f"Sensitive area changed: {', '.join(sensitive)}")
    sensitive_impacted = [
        (item.path, sorted(_sensitive_concepts(item.path)))
        for item in impacted
        if not _is_test(item.path) and Path(item.path).suffix.lower() not in DOC_EXTENSIONS
    ]
    sensitive_impacted = [item for item in sensitive_impacted if item[1]]
    if sensitive_impacted:
        score += 2
        reasons.append(
            "Sensitive dependent files affected: " + _format_sensitive_files(sensitive_impacted)
        )
    if CONFIG_NAMES & names:
        score += 2
        reasons.append("Runtime, dependency, or deployment configuration changed")
    if len(impacted) >= 10:
        score += 3
        reasons.append(f"Wide blast radius: {len(impacted)} dependent files")
    elif len(impacted) >= 4:
        score += 2
        reasons.append(f"Moderate blast radius: {len(impacted)} dependent files")
    if not tests and any(Path(path).suffix.lower() not in DOC_EXTENSIONS for path in changed):
        score += 1
        reasons.append("No matching tests or test command detected")

    if not reasons:
        reasons.append("Localized change with a small dependency radius")
    level: RiskLevel = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return level, reasons


def _sensitive_concepts(path: str) -> set[str]:
    concepts: set[str] = set()
    for component in Path(path).parts:
        # Keep concepts distinct: ``prepayment`` should not match ``payment``, while
        # payment_service, payment-service, and paymentService should all match.
        separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", component)
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", separated)
        for token in re.findall(r"[A-Za-z0-9]+", separated):
            if concept := SENSITIVE_TOKEN_ALIASES.get(token.lower()):
                concepts.add(concept)
    return concepts


def _format_sensitive_files(files: list[tuple[str, list[str]]], limit: int = 3) -> str:
    ordered = sorted(files, key=lambda item: item[0])
    rendered = [f"{path} ({', '.join(concepts)})" for path, concepts in ordered[:limit]]
    if len(ordered) > limit:
        rendered.append(f"+{len(ordered) - limit} more")
    return "; ".join(rendered)


def _normalize(path: str) -> str:
    return Path(path).as_posix().removeprefix("./")
