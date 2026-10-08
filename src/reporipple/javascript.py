"""Deterministic JavaScript and TypeScript import resolution."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from reporipple.config import JAVASCRIPT_EXTENSIONS, MAX_SOURCE_FILE_BYTES

JS_IMPORT_PATTERN = re.compile(
    r"(?:import|export)\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
    r"|import\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
_MAX_CONFIG_DEPTH = 16
_CONDITION_PRIORITY = ("source", "import", "default", "require", "browser", "node", "types")


@dataclass(frozen=True)
class _PathRule:
    pattern: str
    targets: tuple[str, ...]
    base_directory: Path
    order: int


@dataclass(frozen=True)
class _ProjectConfig:
    base_url: Path | None = None
    path_rules: tuple[_PathRule, ...] = ()


@dataclass(frozen=True)
class _WorkspacePackage:
    name: str
    directory: Path
    manifest: Mapping[str, Any]


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
        for match in JS_IMPORT_PATTERN.finditer(content):
            specifier = next(group for group in match.groups() if group is not None)
            for target in self.resolve(source, specifier):
                if target != source:
                    resolved.append((specifier, target))
        return resolved

    def resolve(self, source: str, specifier: str) -> tuple[str, ...]:
        """Resolve one import using relative, config, then workspace semantics."""
        if not specifier or "\x00" in specifier:
            return ()
        if specifier.startswith("."):
            target = self._resolve_from(Path(source).parent, specifier)
            return (target,) if target is not None else ()
        if specifier.startswith(("/", "#")):
            return ()

        config = self._nearest_config(source)
        if config is not None:
            target = self._resolve_paths(config, specifier)
            if target is not None:
                return (target,)
            if config.base_url is not None:
                target = self._resolve_absolute_base(config.base_url, specifier)
                if target is not None:
                    return (target,)

        return self._resolve_workspace(specifier)

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
        if isinstance(extends, str) and extends:
            if extends.startswith("."):
                inherited = self._resolve_extends(relative, extends)
                if inherited is not None:
                    parent = self._load_project_config(inherited, (*stack, relative)) or parent
            else:
                self._warn(f"Unsupported package-based extends in {relative}: {extends!r}")
        elif extends is not None:
            self._warn(f"Invalid extends value in {relative}; expected a relative string")

        compiler = payload.get("compilerOptions", {})
        if not isinstance(compiler, dict):
            self._warn(f"Invalid compilerOptions in {relative}; expected an object")
            compiler = {}

        base_url = parent.base_url
        config_directory = self.root / PurePosixPath(relative).parent
        if "baseUrl" in compiler:
            raw_base = compiler.get("baseUrl")
            if isinstance(raw_base, str) and raw_base and "\x00" not in raw_base:
                candidate = (config_directory / raw_base).resolve(strict=False)
                if self._inside(candidate, self.root):
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
        if "paths" in compiler:
            raw_paths = compiler.get("paths")
            path_rules = self._path_rules(
                relative,
                raw_paths,
                base_url or config_directory,
            )

        config = _ProjectConfig(base_url=base_url, path_rules=path_rules)
        self._config_cache[relative] = config
        return config

    def _resolve_extends(self, owner: str, value: str) -> str | None:
        owner_directory = self.root / PurePosixPath(owner).parent
        candidate = (owner_directory / value).resolve(strict=False)
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
        base_directory: Path,
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
                    base_directory=base_directory,
                    order=order,
                )
            )
        return tuple(rules)

    def _resolve_paths(self, config: _ProjectConfig, specifier: str) -> str | None:
        matches: list[tuple[tuple[int, int, int, int], _PathRule, str]] = []
        for rule in config.path_rules:
            capture = _match_pattern(rule.pattern, specifier)
            if capture is None:
                continue
            prefix, _, suffix = rule.pattern.partition("*")
            score = (
                int("*" not in rule.pattern),
                len(prefix) + len(suffix),
                len(prefix),
                -rule.order,
            )
            matches.append((score, rule, capture))
        if not matches:
            return None

        _, rule, capture = max(matches, key=lambda item: item[0])
        for target_pattern in rule.targets:
            target_value = target_pattern.replace("*", capture)
            target = self._resolve_absolute_base(rule.base_directory, target_value)
            if target is not None:
                return target
        return None

    def _resolve_workspace(self, specifier: str) -> tuple[str, ...]:
        matches = [
            name
            for name in self._workspaces
            if specifier == name or specifier.startswith(f"{name}/")
        ]
        if not matches:
            return ()
        name = min(matches, key=lambda item: (-len(item), item))
        package = self._workspaces[name]
        suffix = specifier[len(name) :].lstrip("/")
        subpath = "." if not suffix else f"./{suffix}"
        return self._workspace_targets(package, subpath)

    def _workspace_targets(
        self,
        package: _WorkspacePackage,
        subpath: str,
    ) -> tuple[str, ...]:
        manifest = package.manifest
        exports = manifest.get("exports")
        if exports is not None:
            matched, export_value, capture = _select_export(exports, subpath)
            if not matched:
                return ()
            targets = self._resolve_export_targets(package, export_value, capture)
            if targets:
                return targets
            if subpath == ".":
                source = manifest.get("source")
                if isinstance(source, str):
                    target = self._resolve_package_path(package, source)
                    if target is not None:
                        return (target,)
            return ()

        if subpath != ".":
            target = self._resolve_package_path(package, subpath.removeprefix("./"))
            return (target,) if target is not None else ()

        for field in ("source", "module", "main"):
            value = manifest.get(field)
            if isinstance(value, str):
                target = self._resolve_package_path(package, value)
                if target is not None:
                    return (target,)
        for fallback in ("src/index", "index"):
            target = self._resolve_package_path(package, fallback)
            if target is not None:
                return (target,)
        return ()

    def _resolve_export_targets(
        self,
        package: _WorkspacePackage,
        value: object,
        capture: str,
    ) -> tuple[str, ...]:
        targets: list[str] = []
        for raw_target in _string_leaves(value):
            if not raw_target.startswith("./"):
                self._warn(
                    f"Workspace export for {package.name!r} must stay inside its package: "
                    f"{raw_target!r}"
                )
                continue
            target = self._resolve_package_path(package, raw_target.replace("*", capture))
            if target is not None and target not in targets:
                targets.append(target)
        return tuple(targets)

    def _resolve_package_path(
        self,
        package: _WorkspacePackage,
        value: str,
    ) -> str | None:
        if not value or "\x00" in value or Path(value).is_absolute():
            self._warn(f"Invalid workspace target for {package.name!r}: {value!r}")
            return None
        candidate = (package.directory / value).resolve(strict=False)
        if not self._inside(candidate, package.directory):
            self._warn(
                f"Workspace target for {package.name!r} resolves outside its package: {value!r}"
            )
            return None
        return self._resolve_candidate(candidate)

    def _build_workspace_index(self) -> dict[str, _WorkspacePackage]:
        if not self._metadata_exists("package.json"):
            return {}
        root_manifest = self._read_manifest("package.json")
        if root_manifest is None:
            return {}

        candidates: list[_WorkspacePackage] = []
        root_name = root_manifest.get("name")
        if isinstance(root_name, str) and root_name:
            candidates.append(_WorkspacePackage(root_name, self.root, root_manifest))

        patterns = _workspace_patterns(root_manifest.get("workspaces"))
        if patterns:
            for manifest_path in self._candidate_manifest_paths():
                if manifest_path == "package.json":
                    continue
                directory_text = PurePosixPath(manifest_path).parent.as_posix()
                if not any(PurePosixPath(directory_text).match(pattern) for pattern in patterns):
                    continue
                manifest = self._read_manifest(manifest_path)
                if manifest is None:
                    continue
                name = manifest.get("name")
                if not isinstance(name, str) or not name:
                    continue
                directory = self.root / PurePosixPath(manifest_path).parent
                candidates.append(_WorkspacePackage(name, directory.resolve(), manifest))

        grouped: dict[str, list[_WorkspacePackage]] = {}
        for package in candidates:
            grouped.setdefault(package.name, []).append(package)

        index: dict[str, _WorkspacePackage] = {}
        for name in sorted(grouped):
            packages = sorted(grouped[name], key=lambda item: item.directory.as_posix())
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
        try:
            payload = json.loads(_normalize_jsonc(content) if jsonc else content)
        except json.JSONDecodeError as exc:
            self._warn(f"Could not parse {label.lower()} {relative}:{exc.lineno}: {exc.msg}")
            return None
        if not isinstance(payload, dict):
            self._warn(f"Could not parse {label.lower()} {relative}: expected an object")
            return None
        return payload

    def _read_metadata(self, relative: str, label: str) -> str | None:
        if relative in self.virtual_files:
            content = self.virtual_files[relative]
            if len(content.encode("utf-8")) > MAX_SOURCE_FILE_BYTES:
                self._warn(f"Skipped {relative}: {label.lower()} is too large")
                return None
            return content

        path = self.root / PurePosixPath(relative)
        if path.is_symlink():
            self._warn(f"Skipped symlinked {label.lower()} {relative}")
            return None
        try:
            with path.open("rb") as metadata_file:
                raw = metadata_file.read(MAX_SOURCE_FILE_BYTES + 1)
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

    def _resolve_from(self, base: Path, value: str) -> str | None:
        return self._resolve_absolute_base(self.root / base, value)

    def _resolve_absolute_base(self, base: Path, value: str) -> str | None:
        if not value or "\x00" in value or Path(value).is_absolute():
            return None
        candidate = (base / value).resolve(strict=False)
        if not self._inside(candidate, self.root):
            return None
        return self._resolve_candidate(candidate)

    def _resolve_candidate(self, candidate: Path) -> str | None:
        try:
            relative = candidate.relative_to(self.root).as_posix()
        except ValueError:
            return None
        for option in _module_candidates(relative):
            if option in self.files:
                return option
        return None

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


def _module_candidates(relative: str) -> tuple[str, ...]:
    normalized = posixpath.normpath(relative)
    path = PurePosixPath(normalized)
    candidates: list[str] = [normalized]
    suffix = path.suffix.lower()
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        stem = path.with_suffix("").as_posix()
        candidates.extend(f"{stem}{extension}" for extension in JAVASCRIPT_EXTENSIONS)
    elif not suffix:
        candidates.extend(f"{normalized}{extension}" for extension in JAVASCRIPT_EXTENSIONS)
        candidates.extend(
            (path / f"index{extension}").as_posix() for extension in JAVASCRIPT_EXTENSIONS
        )
    return tuple(dict.fromkeys(candidates))


def _workspace_patterns(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        raw_patterns = value
    elif isinstance(value, dict) and isinstance(value.get("packages"), list):
        raw_patterns = value["packages"]
    else:
        return ()
    return tuple(
        pattern.rstrip("/")
        for pattern in raw_patterns
        if isinstance(pattern, str)
        and pattern
        and not pattern.startswith(("!", "/"))
        and "\x00" not in pattern
        and ".." not in PurePosixPath(pattern).parts
    )


def _select_export(exports: object, subpath: str) -> tuple[bool, object, str]:
    if isinstance(exports, dict) and any(
        isinstance(key, str) and key.startswith(".") for key in exports
    ):
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
            matches.append(((len(prefix) + len(suffix), len(prefix)), value, capture))
        if not matches:
            return False, None, ""
        _, value, capture = max(matches, key=lambda item: item[0])
        return True, value, capture
    if subpath == ".":
        return True, exports, ""
    return False, None, ""


def _string_leaves(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for child in value for item in _string_leaves(child))
    if isinstance(value, dict):
        ordered_keys = [key for key in _CONDITION_PRIORITY if key in value]
        ordered_keys.extend(sorted(str(key) for key in value if key not in ordered_keys))
        return tuple(item for key in ordered_keys for item in _string_leaves(value[key]))
    return ()


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
