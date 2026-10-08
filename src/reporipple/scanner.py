"""Repository discovery and dependency extraction."""

from __future__ import annotations

import ast
import fnmatch
import os
import posixpath
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from reporipple.config import (
    IGNORED_DIRECTORIES,
    JAVASCRIPT_EXTENSIONS,
    MAX_SOURCE_FILE_BYTES,
    SOURCE_EXTENSIONS,
)
from reporipple.filesystem import read_repository_bytes
from reporipple.javascript import JavaScriptResolver
from reporipple.models import DependencyEdge, RepositoryGraph


@dataclass(frozen=True)
class _GitignoreRule:
    base: tuple[str, ...]
    pattern: tuple[str, ...]
    match_anywhere: bool
    directory_only: bool
    negated: bool


def discover_source_files(root: Path) -> set[str]:
    """Return normalized source paths while excluding generated and dependency directories."""
    root = root.resolve()
    files: set[str] = set()
    ignore_rules: list[_GitignoreRule] = []

    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        current_relative = current_path.relative_to(root)
        _append_gitignore_rules(current_path / ".gitignore", current_relative, ignore_rules)

        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = current_path / name
            relative = path.relative_to(root)
            if (
                name in IGNORED_DIRECTORIES
                or path.is_symlink()
                or _is_gitignored(relative, is_directory=True, rules=ignore_rules)
            ):
                continue
            kept_directories.append(name)
        # os.walk only avoids descending into an ignored tree when its list is mutated in place.
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            path = current_path / name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix.lower() not in SOURCE_EXTENSIONS
            ):
                continue
            relative = path.relative_to(root)
            if _is_gitignored(relative, is_directory=False, rules=ignore_rules):
                continue
            files.add(relative.as_posix())
    return files


def scan_repository(
    root: Path,
    virtual_files: Mapping[str, str] | None = None,
) -> RepositoryGraph:
    """Build an import graph, optionally overlaying in-memory source file contents.

    Virtual files use repository-relative POSIX paths. They may replace a file on disk or add a
    source or configuration file that no longer exists, such as pre-change content from Git.
    """
    root = root.resolve()
    files = discover_source_files(root)
    virtual_overlays = _normalize_virtual_files(virtual_files)
    virtual_sources = {
        path: content
        for path, content in virtual_overlays.items()
        if PurePosixPath(path).suffix.lower() in SOURCE_EXTENSIONS
    }
    files.update(virtual_sources)
    graph = RepositoryGraph(files=files)
    python_modules = _python_module_index(files, graph.warnings)
    javascript = JavaScriptResolver(
        root,
        files,
        graph.warnings,
        virtual_files=virtual_overlays,
    )

    for relative in sorted(files):
        path = root / relative
        if relative in virtual_sources:
            content = virtual_sources[relative]
            try:
                encoded_size = len(content.encode("utf-8"))
            except UnicodeEncodeError as exc:
                graph.warnings.append(f"Could not read {relative}: {exc}")
                continue
            if encoded_size > MAX_SOURCE_FILE_BYTES:
                graph.warnings.append(_oversized_source_warning(relative))
                continue
        else:
            try:
                raw_content = read_repository_bytes(root, relative, MAX_SOURCE_FILE_BYTES)
                if len(raw_content) > MAX_SOURCE_FILE_BYTES:
                    graph.warnings.append(_oversized_source_warning(relative))
                    continue
                content = raw_content.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                graph.warnings.append(f"Could not read {relative}: {exc}")
                continue

        if path.suffix.lower() == ".py":
            graph.edges.extend(_python_edges(relative, content, python_modules, graph.warnings))
        elif path.suffix.lower() in JAVASCRIPT_EXTENSIONS:
            graph.edges.extend(_javascript_edges(relative, content, javascript))

    graph.edges = sorted(set(graph.edges), key=lambda edge: (edge.source, edge.target, edge.kind))
    return graph


def _append_gitignore_rules(
    gitignore: Path,
    relative_directory: Path,
    rules: list[_GitignoreRule],
) -> None:
    if gitignore.is_symlink():
        return
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return

    base = () if relative_directory == Path(".") else relative_directory.parts
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith(r"\#") or line.startswith(r"\!"):
            line = line[1:]
        elif line.startswith("#"):
            continue

        negated = line.startswith("!")
        if negated:
            line = line[1:]
        directory_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = line.startswith("/")
        line = line.lstrip("/")
        if not line:
            continue

        rules.append(
            _GitignoreRule(
                base=base,
                pattern=tuple(part for part in line.split("/") if part),
                match_anywhere=not anchored and "/" not in line,
                directory_only=directory_only,
                negated=negated,
            )
        )


def _is_gitignored(
    relative: Path,
    *,
    is_directory: bool,
    rules: list[_GitignoreRule],
) -> bool:
    parts = relative.parts
    ignored = False
    for rule in rules:
        if parts[: len(rule.base)] != rule.base:
            continue
        local_parts = parts[len(rule.base) :]
        candidate_count = len(local_parts) if is_directory else len(local_parts) - 1
        prefix_limit = candidate_count if rule.directory_only else len(local_parts)
        if prefix_limit <= 0:
            continue

        matched = False
        for length in range(1, prefix_limit + 1):
            candidate = local_parts[:length]
            if rule.match_anywhere:
                matched = fnmatch.fnmatchcase(candidate[-1], rule.pattern[0])
            else:
                matched = _match_gitignore_parts(rule.pattern, candidate)
            if matched:
                break
        if matched:
            ignored = not rule.negated
    return ignored


def _match_gitignore_parts(pattern: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    if not pattern:
        return not candidate
    if pattern[0] == "**":
        return (
            _match_gitignore_parts(pattern[1:], candidate)
            or bool(candidate)
            and (_match_gitignore_parts(pattern, candidate[1:]))
        )
    if not candidate or not fnmatch.fnmatchcase(candidate[0], pattern[0]):
        return False
    return _match_gitignore_parts(pattern[1:], candidate[1:])


def _normalize_virtual_files(virtual_files: Mapping[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if virtual_files is None:
        return normalized

    for raw_path, content in sorted(virtual_files.items(), key=lambda item: str(item[0])):
        if not isinstance(content, str):
            raise TypeError(f"Virtual source content for {raw_path!s} must be text")
        candidate = str(raw_path).replace("\\", "/")
        path = PurePosixPath(candidate)
        if path.is_absolute() or ".." in path.parts or "\x00" in candidate:
            raise ValueError(f"Virtual source path must stay inside the repository: {raw_path!s}")
        relative = posixpath.normpath(candidate)
        if relative in {"", "."}:
            raise ValueError("Virtual file path cannot be empty")
        if any(part in IGNORED_DIRECTORIES for part in PurePosixPath(relative).parts):
            continue
        if relative in normalized:
            raise ValueError(f"Duplicate virtual file path after normalization: {relative}")
        normalized[relative] = content
    return normalized


def _normalize_virtual_sources(virtual_files: Mapping[str, str] | None) -> dict[str, str]:
    """Compatibility helper returning only supported source overlays."""
    return {
        path: content
        for path, content in _normalize_virtual_files(virtual_files).items()
        if PurePosixPath(path).suffix.lower() in SOURCE_EXTENSIONS
    }


def _oversized_source_warning(relative: str) -> str:
    return f"Skipped {relative}: source is larger than {MAX_SOURCE_FILE_BYTES} bytes"


def _python_module_index(
    files: Iterable[str],
    warnings: list[str] | None = None,
) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    file_set = set(files)
    for relative in sorted(file_set):
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
            candidates.setdefault(module, set()).add(relative)
        # Also index package roots so `from package import module` can resolve.
        for length in range(1, len(parts)):
            prefix = ".".join(parts[:length])
            init_candidates = [
                Path("src", *parts[:length], "__init__.py").as_posix(),
                Path(*parts[:length], "__init__.py").as_posix(),
            ]
            for candidate in init_candidates:
                if candidate in file_set:
                    candidates.setdefault(prefix, set()).add(candidate)

    index: dict[str, str] = {}
    for module in sorted(candidates):
        matches = sorted(candidates[module])
        index[module] = matches[0]
        if warnings is not None and len(matches) > 1:
            warnings.append(
                f"Ambiguous Python module {module!r}: {', '.join(matches)}; using {matches[0]}"
            )
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


def _javascript_edges(
    source: str,
    content: str,
    resolver: JavaScriptResolver,
) -> list[DependencyEdge]:
    return [
        DependencyEdge(source=source, target=target, kind="js-import")
        for _, target in resolver.imports(source, content)
    ]
