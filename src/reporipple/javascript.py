"""Deterministic JavaScript and TypeScript import resolution."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from reporipple.config import MAX_SOURCE_FILE_BYTES
from reporipple.filesystem import read_repository_bytes

JS_IMPORT_PATTERN = re.compile(
    r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
    r"|import\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
_MAX_CONFIG_DEPTH = 16
_MAX_EXPORT_DEPTH = 64
_MAX_WORKSPACE_BRACE_EXPANSIONS = 64
_MAX_WORKSPACE_MATCH_STATES = 100_000
_MAX_WORKSPACE_PATTERN_PARTS = 256
_MAX_EFFECTIVE_WORKSPACE_PATTERNS = 512
_MAX_WORKSPACE_PATTERN_COMPARISONS = 100_000
_MAX_WORKSPACE_PATTERN_COMPONENTS = 2_048
_MAX_WORKSPACE_PATTERN_BYTES = 65_536
_MAX_EXPANDED_WORKSPACE_PATTERN_BYTES = 262_144
_IMPORT_CONDITIONS = frozenset({"import"})
_REQUIRE_CONDITIONS = frozenset({"require"})
_AMBIGUOUS_MODULE_CONDITIONS = frozenset({"import", "require"})
_EXPLICIT_EXTENSION_SUBSTITUTIONS = {
    ".js": (".ts", ".tsx", ".d.ts", ".js", ".jsx"),
    ".jsx": (".tsx", ".ts", ".d.ts", ".jsx", ".js"),
    ".mjs": (".mts", ".d.mts", ".mjs"),
    ".cjs": (".cts", ".d.cts", ".cjs"),
}
_EXTENSIONLESS_CANDIDATES = (
    ".ts",
    ".tsx",
    ".d.ts",
    ".js",
    ".jsx",
)
_JAVASCRIPT_EXTENSIONLESS_CANDIDATES = (
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".d.ts",
)


@dataclass(frozen=True)
class _PathRule:
    pattern: str
    targets: tuple[str, ...]
    config_directory: Path
    order: int


@dataclass(frozen=True)
class _ProjectConfig:
    base_url: Path | None = None
    path_rules: tuple[_PathRule, ...] = ()
    defines_base_url: bool = False
    defines_path_rules: bool = False


@dataclass(frozen=True)
class _WorkspacePackage:
    name: str
    directory: Path
    manifest: Mapping[str, Any]
    historical: bool = False


@dataclass(frozen=True)
class _ConditionalTargets:
    targets: tuple[str, ...] = ()
    blocked: bool = False
    undefined: bool = False
    invalid: bool = False


class JavaScriptResolver:
    """Resolve local JS/TS imports without executing repository configuration."""

    def __init__(
        self,
        root: Path,
        files: set[str],
        warnings: list[str],
        *,
        virtual_files: Mapping[str, str] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.files = frozenset(files)
        self.warnings = warnings
        self.virtual_files = dict(virtual_files or {})
        self._warning_set = set(warnings)
        self._config_cache: dict[str, _ProjectConfig | None] = {}
        self._source_config_cache: dict[str, _ProjectConfig | None] = {}
        self._manifest_cache: dict[str, Mapping[str, Any] | None] = {}
        self._workspaces = self._build_workspace_index()

    def imports(self, source: str, content: str) -> list[tuple[str, str]]:
        """Return resolved ``(specifier, target)`` pairs for one source file."""
        # Load the nearest config even when this file only uses relative imports so malformed or
        # cyclic project configuration remains visible in scanner warnings.
        self._nearest_config(source)
        resolved: list[tuple[str, str]] = []
        source_suffix = PurePosixPath(source).suffix.lower()
        for match in JS_IMPORT_PATTERN.finditer(content):
            static_import, require_import, dynamic_import = match.groups()
            specifier = static_import or require_import or dynamic_import
            if require_import is not None or (
                static_import is not None and source_suffix in {".cjs", ".cts"}
            ):
                conditions = _REQUIRE_CONDITIONS
            elif dynamic_import is not None or source_suffix in {".mjs", ".mts"}:
                conditions = _IMPORT_CONDITIONS
            else:
                conditions = _AMBIGUOUS_MODULE_CONDITIONS
            for target in self.resolve(source, specifier, conditions=conditions):
                if target != source:
                    resolved.append((specifier, target))
        return resolved

    def resolve(
        self,
        source: str,
        specifier: str,
        *,
        conditions: frozenset[str] = _IMPORT_CONDITIONS,
    ) -> tuple[str, ...]:
        """Resolve one import using relative, config, then workspace semantics."""
        if not specifier or "\x00" in specifier:
            return ()
        prefer_typescript = PurePosixPath(source).suffix.lower() in {
            ".ts",
            ".tsx",
            ".mts",
            ".cts",
        }
        if specifier.startswith("."):
            target = self._resolve_from(
                Path(source).parent,
                specifier,
                prefer_typescript=prefer_typescript,
            )
            return (target,) if target is not None else ()
        if specifier.startswith("/"):
            return ()

        config = self._nearest_config(source)
        if config is not None:
            target = self._resolve_paths(
                config,
                specifier,
                prefer_typescript=prefer_typescript,
            )
            if target is not None:
                return (target,)
            if config.base_url is not None:
                target = self._resolve_absolute_base(
                    config.base_url,
                    specifier,
                    prefer_typescript=prefer_typescript,
                )
                if target is not None:
                    return (target,)

        if specifier.startswith("#"):
            return ()
        return self._resolve_workspace(
            specifier,
            conditions,
            prefer_typescript=prefer_typescript,
        )

    def _nearest_config(self, source: str) -> _ProjectConfig | None:
        parent = PurePosixPath(source).parent
        key = parent.as_posix()
        if key in self._source_config_cache:
            return self._source_config_cache[key]

        current = parent
        while True:
            for name in _CONFIG_NAMES:
                candidate = (current / name).as_posix()
                if self._metadata_exists(candidate):
                    config = self._load_project_config(candidate, ())
                    self._source_config_cache[key] = config
                    return config
            if current == PurePosixPath("."):
                break
            current = current.parent

        self._source_config_cache[key] = None
        return None

    def _load_project_config(
        self,
        relative: str,
        stack: tuple[str, ...],
    ) -> _ProjectConfig | None:
        if relative in self._config_cache:
            return self._config_cache[relative]
        if relative in stack:
            self._warn(f"JavaScript configuration extends cycle detected at {relative}")
            return _ProjectConfig()
        if len(stack) >= _MAX_CONFIG_DEPTH:
            self._warn(f"JavaScript configuration extends depth exceeded at {relative}")
            return _ProjectConfig()

        payload = self._read_json(relative, jsonc=True, label="JavaScript configuration")
        if payload is None:
            self._config_cache[relative] = None
            return None

        parent = _ProjectConfig()
        extends = payload.get("extends")
        if isinstance(extends, str):
            extend_values: list[object] = [extends]
        elif isinstance(extends, list):
            extend_values = extends
        elif extends is None:
            extend_values = []
        else:
            extend_values = [extends]

        for extend_value in extend_values:
            if not isinstance(extend_value, str) or not extend_value:
                self._warn(f"Invalid extends value in {relative}; expected relative strings")
                continue
            if not extend_value.startswith("."):
                self._warn(f"Unsupported package-based extends in {relative}: {extend_value!r}")
                continue
            inherited = self._resolve_extends(relative, extend_value)
            if inherited is not None:
                loaded = self._load_project_config(inherited, (*stack, relative))
                if loaded is not None:
                    parent = _merge_project_configs(parent, loaded)

        compiler = payload.get("compilerOptions", {})
        if not isinstance(compiler, dict):
            self._warn(f"Invalid compilerOptions in {relative}; expected an object")
            compiler = {}

        base_url = parent.base_url
        defines_base_url = parent.defines_base_url
        config_directory = self.root / PurePosixPath(relative).parent
        if "baseUrl" in compiler:
            defines_base_url = True
            raw_base = compiler.get("baseUrl")
            if isinstance(raw_base, str) and raw_base and "\x00" not in raw_base:
                candidate = self._resolve_path(
                    config_directory / raw_base,
                    f"baseUrl in {relative}",
                )
                if candidate is None:
                    base_url = None
                elif self._inside(candidate, self.root):
                    base_url = candidate
                else:
                    base_url = None
                    self._warn(
                        f"baseUrl in {relative} resolves outside the repository and was ignored"
                    )
            else:
                base_url = None
                self._warn(f"Invalid baseUrl in {relative}; expected a non-empty string")

        path_rules = parent.path_rules
        defines_path_rules = parent.defines_path_rules
        if "paths" in compiler:
            defines_path_rules = True
            raw_paths = compiler.get("paths")
            path_rules = self._path_rules(
                relative,
                raw_paths,
                config_directory,
            )

        config = _ProjectConfig(
            base_url=base_url,
            path_rules=path_rules,
            defines_base_url=defines_base_url,
            defines_path_rules=defines_path_rules,
        )
        self._config_cache[relative] = config
        return config

    def _resolve_extends(self, owner: str, value: str) -> str | None:
        owner_directory = self.root / PurePosixPath(owner).parent
        candidate = self._resolve_path(
            owner_directory / value,
            f"extends target in {owner}",
        )
        if candidate is None:
            return None
        if not self._inside(candidate, self.root):
            self._warn(f"extends in {owner} resolves outside the repository and was ignored")
            return None

        candidates = [candidate]
        if not candidate.suffix:
            candidates.insert(0, candidate.with_suffix(".json"))
            candidates.append(candidate / "tsconfig.json")
        for path in candidates:
            relative = path.relative_to(self.root).as_posix()
            if self._metadata_exists(relative):
                return relative
        self._warn(f"Relative extends target in {owner} was not found: {value!r}")
        return None

    def _path_rules(
        self,
        owner: str,
        raw_paths: object,
        config_directory: Path,
    ) -> tuple[_PathRule, ...]:
        if not isinstance(raw_paths, dict):
            self._warn(f"Invalid paths in {owner}; expected an object")
            return ()

        rules: list[_PathRule] = []
        for order, (pattern, raw_targets) in enumerate(raw_paths.items()):
            if (
                not isinstance(pattern, str)
                or not pattern
                or "\x00" in pattern
                or pattern.count("*") > 1
            ):
                self._warn(f"Invalid paths pattern in {owner}: {pattern!r}")
                continue
            if not isinstance(raw_targets, list):
                self._warn(f"Invalid paths targets for {pattern!r} in {owner}")
                continue
            targets = tuple(
                target
                for target in raw_targets
                if isinstance(target, str)
                and target
                and "\x00" not in target
                and target.count("*") <= 1
            )
            if not targets:
                self._warn(f"No usable paths targets for {pattern!r} in {owner}")
                continue
            rules.append(
                _PathRule(
                    pattern=pattern,
                    targets=targets,
                    config_directory=config_directory,
                    order=order,
                )
            )
        return tuple(rules)

    def _resolve_paths(
        self,
        config: _ProjectConfig,
        specifier: str,
        *,
        prefer_typescript: bool,
    ) -> str | None:
        matches: list[tuple[tuple[int, int, int], _PathRule, str]] = []
        for rule in config.path_rules:
            capture = _match_pattern(rule.pattern, specifier)
            if capture is None:
                continue
            prefix, _, _ = rule.pattern.partition("*")
            score = (
                int("*" not in rule.pattern),
                len(prefix),
                -rule.order,
            )
            matches.append((score, rule, capture))
        if not matches:
            return None

        _, rule, capture = max(matches, key=lambda item: item[0])
        for target_pattern in rule.targets:
            target_value = target_pattern.replace("*", capture)
            target = self._resolve_absolute_base(
                config.base_url or rule.config_directory,
                target_value,
                prefer_typescript=prefer_typescript,
            )
            if target is not None:
                return target
        return None

    def _resolve_workspace(
        self,
        specifier: str,
        conditions: frozenset[str],
        *,
        prefer_typescript: bool,
    ) -> tuple[str, ...]:
        matches = [
            name
            for name in self._workspaces
            if specifier == name or specifier.startswith(f"{name}/")
        ]
        if not matches:
            return ()
        name = min(matches, key=lambda item: (-len(item), item))
        package = self._workspaces[name]
        suffix = specifier[len(name) :]
        if not _valid_workspace_request_suffix(suffix):
            return ()
        subpath = "." if not suffix else f".{suffix}"
        return self._workspace_targets(
            package,
            subpath,
            conditions,
            prefer_typescript=prefer_typescript,
        )

    def _workspace_targets(
        self,
        package: _WorkspacePackage,
        subpath: str,
        conditions: frozenset[str],
        *,
        prefer_typescript: bool,
    ) -> tuple[str, ...]:
        manifest = package.manifest
        exports = manifest.get("exports")
        if exports is not None:
            matched, export_value, capture = _select_export(exports, subpath)
            if not matched or (capture and not _valid_package_path_segments(capture)):
                return ()
            targets, has_local_candidate = self._resolve_export_targets(
                package,
                export_value,
                capture,
                conditions,
                prefer_typescript=prefer_typescript,
            )
            if targets:
                return targets
            if subpath == "." and has_local_candidate:
                source = manifest.get("source")
                if isinstance(source, str):
                    target = self._resolve_package_path(
                        package,
                        source,
                        prefer_typescript=prefer_typescript,
                    )
                    if target is not None:
                        return (target,)
            return ()

        if subpath != ".":
            target = self._resolve_package_path(
                package,
                subpath.removeprefix("./"),
                prefer_typescript=prefer_typescript,
            )
            return (target,) if target is not None else ()

        for field in ("source", "module", "main"):
            value = manifest.get(field)
            if isinstance(value, str):
                target = self._resolve_package_path(
                    package,
                    value,
                    prefer_typescript=prefer_typescript,
                )
                if target is not None:
                    return (target,)
        for fallback in ("src/index", "index"):
            target = self._resolve_package_path(
                package,
                fallback,
                prefer_typescript=prefer_typescript,
            )
            if target is not None:
                return (target,)
        return ()

    def _resolve_export_targets(
        self,
        package: _WorkspacePackage,
        value: object,
        capture: str,
        conditions: frozenset[str],
        *,
        prefer_typescript: bool,
    ) -> tuple[tuple[str, ...], bool]:
        try:
            raw_targets = _conditional_export_targets(value, conditions).targets
        except RecursionError:
            self._warn(f"Workspace export for {package.name!r} is nested too deeply")
            return (), False

        targets: list[str] = []
        has_local_candidate = False
        for raw_target in raw_targets:
            if not raw_target.startswith("./"):
                self._warn(
                    f"Workspace export for {package.name!r} must stay inside its package: "
                    f"{raw_target!r}"
                )
                continue
            candidate = self._workspace_candidate(
                package,
                raw_target.replace("*", capture),
            )
            if candidate is None:
                continue
            has_local_candidate = True
            target = self._resolve_candidate(
                candidate,
                prefer_typescript=prefer_typescript,
            )
            if target is not None and target not in targets:
                targets.append(target)
        return tuple(targets), has_local_candidate

    def _resolve_package_path(
        self,
        package: _WorkspacePackage,
        value: str,
        *,
        prefer_typescript: bool,
    ) -> str | None:
        candidate = self._workspace_candidate(package, value)
        if candidate is None:
            return None
        return self._resolve_candidate(candidate, prefer_typescript=prefer_typescript)

    def _workspace_candidate(
        self,
        package: _WorkspacePackage,
        value: str,
    ) -> Path | None:
        if not value or "\x00" in value or Path(value).is_absolute():
            self._warn(f"Invalid workspace target for {package.name!r}: {value!r}")
            return None
        candidate = self._resolve_path(
            package.directory / value,
            f"workspace target for {package.name!r}",
        )
        if candidate is None:
            return None
        if not self._inside(candidate, package.directory):
            self._warn(
                f"Workspace target for {package.name!r} resolves outside its package: {value!r}"
            )
            return None
        return candidate

    def _build_workspace_index(self) -> dict[str, _WorkspacePackage]:
        if not self._metadata_exists("package.json"):
            return {}
        root_manifest = self._read_manifest("package.json")
        if root_manifest is None:
            return {}

        candidates: list[_WorkspacePackage] = []
        patterns = _workspace_patterns(root_manifest.get("workspaces"))
        effective_patterns = _effective_workspace_patterns(patterns)
        if effective_patterns is None:
            self._warn(
                "Workspace patterns exceeded safe analysis limits; "
                "workspace imports were left unresolved"
            )
            return {}
        root_name = root_manifest.get("name")
        if (
            patterns
            and _workspace_root_is_explicitly_included(effective_patterns)
            and isinstance(root_name, str)
            and root_name
        ):
            candidates.append(_WorkspacePackage(root_name, self.root, root_manifest))

        if patterns:
            for manifest_path in self._candidate_manifest_paths():
                if manifest_path == "package.json":
                    continue
                directory_text = PurePosixPath(manifest_path).parent.as_posix()
                if not _workspace_path_matches(directory_text, effective_patterns):
                    continue
                manifest = self._read_manifest(manifest_path)
                if manifest is None:
                    continue
                name = manifest.get("name")
                if not isinstance(name, str) or not name:
                    continue
                manifest_file = self.root / PurePosixPath(manifest_path)
                directory = self._resolve_path(
                    manifest_file.parent,
                    f"workspace directory for {name!r}",
                )
                if directory is None:
                    continue
                if not self._inside(directory, self.root):
                    self._warn(
                        f"Workspace package {name!r} resolves outside the repository "
                        "and was ignored"
                    )
                    continue
                historical = manifest_path in self.virtual_files and not manifest_file.is_file()
                candidates.append(
                    _WorkspacePackage(
                        name,
                        directory,
                        manifest,
                        historical=historical,
                    )
                )

        grouped: dict[str, list[_WorkspacePackage]] = {}
        for package in candidates:
            grouped.setdefault(package.name, []).append(package)

        index: dict[str, _WorkspacePackage] = {}
        for name in sorted(grouped):
            packages = sorted(grouped[name], key=lambda item: item.directory.as_posix())
            current_packages = [package for package in packages if not package.historical]
            if len(packages) > 1 and len(current_packages) == 1:
                index[name] = current_packages[0]
                continue
            if len(packages) > 1:
                locations = ", ".join(
                    package.directory.relative_to(self.root).as_posix() or "."
                    for package in packages
                )
                self._warn(
                    f"Ambiguous workspace package {name!r}: {locations}; import left unresolved"
                )
                continue
            index[name] = packages[0]
        return index

    def _candidate_manifest_paths(self) -> list[str]:
        candidates = {
            path for path in self.virtual_files if PurePosixPath(path).name == "package.json"
        }
        for relative in self.files:
            parent = PurePosixPath(relative).parent
            while True:
                candidate = (parent / "package.json").as_posix()
                if self._metadata_exists(candidate):
                    candidates.add(candidate)
                if parent == PurePosixPath("."):
                    break
                parent = parent.parent
        return sorted(candidates)

    def _read_manifest(self, relative: str) -> Mapping[str, Any] | None:
        if relative not in self._manifest_cache:
            self._manifest_cache[relative] = self._read_json(
                relative,
                jsonc=False,
                label="Workspace manifest",
            )
        return self._manifest_cache[relative]

    def _read_json(
        self,
        relative: str,
        *,
        jsonc: bool,
        label: str,
    ) -> Mapping[str, Any] | None:
        content = self._read_metadata(relative, label)
        if content is None:
            return None
        content = content.removeprefix("\ufeff")
        try:
            payload = json.loads(_normalize_jsonc(content) if jsonc else content)
        except json.JSONDecodeError as exc:
            self._warn(f"Could not parse {label.lower()} {relative}:{exc.lineno}: {exc.msg}")
            return None
        except ValueError as exc:
            self._warn(f"Could not parse {label.lower()} {relative}: {exc}")
            return None
        except RecursionError:
            self._warn(f"Could not parse {label.lower()} {relative}: nesting is too deep")
            return None
        if not isinstance(payload, dict):
            self._warn(f"Could not parse {label.lower()} {relative}: expected an object")
            return None
        return payload

    def _read_metadata(self, relative: str, label: str) -> str | None:
        if relative in self.virtual_files:
            content = self.virtual_files[relative]
            try:
                encoded_size = len(content.encode("utf-8"))
            except UnicodeEncodeError as exc:
                self._warn(f"Could not read {label.lower()} {relative}: {exc}")
                return None
            if encoded_size > MAX_SOURCE_FILE_BYTES:
                self._warn(f"Skipped {relative}: {label.lower()} is too large")
                return None
            return content

        path = self.root
        if any(
            (path := path / component).is_symlink() for component in PurePosixPath(relative).parts
        ):
            self._warn(f"Skipped symlinked {label.lower()} {relative}")
            return None
        try:
            raw = read_repository_bytes(self.root, relative, MAX_SOURCE_FILE_BYTES)
        except OSError as exc:
            self._warn(f"Could not read {label.lower()} {relative}: {exc}")
            return None
        if len(raw) > MAX_SOURCE_FILE_BYTES:
            self._warn(f"Skipped {relative}: {label.lower()} is too large")
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._warn(f"Could not read {label.lower()} {relative}: {exc}")
            return None

    def _metadata_exists(self, relative: str) -> bool:
        if relative in self.virtual_files:
            return True
        path = self.root / PurePosixPath(relative)
        return path.is_file() or path.is_symlink()

    def _resolve_from(
        self,
        base: Path,
        value: str,
        *,
        prefer_typescript: bool,
    ) -> str | None:
        return self._resolve_absolute_base(
            self.root / base,
            value,
            prefer_typescript=prefer_typescript,
        )

    def _resolve_absolute_base(
        self,
        base: Path,
        value: str,
        *,
        prefer_typescript: bool,
    ) -> str | None:
        if not value or "\x00" in value or Path(value).is_absolute():
            return None
        candidate = self._resolve_path(base / value, f"JavaScript target {value!r}")
        if candidate is None:
            return None
        if not self._inside(candidate, self.root):
            return None
        return self._resolve_candidate(candidate, prefer_typescript=prefer_typescript)

    def _resolve_candidate(self, candidate: Path, *, prefer_typescript: bool) -> str | None:
        try:
            relative = candidate.relative_to(self.root).as_posix()
        except ValueError:
            return None
        for option in _module_candidates(relative, prefer_typescript=prefer_typescript):
            if option in self.files:
                return option
        return None

    def _resolve_path(self, candidate: Path, description: str) -> Path | None:
        if self._path_contains_symlink(candidate):
            self._warn(f"Could not resolve {description}; filesystem link or path error")
            return None
        try:
            return candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            self._warn(f"Could not resolve {description}; filesystem link or path error")
            return None

    def _path_contains_symlink(self, candidate: Path) -> bool:
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            return False
        current = self.root
        for component in relative.parts:
            current /= component
            try:
                if current.is_symlink():
                    return True
            except (OSError, ValueError):
                return True
        return False

    def _warn(self, message: str) -> None:
        if message not in self._warning_set:
            self._warning_set.add(message)
            self.warnings.append(message)

    @staticmethod
    def _inside(candidate: Path, boundary: Path) -> bool:
        try:
            candidate.relative_to(boundary)
        except ValueError:
            return False
        return True


def _match_pattern(pattern: str, specifier: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == specifier else None
    prefix, _, suffix = pattern.partition("*")
    if not specifier.startswith(prefix) or not specifier.endswith(suffix):
        return None
    if len(specifier) < len(prefix) + len(suffix):
        return None
    return specifier[len(prefix) : len(specifier) - len(suffix) if suffix else None]


def _valid_workspace_request_suffix(suffix: str) -> bool:
    if not suffix:
        return True
    if not suffix.startswith("/") or suffix == "/" or "//" in suffix or "\\" in suffix:
        return False
    return _valid_package_path_segments(suffix[1:])


def _valid_package_path_segments(value: str) -> bool:
    if not value or "//" in value or "\\" in value:
        return False
    for raw_segment in value.split("/"):
        segment = unquote(raw_segment)
        if (
            not segment
            or segment in {".", ".."}
            or segment.lower() == "node_modules"
            or "/" in segment
            or "\\" in segment
            or "\x00" in segment
        ):
            return False
    return True


def _merge_project_configs(
    base: _ProjectConfig,
    overlay: _ProjectConfig,
) -> _ProjectConfig:
    return _ProjectConfig(
        base_url=overlay.base_url if overlay.defines_base_url else base.base_url,
        path_rules=overlay.path_rules if overlay.defines_path_rules else base.path_rules,
        defines_base_url=base.defines_base_url or overlay.defines_base_url,
        defines_path_rules=base.defines_path_rules or overlay.defines_path_rules,
    )


def _module_candidates(relative: str, *, prefer_typescript: bool) -> tuple[str, ...]:
    normalized = posixpath.normpath(relative)
    path = PurePosixPath(normalized)
    candidates: list[str] = []
    suffix = path.suffix.lower()
    extensions = (
        _EXTENSIONLESS_CANDIDATES if prefer_typescript else _JAVASCRIPT_EXTENSIONLESS_CANDIDATES
    )
    if substitutions := _EXPLICIT_EXTENSION_SUBSTITUTIONS.get(suffix):
        stem = path.with_suffix("").as_posix()
        candidates.extend(f"{stem}{extension}" for extension in substitutions)
        if not prefer_typescript:
            candidates.insert(0, normalized)
    elif not suffix:
        candidates.extend(f"{normalized}{extension}" for extension in extensions)
        candidates.extend((path / f"index{extension}").as_posix() for extension in extensions)
    else:
        if suffix not in {".ts", ".tsx", ".mts", ".cts"}:
            stem = path.with_suffix("").as_posix()
            candidates.append(f"{stem}.d{suffix}.ts")
        candidates.append(normalized)
        if suffix not in {".ts", ".tsx", ".mts", ".cts"}:
            candidates.extend(f"{normalized}{extension}" for extension in extensions)
            candidates.extend((path / f"index{extension}").as_posix() for extension in extensions)
    return tuple(dict.fromkeys(candidates))


def _workspace_patterns(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        raw_patterns = value
    elif isinstance(value, dict) and isinstance(value.get("packages"), list):
        raw_patterns = value["packages"]
    else:
        return ()
    patterns: list[str] = []
    for raw_pattern in raw_patterns:
        if not isinstance(raw_pattern, str) or not raw_pattern or "\x00" in raw_pattern:
            continue
        bang_count = len(raw_pattern) - len(raw_pattern.lstrip("!"))
        negated = bang_count % 2 == 1
        pattern = raw_pattern[bang_count:].replace("\\", "/")
        while pattern.startswith("./"):
            pattern = pattern[2:]
        pattern = pattern.lstrip("/")
        pattern = pattern.rstrip("/")
        if not pattern or ".." in PurePosixPath(pattern).parts:
            continue
        patterns.append(f"!{pattern}" if negated else pattern)
    return tuple(patterns)


def _workspace_path_matches(
    path: str,
    effective_patterns: tuple[tuple[str, ...], tuple[str, ...]],
) -> bool:
    positives, negatives = effective_patterns
    return any(_workspace_pattern_matches_path(path, pattern) for pattern in positives) and not any(
        _workspace_pattern_matches_path(path, pattern) for pattern in negatives
    )


def _workspace_root_is_explicitly_included(
    effective_patterns: tuple[tuple[str, ...], tuple[str, ...]],
) -> bool:
    positives, _ = effective_patterns
    return "." in positives


def _effective_workspace_patterns(
    patterns: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """Apply npm's ordered workspace-negation behavior to bounded glob patterns."""
    if sum(_text_byte_length(pattern) for pattern in patterns) > _MAX_WORKSPACE_PATTERN_BYTES:
        return None
    unique_patterns = {pattern.removeprefix("!") for pattern in patterns}
    if (
        sum(len(PurePosixPath(pattern).parts) for pattern in unique_patterns)
        > _MAX_WORKSPACE_PATTERN_COMPONENTS
    ):
        return None
    expanded_by_pattern: dict[str, tuple[str, ...]] = {}
    expanded_bytes = 0
    for pattern in unique_patterns:
        expanded = _expand_workspace_braces(pattern)
        if not expanded:
            return None
        expanded_bytes += sum(_text_byte_length(value) for value in expanded)
        if expanded_bytes > _MAX_EXPANDED_WORKSPACE_PATTERN_BYTES:
            return None
        expanded_by_pattern[pattern] = expanded
    positives: list[str] = []
    positive_set: set[str] = set()
    negatives: list[str] = []
    negative_set: set[str] = set()
    comparisons = 0
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        if negated:
            if pattern not in negative_set:
                negatives.append(pattern)
                negative_set.add(pattern)
                if len(positive_set) + len(negative_set) > _MAX_EFFECTIVE_WORKSPACE_PATTERNS:
                    return None
            continue
        retained_negatives: list[str] = []
        for negative in negatives:
            comparisons += 1
            if comparisons > _MAX_WORKSPACE_PATTERN_COMPARISONS:
                return None
            if not _workspace_pattern_matches_expanded_path(
                pattern,
                expanded_by_pattern[negative],
            ):
                retained_negatives.append(negative)
        negatives = retained_negatives
        negative_set = set(negatives)
        if pattern not in positive_set:
            positives.append(pattern)
            positive_set.add(pattern)
            if len(positive_set) + len(negative_set) > _MAX_EFFECTIVE_WORKSPACE_PATTERNS:
                return None

    retained_positives: list[str] = []
    for positive in positives:
        excluded = False
        for negative in negatives:
            comparisons += 1
            if comparisons > _MAX_WORKSPACE_PATTERN_COMPARISONS:
                return None
            if _workspace_pattern_matches_expanded_path(
                positive,
                expanded_by_pattern[negative],
            ):
                excluded = True
                break
        if not excluded:
            retained_positives.append(positive)

    expanded_positive_values: list[str] = []
    for positive in retained_positives:
        expanded_positive_values.extend(expanded_by_pattern[positive])
    expanded_negative_values: list[str] = []
    for negative in negatives:
        expanded_negative_values.extend(expanded_by_pattern[negative])
    expanded_positives = _deduplicate(expanded_positive_values)
    expanded_negatives = _deduplicate(expanded_negative_values)
    if len(expanded_positives) + len(expanded_negatives) > _MAX_EFFECTIVE_WORKSPACE_PATTERNS:
        return None
    return expanded_positives, expanded_negatives


def _workspace_pattern_matches_expanded_path(
    path: str,
    expanded_patterns: tuple[str, ...],
) -> bool:
    return any(_workspace_pattern_matches_path(path, pattern) for pattern in expanded_patterns)


def _workspace_pattern_matches_path(path: str, pattern: str) -> bool:
    path_parts = () if path == "." else PurePosixPath(path).parts
    return _match_workspace_parts(path_parts, PurePosixPath(pattern).parts)


def _match_workspace_parts(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if len(pattern) > _MAX_WORKSPACE_PATTERN_PARTS:
        return False
    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()
    while pending and len(visited) < _MAX_WORKSPACE_MATCH_STATES:
        path_index, pattern_index = pending.pop()
        state = (path_index, pattern_index)
        if state in visited:
            continue
        visited.add(state)
        if pattern_index == len(pattern):
            if path_index == len(path):
                return True
            continue
        if pattern[pattern_index] == "**":
            pending.append((path_index, pattern_index + 1))
            if path_index < len(path) and not path[path_index].startswith("."):
                pending.append((path_index + 1, pattern_index))
            continue
        component = pattern[pattern_index]
        if (
            path_index < len(path)
            and (not path[path_index].startswith(".") or _pattern_component_allows_dot(component))
            and fnmatchcase(path[path_index], component)
        ):
            pending.append((path_index + 1, pattern_index + 1))
    return False


def _pattern_component_allows_dot(pattern: str) -> bool:
    if pattern.startswith("."):
        return True
    if pattern.startswith("[") and (closing := pattern.find("]")) > 0:
        return fnmatchcase(".", pattern[: closing + 1])
    return False


def _expand_workspace_braces(pattern: str) -> tuple[str, ...]:
    if _text_byte_length(pattern) > _MAX_WORKSPACE_PATTERN_BYTES:
        return ()
    expanded = [pattern]
    while True:
        next_patterns: list[str] = []
        expanded_bytes = 0
        changed = False
        for candidate in expanded:
            match = re.search(r"\{([^{}]+)\}", candidate)
            if match is None or (options := _brace_options(match.group(1))) is None:
                expanded_bytes += _text_byte_length(candidate)
                if expanded_bytes > _MAX_EXPANDED_WORKSPACE_PATTERN_BYTES:
                    return ()
                next_patterns.append(candidate)
                continue
            changed = True
            prefix = candidate[: match.start()]
            suffix = candidate[match.end() :]
            for option in options:
                expanded_pattern = f"{prefix}{option}{suffix}"
                expanded_bytes += _text_byte_length(expanded_pattern)
                if expanded_bytes > _MAX_EXPANDED_WORKSPACE_PATTERN_BYTES:
                    return ()
                next_patterns.append(expanded_pattern)
                if len(next_patterns) > _MAX_WORKSPACE_BRACE_EXPANSIONS:
                    return ()
        expanded = next_patterns
        if not changed:
            return tuple(expanded)


def _text_byte_length(value: str) -> int:
    return len(value.encode("utf-8", errors="surrogatepass"))


def _brace_options(expression: str) -> tuple[str, ...] | None:
    if "," in expression:
        return tuple(expression.split(","))

    parts = expression.split("..")
    if len(parts) not in {2, 3}:
        return None
    start, end = parts[:2]
    step_text = parts[2] if len(parts) == 3 else None
    if re.fullmatch(r"-?\d+", start) and re.fullmatch(r"-?\d+", end):
        start_number = _parse_range_integer(start)
        end_number = _parse_range_integer(end)
        if start_number is None or end_number is None:
            return ()
        step = _range_step(start_number, end_number, step_text)
        if step is None:
            return None
        values = _bounded_range(start_number, end_number, step)
        if values is None:
            return ()
        width = max(len(start.lstrip("-")), len(end.lstrip("-")))
        return tuple(_format_range_number(value, width, start, end) for value in values)

    if len(start) == len(end) == 1:
        start_number = ord(start)
        end_number = ord(end)
        step = _range_step(start_number, end_number, step_text)
        if step is None:
            return None
        values = _bounded_range(start_number, end_number, step)
        return () if values is None else tuple(chr(value) for value in values)
    return None


def _range_step(start: int, end: int, raw_step: str | None) -> int | None:
    if raw_step is None:
        return 1 if end >= start else -1
    if not re.fullmatch(r"-?\d+", raw_step):
        return None
    parsed_step = _parse_range_integer(raw_step)
    if parsed_step in {None, 0}:
        return None
    magnitude = abs(parsed_step)
    return magnitude if end >= start else -magnitude


def _bounded_range(start: int, end: int, step: int) -> tuple[int, ...] | None:
    stop = end + (1 if step > 0 else -1)
    values = range(start, stop, step)
    try:
        value_count = len(values)
    except OverflowError:
        return None
    if value_count > _MAX_WORKSPACE_BRACE_EXPANSIONS:
        return None
    return tuple(values)


def _parse_range_integer(value: str) -> int | None:
    if len(value.lstrip("-")) > 18:
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):
        return None


def _format_range_number(value: int, width: int, start: str, end: str) -> str:
    padded = start.lstrip("-").startswith("0") or end.lstrip("-").startswith("0")
    if not padded:
        return str(value)
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):0{width}d}"


def _select_export(exports: object, subpath: str) -> tuple[bool, object, str]:
    if isinstance(exports, dict):
        keys = tuple(exports)
        if any(not isinstance(key, str) or _is_array_index_key(key) for key in keys):
            return False, None, ""
        subpath_keys = tuple(key for key in keys if key.startswith("."))
        if subpath_keys and len(subpath_keys) != len(keys):
            return False, None, ""
        if any(key != "." and not key.startswith("./") for key in subpath_keys):
            return False, None, ""
    if isinstance(exports, dict) and any(key.startswith(".") for key in exports):
        if subpath in exports:
            return True, exports[subpath], ""
        matches: list[tuple[tuple[int, int], object, str]] = []
        for pattern, value in exports.items():
            if not isinstance(pattern, str) or not pattern.startswith("./"):
                continue
            capture = _match_pattern(pattern, subpath)
            if capture is None or "*" not in pattern:
                continue
            prefix, _, suffix = pattern.partition("*")
            matches.append(((len(prefix), len(suffix)), value, capture))
        if not matches:
            return False, None, ""
        _, value, capture = max(matches, key=lambda item: item[0])
        return True, value, capture
    if subpath == ".":
        return True, exports, ""
    return False, None, ""


def _is_array_index_key(value: str) -> bool:
    if not value or len(value) > 10 or not value.isascii() or not value.isdigit():
        return False
    number = int(value)
    return str(number) == value and number < 2**32 - 1


def _conditional_export_targets(
    value: object,
    conditions: frozenset[str],
    depth: int = 0,
) -> _ConditionalTargets:
    if depth >= _MAX_EXPORT_DEPTH:
        raise RecursionError("workspace exports nesting is too deep")
    syntax_conditions = conditions & {"import", "require"}
    if len(syntax_conditions) > 1:
        results = [
            _conditional_export_targets(value, frozenset({condition}), depth)
            for condition in sorted(syntax_conditions)
        ]
        return _ConditionalTargets(
            targets=_deduplicate(target for result in results for target in result.targets),
            blocked=any(result.blocked for result in results),
            undefined=any(result.undefined for result in results),
            invalid=any(result.invalid for result in results),
        )
    if isinstance(value, str):
        if _valid_workspace_export_target(value):
            return _ConditionalTargets((value,))
        return _ConditionalTargets(invalid=True)
    if value is None:
        return _ConditionalTargets(blocked=True)
    if isinstance(value, list):
        if not value:
            return _ConditionalTargets(blocked=True)
        candidates: list[str] = []
        continuing_states = {"undefined"}
        for child in value:
            result = _conditional_export_targets(child, conditions, depth + 1)
            candidates.extend(result.targets)
            next_states: set[str] = set()
            if result.blocked:
                next_states.add("blocked")
            if result.invalid:
                next_states.add("invalid")
            if result.undefined:
                next_states.update(continuing_states)
            continuing_states = next_states
            if not continuing_states:
                break
        return _ConditionalTargets(
            targets=_deduplicate(candidates),
            blocked="blocked" in continuing_states,
            undefined="undefined" in continuing_states,
            invalid="invalid" in continuing_states,
        )
    if isinstance(value, dict):
        if any(not isinstance(key, str) or _is_array_index_key(key) for key in value):
            return _ConditionalTargets(invalid=True)
        syntax = next(iter(syntax_conditions), "import")
        opposite = "require" if syntax == "import" else "import"
        candidates: list[str] = []
        blocked = False
        invalid = False
        for key, child in value.items():
            if not isinstance(key, str) or key == opposite:
                continue
            result = _conditional_export_targets(child, conditions, depth + 1)
            candidates.extend(result.targets)
            blocked = blocked or result.blocked
            invalid = invalid or result.invalid
            if key in {syntax, "default"}:
                if not result.undefined:
                    return _ConditionalTargets(
                        targets=_deduplicate(candidates),
                        blocked=blocked,
                        invalid=invalid,
                    )
                continue
        return _ConditionalTargets(
            targets=_deduplicate(candidates),
            blocked=blocked,
            undefined=True,
            invalid=invalid,
        )
    return _ConditionalTargets(invalid=True)


def _valid_workspace_export_target(value: str) -> bool:
    if not value.startswith("./") or "\x00" in value:
        return False
    return _valid_package_path_segments(value[2:])


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _normalize_jsonc(content: str) -> str:
    return _strip_trailing_commas(_strip_jsonc_comments(content))


def _strip_jsonc_comments(content: str) -> str:
    output: list[str] = []
    position = 0
    in_string = False
    escaped = False
    while position < len(content):
        character = content[position]
        following = content[position + 1] if position + 1 < len(content) else ""
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            position += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            position += 1
            continue
        if character == "/" and following == "/":
            output.extend("  ")
            position += 2
            while position < len(content) and content[position] not in "\r\n":
                output.append(" ")
                position += 1
            continue
        if character == "/" and following == "*":
            output.extend("  ")
            position += 2
            while position < len(content):
                if (
                    content[position] == "*"
                    and position + 1 < len(content)
                    and content[position + 1] == "/"
                ):
                    output.extend("  ")
                    position += 2
                    break
                output.append("\n" if content[position] == "\n" else " ")
                position += 1
            continue
        output.append(character)
        position += 1
    return "".join(output)


def _strip_trailing_commas(content: str) -> str:
    output: list[str] = []
    position = 0
    in_string = False
    escaped = False
    while position < len(content):
        character = content[position]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            position += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            position += 1
            continue
        if character == ",":
            lookahead = position + 1
            while lookahead < len(content) and content[lookahead].isspace():
                lookahead += 1
            if lookahead < len(content) and content[lookahead] in "}]":
                output.append(" ")
                position += 1
                continue
        output.append(character)
        position += 1
    return "".join(output)
