import json
from pathlib import Path

from reporipple.analysis import analyze_impact
from reporipple.config import MAX_SOURCE_FILE_BYTES
from reporipple.scanner import scan_repository


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(root: Path, relative: str, payload: object) -> None:
    write(root, relative, json.dumps(payload))


def impacted(graph, root: Path, *changed: str) -> list[tuple[str, int, tuple[str, ...]]]:
    report = analyze_impact(root, graph, list(changed))
    return [(item.path, item.distance, item.via) for item in report.impacted_files]


def test_nested_tsconfig_change_traces_governed_source_then_external_dependents(tmp_path):
    write_json(tmp_path, "packages/lib/tsconfig.json", {})
    write(tmp_path, "packages/lib/src/value.ts", "export const value = 1;\n")
    write(tmp_path, "src/app.ts", 'import "../packages/lib/src/value";\n')
    write(tmp_path, "src/entry.ts", 'import "./app";\n')

    graph = scan_repository(tmp_path)

    assert impacted(graph, tmp_path, "packages/lib/tsconfig.json") == [
        (
            "packages/lib/src/value.ts",
            1,
            ("packages/lib/tsconfig.json", "packages/lib/src/value.ts"),
        ),
        (
            "src/app.ts",
            2,
            (
                "packages/lib/tsconfig.json",
                "packages/lib/src/value.ts",
                "src/app.ts",
            ),
        ),
        (
            "src/entry.ts",
            3,
            (
                "packages/lib/tsconfig.json",
                "packages/lib/src/value.ts",
                "src/app.ts",
                "src/entry.ts",
            ),
        ),
    ]


def test_nearest_project_config_limits_governance_unless_child_extends_parent(tmp_path):
    write_json(tmp_path, "tsconfig.json", {})
    write_json(tmp_path, "packages/isolated/tsconfig.json", {})
    write_json(
        tmp_path,
        "packages/inherited/tsconfig.json",
        {"extends": "../../tsconfig.json"},
    )
    write(tmp_path, "src/root.ts", "export {};\n")
    write(tmp_path, "packages/isolated/src/value.ts", "export {};\n")
    write(tmp_path, "packages/inherited/src/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert [path for path, _, _ in impacted(graph, tmp_path, "tsconfig.json")] == [
        "packages/inherited/src/value.ts",
        "src/root.ts",
    ]
    assert impacted(graph, tmp_path, "packages/isolated/tsconfig.json") == [
        (
            "packages/isolated/src/value.ts",
            1,
            (
                "packages/isolated/tsconfig.json",
                "packages/isolated/src/value.ts",
            ),
        )
    ]


def test_local_extends_target_is_a_configuration_dependency(tmp_path):
    write_json(tmp_path, "config/base.json", {"compilerOptions": {"strict": True}})
    write_json(tmp_path, "tsconfig.json", {"extends": "./config/base.json"})
    write(tmp_path, "src/app.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert impacted(graph, tmp_path, "config/base.json") == [
        ("src/app.ts", 1, ("config/base.json", "src/app.ts"))
    ]


def test_malformed_jsconfig_still_governs_nearby_javascript(tmp_path):
    write(tmp_path, "web/jsconfig.json", "{not-json")
    write(tmp_path, "web/src/app.js", "export {};\n")

    graph = scan_repository(tmp_path)

    assert impacted(graph, tmp_path, "web/jsconfig.json") == [
        ("web/src/app.js", 1, ("web/jsconfig.json", "web/src/app.js"))
    ]
    assert any("Could not parse" in warning for warning in graph.warnings)


def test_malformed_extended_config_remains_an_impact_target(tmp_path):
    write(tmp_path, "config/base.json", "{not-json")
    write_json(tmp_path, "tsconfig.json", {"extends": "./config/base.json"})
    write(tmp_path, "src/app.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert impacted(graph, tmp_path, "config/base.json") == [
        ("src/app.ts", 1, ("config/base.json", "src/app.ts"))
    ]


def test_oversized_source_still_retains_configuration_governance(tmp_path):
    write_json(tmp_path, "tsconfig.json", {})
    write(tmp_path, "src/large.ts", "x" * (MAX_SOURCE_FILE_BYTES + 1))

    graph = scan_repository(tmp_path)

    assert impacted(graph, tmp_path, "tsconfig.json") == [
        ("src/large.ts", 1, ("tsconfig.json", "src/large.ts"))
    ]
    assert any("source is larger" in warning for warning in graph.warnings)


def test_package_manifest_change_impacts_owned_sources_and_workspace_importers(tmp_path):
    write_json(tmp_path, "package.json", {"private": True, "workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/shared/package.json",
        {"name": "@demo/shared", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/shared/src/index.ts", "export const value = 1;\n")
    write(tmp_path, "packages/shared/src/internal.ts", "export {};\n")
    write(tmp_path, "apps/web/package.json", '{"name":"web"}')
    write(tmp_path, "apps/web/src/app.ts", 'import "@demo/shared";\n')

    graph = scan_repository(tmp_path)

    assert [path for path, _, _ in impacted(
        graph, tmp_path, "packages/shared/package.json"
    )] == [
        "apps/web/src/app.ts",
        "packages/shared/src/index.ts",
        "packages/shared/src/internal.ts",
    ]


def test_root_manifest_change_reaches_nested_workspace_importers(tmp_path):
    write_json(tmp_path, "package.json", {"private": True, "workspaces": ["packages/*"]})
    write_json(tmp_path, "packages/shared/package.json", {"name": "shared"})
    write(tmp_path, "packages/shared/index.ts", "export {};\n")
    write_json(tmp_path, "apps/web/package.json", {"name": "web"})
    write(tmp_path, "apps/web/app.ts", 'import "shared";\n')
    write(tmp_path, "apps/web/no-imports.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert [path for path, _, _ in impacted(graph, tmp_path, "package.json")] == [
        "apps/web/app.ts"
    ]


def test_package_governance_does_not_cross_nearest_manifest_boundary(tmp_path):
    write_json(tmp_path, "package.json", {"name": "root"})
    write_json(tmp_path, "packages/child/package.json", {"name": "child"})
    write(tmp_path, "src/root.ts", "export {};\n")
    write(tmp_path, "packages/child/src/child.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert [path for path, _, _ in impacted(graph, tmp_path, "package.json")] == [
        "src/root.ts"
    ]
    assert [
        path for path, _, _ in impacted(graph, tmp_path, "packages/child/package.json")
    ] == ["packages/child/src/child.ts"]


def test_virtual_deleted_project_config_remains_traceable(tmp_path):
    write(tmp_path, "src/app.ts", "export {};\n")

    graph = scan_repository(tmp_path, virtual_files={"tsconfig.json": "{}"})

    assert impacted(graph, tmp_path, "tsconfig.json") == [
        ("src/app.ts", 1, ("tsconfig.json", "src/app.ts"))
    ]
    assert graph.files == {"src/app.ts"}


def test_renamed_project_config_keeps_old_and_new_paths_actionable(tmp_path):
    write_json(tmp_path, "jsconfig.json", {})
    write(tmp_path, "src/app.js", "export {};\n")

    graph = scan_repository(tmp_path, virtual_files={"tsconfig.json": "{}"})

    assert impacted(graph, tmp_path, "tsconfig.json") == [
        ("src/app.js", 1, ("tsconfig.json", "src/app.js"))
    ]
    assert impacted(graph, tmp_path, "jsconfig.json") == [
        ("src/app.js", 1, ("jsconfig.json", "src/app.js"))
    ]


def test_virtual_deleted_workspace_manifest_reaches_owned_source_and_importer(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write(tmp_path, "src/app.ts", 'import "removed";\n')

    graph = scan_repository(
        tmp_path,
        virtual_files={
            "packages/removed/package.json": json.dumps(
                {"name": "removed", "source": "./src/index.ts"}
            ),
            "packages/removed/src/index.ts": "export {};\n",
        },
    )

    assert [path for path, _, _ in impacted(
        graph, tmp_path, "packages/removed/package.json"
    )] == ["packages/removed/src/index.ts", "src/app.ts"]


def test_configuration_relations_do_not_change_source_inventory_or_import_edges(tmp_path):
    write_json(tmp_path, "tsconfig.json", {})
    write_json(tmp_path, "package.json", {"name": "demo"})
    write(tmp_path, "src/app.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert graph.files == {"src/app.ts"}
    assert graph.edges == []
    assert {(edge.target, edge.kind) for edge in graph.metadata_edges} == {
        ("package.json", "package-manifest"),
        ("tsconfig.json", "js-config"),
    }
