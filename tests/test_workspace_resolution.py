import json
from pathlib import Path

import pytest

from reporipple.analysis import analyze_impact
from reporipple.scanner import scan_repository


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(root: Path, relative: str, payload: object) -> None:
    write(root, relative, json.dumps(payload))


def targets_for(graph, source: str) -> set[str]:
    return {edge.target for edge in graph.edges if edge.source == source}


@pytest.mark.parametrize(
    "workspaces",
    [
        ["packages/*"],
        {"packages": ["packages/*"]},
    ],
)
def test_resolves_package_json_workspace_array_and_object_forms(tmp_path, workspaces):
    write_json(tmp_path, "package.json", {"private": True, "workspaces": workspaces})
    write_json(
        tmp_path,
        "packages/shared/package.json",
        {"name": "shared", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/shared/src/index.ts", "export const shared = true;\n")
    write(tmp_path, "src/app.ts", 'import { shared } from "shared";\n')

    graph = scan_repository(tmp_path)
    report = analyze_impact(tmp_path, graph, ["packages/shared/src/index.ts"])

    assert targets_for(graph, "src/app.ts") == {"packages/shared/src/index.ts"}
    assert [item.path for item in report.impacted_files] == ["src/app.ts"]


def test_resolves_scoped_workspace_root_and_exported_subpath(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/ui/package.json",
        {
            "name": "@acme/ui",
            "exports": {
                ".": "./src/index.ts",
                "./button": "./src/button.ts",
            },
        },
    )
    write(tmp_path, "packages/ui/src/index.ts", "export const theme = 'blue';\n")
    write(tmp_path, "packages/ui/src/button.ts", "export const Button = {};\n")
    write(
        tmp_path,
        "apps/web/app.ts",
        'import { theme } from "@acme/ui";\nimport { Button } from "@acme/ui/button";\n',
    )

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "apps/web/app.ts") == {
        "packages/ui/src/button.ts",
        "packages/ui/src/index.ts",
    }


def test_resolves_exact_wildcard_and_conditional_workspace_exports(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/features/package.json",
        {
            "name": "@acme/features",
            "exports": {
                ".": {
                    "import": "./src/index.ts",
                    "default": "./src/fallback.ts",
                },
                "./exact": "./src/exact.ts",
                "./widgets/*": {
                    "import": "./src/widgets/*.ts",
                    "default": "./src/fallback/*.ts",
                },
            },
        },
    )
    write(tmp_path, "packages/features/src/index.ts", "export const root = true;\n")
    write(tmp_path, "packages/features/src/fallback.ts", "export const fallback = true;\n")
    write(tmp_path, "packages/features/src/exact.ts", "export const exact = true;\n")
    write(tmp_path, "packages/features/src/widgets/card.ts", "export const card = true;\n")
    write(tmp_path, "packages/features/src/fallback/card.ts", "export const card = false;\n")
    write(
        tmp_path,
        "src/app.ts",
        "\n".join(
            [
                'import "@acme/features";',
                'import "@acme/features/exact";',
                'import "@acme/features/widgets/card";',
            ]
        ),
    )

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "packages/features/src/exact.ts",
        "packages/features/src/fallback.ts",
        "packages/features/src/fallback/card.ts",
        "packages/features/src/index.ts",
        "packages/features/src/widgets/card.ts",
    }


def test_workspace_exports_encapsulate_unlisted_subpaths(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/ui/package.json",
        {"name": "@acme/ui", "exports": {".": "./src/index.ts"}},
    )
    write(tmp_path, "packages/ui/src/index.ts", "export const publicValue = true;\n")
    write(tmp_path, "packages/ui/src/private.ts", "export const privateValue = true;\n")
    write(tmp_path, "src/app.ts", 'import "@acme/ui/private";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()


@pytest.mark.parametrize(
    ("entry_field", "entry_value", "target"),
    [
        ("source", "./src/source.ts", "packages/tool/src/source.ts"),
        ("module", "./src/module.ts", "packages/tool/src/module.ts"),
        ("main", "./src/main.ts", "packages/tool/src/main.ts"),
        (None, None, "packages/tool/index.ts"),
    ],
)
def test_workspace_entry_point_fallbacks(tmp_path, entry_field, entry_value, target):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    manifest = {"name": "tool"}
    if entry_field is not None:
        manifest[entry_field] = entry_value
    write_json(tmp_path, "packages/tool/package.json", manifest)
    write(tmp_path, target, "export const tool = true;\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {target}


def test_ignores_external_and_undeclared_local_packages(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "examples/react/package.json",
        {"name": "react", "source": "./src/index.ts"},
    )
    write(tmp_path, "examples/react/src/index.ts", "export const localImpostor = true;\n")
    write(tmp_path, "src/app.ts", 'import React from "react";\nimport leftPad from "left-pad";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()


def test_duplicate_workspace_names_warn_and_remain_unresolved(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    for directory in ("first", "second"):
        write_json(
            tmp_path,
            f"packages/{directory}/package.json",
            {"name": "duplicate", "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{directory}/src/index.ts", "export const value = true;\n")
    write(tmp_path, "src/app.ts", 'import "duplicate";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()
    warnings = "\n".join(graph.warnings).lower()
    assert "duplicate" in warnings
    assert "packages/first" in warnings
    assert "packages/second" in warnings


def test_rejects_workspace_export_target_outside_repository(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    write_json(repository, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        repository,
        "packages/unsafe/package.json",
        {"name": "unsafe", "exports": {".": "../../../outside.ts"}},
    )
    write(repository, "packages/unsafe/src/index.ts", "export const safe = true;\n")
    write(repository, "src/app.ts", 'import "unsafe";\n')
    write(tmp_path, "outside.ts", "export const secret = true;\n")

    graph = scan_repository(repository)

    assert targets_for(graph, "src/app.ts") == set()
    assert all(edge.target != "../outside.ts" for edge in graph.edges)


def test_symlinked_workspace_manifest_is_not_read(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    write_json(repository, "package.json", {"workspaces": ["packages/*"]})
    outside_manifest = tmp_path / "outside-package.json"
    outside_manifest.write_text(
        json.dumps({"name": "linked", "source": "./src/index.ts"}),
        encoding="utf-8",
    )
    manifest = repository / "packages/linked/package.json"
    manifest.parent.mkdir(parents=True)
    try:
        manifest.symlink_to(outside_manifest)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    write(repository, "packages/linked/src/index.ts", "export const linked = true;\n")
    write(repository, "src/app.ts", 'import "linked";\n')

    graph = scan_repository(repository)

    assert targets_for(graph, "src/app.ts") == set()


def test_virtual_deleted_workspace_manifest_and_source_are_resolved(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write(tmp_path, "src/app.ts", 'import "removed";\n')

    graph = scan_repository(
        tmp_path,
        virtual_files={
            "packages/removed/package.json": json.dumps(
                {"name": "removed", "source": "./src/index.ts"}
            ),
            "packages/removed/src/index.ts": "export const removed = true;\n",
        },
    )
    report = analyze_impact(tmp_path, graph, ["packages/removed/src/index.ts"])

    assert targets_for(graph, "src/app.ts") == {"packages/removed/src/index.ts"}
    assert [item.path for item in report.impacted_files] == ["src/app.ts"]


def test_tsconfig_paths_take_precedence_over_workspace_package_names(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "tsconfig.json",
        {"compilerOptions": {"paths": {"shared": ["./src/local-shared.ts"]}}},
    )
    write_json(
        tmp_path,
        "packages/shared/package.json",
        {"name": "shared", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/shared/src/index.ts", "export const source = 'workspace';\n")
    write(tmp_path, "src/local-shared.ts", "export const source = 'alias';\n")
    write(tmp_path, "src/app.ts", 'import { source } from "shared";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/local-shared.ts"}
