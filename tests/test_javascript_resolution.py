from pathlib import Path

import pytest

from reporipple.analysis import analyze_impact
from reporipple.scanner import scan_repository


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def targets_for(graph, source: str) -> set[str]:
    return {edge.target for edge in graph.edges if edge.source == source}


def assert_warning_contains(graph, *terms: str) -> None:
    rendered = "\n".join(graph.warnings).lower()
    for term in terms:
        assert term.lower() in rendered


def test_resolves_jsonc_paths_without_requiring_base_url(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        """
        {
          // TypeScript configuration files allow comments.
          "compilerOptions": {
            /* `paths` is relative to this file when baseUrl is absent. */
            "paths": {
              "@/*": ["./src/*",],
            },
          },
        }
        """,
    )
    write(tmp_path, "src/app.ts", 'import { value } from "@/lib/value";\n')
    write(tmp_path, "src/lib/value.ts", "export const value = 1;\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/lib/value.ts"}


def test_resolves_bare_imports_from_base_url(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions":{"baseUrl":"./src"}}',
    )
    write(tmp_path, "src/app.ts", 'import { value } from "lib/value";\n')
    write(tmp_path, "src/lib/value.ts", "export const value = 1;\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/lib/value.ts"}


def test_resolves_exact_wildcard_and_longest_prefix_path_mappings(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        """
        {
          "compilerOptions": {
            "paths": {
              "@exact": ["./src/exact.ts"],
              "@/*": ["./src/general/*"],
              "@/feature/*": ["./src/feature/*"]
            }
          }
        }
        """,
    )
    write(
        tmp_path,
        "src/app.ts",
        "\n".join(
            [
                'import "@exact";',
                'import "@/shared";',
                'import "@/feature/button";',
            ]
        ),
    )
    write(tmp_path, "src/exact.ts", "export {};\n")
    write(tmp_path, "src/general/shared.ts", "export {};\n")
    write(tmp_path, "src/general/feature/button.ts", "export {};\n")
    write(tmp_path, "src/feature/button.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "src/exact.ts",
        "src/feature/button.ts",
        "src/general/shared.ts",
    }


def test_path_targets_keep_declared_order_and_fall_back_when_missing(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        """
        {
          "compilerOptions": {
            "paths": {
              "@pick/*": ["./src/first/*", "./src/second/*"],
              "@fallback/*": ["./src/missing/*", "./src/second/*"]
            }
          }
        }
        """,
    )
    write(
        tmp_path,
        "src/app.ts",
        'import "@pick/value";\nimport "@fallback/value";\n',
    )
    write(tmp_path, "src/first/value.ts", "export {};\n")
    write(tmp_path, "src/second/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "src/first/value.ts",
        "src/second/value.ts",
    }


def test_paths_take_precedence_over_base_url_lookup(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        """
        {
          "compilerOptions": {
            "baseUrl": "./src",
            "paths": {"lib/*": ["mapped/*"]}
          }
        }
        """,
    )
    write(tmp_path, "src/app.ts", 'import "lib/value";\n')
    write(tmp_path, "src/lib/value.ts", "export {};\n")
    write(tmp_path, "src/mapped/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/mapped/value.ts"}


def test_nearest_javascript_config_controls_each_source_file(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions":{"paths":{"@/*":["./root-src/*"]}}}',
    )
    write(
        tmp_path,
        "packages/app/jsconfig.json",
        '{"compilerOptions":{"paths":{"@/*":["./src/*"]}}}',
    )
    write(tmp_path, "packages/app/src/app.js", 'import "@/value";\n')
    write(tmp_path, "packages/app/src/value.js", "export {};\n")
    write(tmp_path, "root-src/value.js", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "packages/app/src/app.js") == {"packages/app/src/value.js"}


def test_tsconfig_takes_precedence_over_jsconfig_in_the_same_directory(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions":{"paths":{"@/*":["./typescript/*"]}}}',
    )
    write(
        tmp_path,
        "jsconfig.json",
        '{"compilerOptions":{"paths":{"@/*":["./javascript/*"]}}}',
    )
    write(tmp_path, "app.ts", 'import "@/value";\n')
    write(tmp_path, "typescript/value.ts", "export {};\n")
    write(tmp_path, "javascript/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "app.ts") == {"typescript/value.ts"}


def test_relative_extends_keeps_path_targets_relative_to_declaring_config(tmp_path):
    write(
        tmp_path,
        "config/base.json",
        '{"compilerOptions":{"paths":{"@shared/*":["../shared/*"]}}}',
    )
    write(
        tmp_path,
        "packages/app/tsconfig.json",
        '{"extends":"../../config/base"}',
    )
    write(tmp_path, "packages/app/src/app.ts", 'import "@shared/value";\n')
    write(tmp_path, "shared/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "packages/app/src/app.ts") == {"shared/value.ts"}


def test_cyclic_extends_warns_and_preserves_relative_import_analysis(tmp_path):
    write(tmp_path, "tsconfig.json", '{"extends":"./config/base.json"}')
    write(tmp_path, "config/base.json", '{"extends":"../tsconfig.json"}')
    write(tmp_path, "src/app.ts", 'import "./local";\n')
    write(tmp_path, "src/local.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/local.ts"}
    assert_warning_contains(graph, "cycle", "tsconfig.json")


def test_package_based_extends_warns_but_local_options_still_apply(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        """
        {
          "extends": "@tsconfig/strictest/tsconfig.json",
          "compilerOptions": {
            "paths": {"@/*": ["./src/*"]}
          }
        }
        """,
    )
    write(tmp_path, "src/app.ts", 'import "@/value";\n')
    write(tmp_path, "src/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/value.ts"}
    assert_warning_contains(graph, "unsupported", "extends")


def test_base_url_outside_repository_is_rejected(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    write(
        repository,
        "packages/app/tsconfig.json",
        '{"compilerOptions":{"baseUrl":"../../../outside"}}',
    )
    write(repository, "packages/app/src/app.ts", 'import "value";\n')
    write(tmp_path, "outside/value.ts", "export {};\n")

    graph = scan_repository(repository)

    assert targets_for(graph, "packages/app/src/app.ts") == set()
    assert_warning_contains(graph, "baseurl", "repository")


def test_symlinked_config_is_not_read(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    outside_config = tmp_path / "outside-tsconfig.json"
    outside_config.write_text(
        '{"compilerOptions":{"paths":{"@/*":["./src/*"]}}}',
        encoding="utf-8",
    )
    try:
        (repository / "tsconfig.json").symlink_to(outside_config)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    write(repository, "src/app.ts", 'import "@/value";\n')
    write(repository, "src/value.ts", "export {};\n")

    graph = scan_repository(repository)

    assert targets_for(graph, "src/app.ts") == set()
    assert_warning_contains(graph, "symlink", "tsconfig.json")


def test_relative_imports_remain_relative_when_configured_resolution_exists(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions":{"baseUrl":"./other"}}',
    )
    write(tmp_path, "src/app.ts", 'import "./value";\n')
    write(tmp_path, "src/value.ts", "export {};\n")
    write(tmp_path, "other/value.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/value.ts"}


def test_alias_edges_drive_transitive_impact_analysis(tmp_path):
    write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions":{"paths":{"@/*":["./src/*"]}}}',
    )
    write(tmp_path, "src/core.ts", "export const value = 1;\n")
    write(tmp_path, "src/service.ts", 'import { value } from "@/core";\n')
    write(tmp_path, "src/api.ts", 'import "@/service";\n')

    graph = scan_repository(tmp_path)
    report = analyze_impact(tmp_path, graph, ["src/core.ts"])

    assert [(item.path, item.distance, item.via) for item in report.impacted_files] == [
        ("src/service.ts", 1, ("src/core.ts", "src/service.ts")),
        ("src/api.ts", 2, ("src/core.ts", "src/service.ts", "src/api.ts")),
    ]
