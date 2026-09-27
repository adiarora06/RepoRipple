"""Repository discovery and dependency extraction."""

from __future__ import annotations

import ast
import posixpath
import re
from pathlib import Path

from reporipple.config import IGNORED_DIRECTORIES, JAVASCRIPT_EXTENSIONS, SOURCE_EXTENSIONS
from reporipple.models import DependencyEdge, RepositoryGraph

JS_IMPORT_PATTERN = re.compile(
    r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
    r"|import\(\s*['\"]([^'\"]+)['\"]\s*\)"
)


def discover_source_files(root: Path) -> set[str]:
    """Return normalized source paths while excluding generated and dependency directories."""
    root = root.resolve()
    files: set[str] = set()
    for path in root.rglob("*"):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in SOURCE_EXTENSIONS
        ):
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        files.add(relative.as_posix())
    return files


def scan_repository(root: Path) -> RepositoryGraph:
    """Build a local import graph for supported Python and JavaScript-family files."""
    root = root.resolve()
    files = discover_source_files(root)
    graph = RepositoryGraph(files=files)
    python_modules = _python_module_index(files)

    for relative in sorted(files):
        path = root / relative
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            graph.warnings.append(f"Could not read {relative}: {exc}")
            continue

        if path.suffix == ".py":
            graph.edges.extend(_python_edges(relative, content, python_modules, graph.warnings))
        elif path.suffix.lower() in JAVASCRIPT_EXTENSIONS:
            graph.edges.extend(_javascript_edges(relative, content, files))

    graph.edges = sorted(set(graph.edges), key=lambda edge: (edge.source, edge.target, edge.kind))
    return graph


def _python_module_index(files: set[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for relative in files:
        if not relative.endswith(".py"):
            continue
        path = Path(relative)
        parts = list(path.with_suffix("").parts)
        if parts and parts[0] == "src":
            parts = parts[1:]
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        module = ".".join(parts)
        if module:
            index[module] = relative
        # Also index package roots so `from package import module` can resolve.
        for length in range(1, len(parts)):
            prefix = ".".join(parts[:length])
            init_candidates = [
                Path("src", *parts[:length], "__init__.py").as_posix(),
                Path(*parts[:length], "__init__.py").as_posix(),
            ]
            for candidate in init_candidates:
                if candidate in files:
                    index.setdefault(prefix, candidate)
    return index


def _python_edges(
    source: str,
    content: str,
    module_index: dict[str, str],
    warnings: list[str],
) -> list[DependencyEdge]:
    try:
        tree = ast.parse(content, filename=source)
    except SyntaxError as exc:
        warnings.append(f"Could not parse {source}:{exc.lineno}: {exc.msg}")
        return []

    source_module = _module_for_path(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_python_from(source_module, node.module or "", node.level)
            if base:
                imports.add(base)
                imports.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")

    edges: list[DependencyEdge] = []
    for imported in imports:
        target = _closest_python_target(imported, module_index)
        if target and target != source:
            edges.append(DependencyEdge(source=source, target=target, kind="python-import"))
    return edges


def _module_for_path(relative: str) -> str:
    parts = list(Path(relative).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_python_from(source_module: str, module: str, level: int) -> str:
    if level == 0:
        return module
    package = source_module.split(".")[:-1]
    keep = max(0, len(package) - level + 1)
    prefix = package[:keep]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def _closest_python_target(imported: str, module_index: dict[str, str]) -> str | None:
    candidate = imported
    while candidate:
        if candidate in module_index:
            return module_index[candidate]
        candidate = candidate.rpartition(".")[0]
    return None


def _javascript_edges(source: str, content: str, files: set[str]) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []
    for match in JS_IMPORT_PATTERN.finditer(content):
        specifier = next(group for group in match.groups() if group is not None)
        if not specifier.startswith("."):
            continue
        target = _resolve_javascript_target(source, specifier, files)
        if target and target != source:
            edges.append(DependencyEdge(source=source, target=target, kind="js-import"))
    return edges


def _resolve_javascript_target(source: str, specifier: str, files: set[str]) -> str | None:
    base = (Path(source).parent / specifier).as_posix()
    normalized = posixpath.normpath(base)
    candidates = [normalized]
    candidates.extend(f"{normalized}{extension}" for extension in JAVASCRIPT_EXTENSIONS)
    candidates.extend(
        (Path(normalized) / f"index{extension}").as_posix()
        for extension in JAVASCRIPT_EXTENSIONS
    )
    return next((candidate for candidate in candidates if candidate in files), None)
