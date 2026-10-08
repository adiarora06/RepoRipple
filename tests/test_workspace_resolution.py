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


def test_workspace_conditions_follow_import_and_require_contexts(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/dual/package.json",
        {
            "name": "dual",
            "exports": {
                ".": {
                    "import": "./src/module.mts",
                    "require": "./src/common.cts",
                    "default": "./src/fallback.ts",
                }
            },
        },
    )
    write(tmp_path, "packages/dual/src/module.mts", "export {};\n")
    write(tmp_path, "packages/dual/src/common.cts", "export {};\n")
    write(tmp_path, "packages/dual/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/module.mts", 'import "dual";\n')
    write(tmp_path, "src/common.cjs", 'require("dual");\n')
    write(tmp_path, "src/transpiled.cts", 'import "dual";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/module.mts") == {"packages/dual/src/module.mts"}
    assert targets_for(graph, "src/common.cjs") == {"packages/dual/src/common.cts"}
    assert targets_for(graph, "src/transpiled.cts") == {"packages/dual/src/common.cts"}


def test_generic_module_mode_keeps_both_import_and_require_targets(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/dual/package.json",
        {
            "name": "dual",
            "exports": {
                ".": {
                    "import": "./src/module.ts",
                    "require": "./src/common.ts",
                    "default": "./src/fallback.ts",
                }
            },
        },
    )
    write(tmp_path, "packages/dual/src/module.ts", "export {};\n")
    write(tmp_path, "packages/dual/src/common.ts", "export {};\n")
    write(tmp_path, "packages/dual/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "dual";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "packages/dual/src/common.ts",
        "packages/dual/src/module.ts",
    }


def test_custom_conditions_and_default_are_conservative_without_known_mode_match(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/ui/package.json",
        {
            "name": "ui",
            "exports": {
                ".": {
                    "browser": "./src/browser.ts",
                    "default": "./src/default.ts",
                }
            },
        },
    )
    write(tmp_path, "packages/ui/src/browser.ts", "export {};\n")
    write(tmp_path, "packages/ui/src/default.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "ui";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {
        "packages/ui/src/browser.ts",
        "packages/ui/src/default.ts",
    }


def test_nested_unmatched_condition_falls_through_to_default(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/dual/package.json",
        {
            "name": "dual",
            "exports": {
                ".": {
                    "node": {"require": "./src/common.cts"},
                    "default": "./src/fallback.ts",
                }
            },
        },
    )
    write(tmp_path, "packages/dual/src/common.cts", "export {};\n")
    write(tmp_path, "packages/dual/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "dual";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {"packages/dual/src/fallback.ts"}


@pytest.mark.parametrize(
    ("browser_target", "expected"),
    [
        (
            "./src/browser.ts",
            {"packages/dual/src/browser.ts", "packages/dual/src/fallback.ts"},
        ),
        (None, {"packages/dual/src/fallback.ts"}),
    ],
)
def test_nested_optional_condition_preserves_outer_default(
    tmp_path,
    browser_target,
    expected,
):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/dual/package.json",
        {
            "name": "dual",
            "exports": {
                ".": {
                    "import": {"browser": browser_target},
                    "default": "./src/fallback.ts",
                }
            },
        },
    )
    write(tmp_path, "packages/dual/src/browser.ts", "export {};\n")
    write(tmp_path, "packages/dual/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "dual";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == expected


def test_workspace_export_array_uses_first_valid_target(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {".": ["./src/first.ts", "./src/second.ts"]}},
    )
    write(tmp_path, "packages/tool/src/first.ts", "export {};\n")
    write(tmp_path, "packages/tool/src/second.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {"packages/tool/src/first.ts"}


def test_workspace_export_array_does_not_fall_back_from_missing_valid_target(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {".": ["./src/missing.ts", "./src/second.ts"]}},
    )
    write(tmp_path, "packages/tool/src/second.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == set()


def test_workspace_export_array_skips_invalid_target(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {".": ["../outside.ts", "./src/second.ts"]}},
    )
    write(tmp_path, "packages/tool/src/second.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {"packages/tool/src/second.ts"}


def test_empty_workspace_export_array_blocks_outer_default(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {".": {"import": [], "default": "./src/fallback.ts"}},
        },
    )
    write(tmp_path, "packages/tool/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == set()


@pytest.mark.parametrize("blocked_target", [None, []])
def test_workspace_export_array_continues_after_blocked_target(tmp_path, blocked_target):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {".": [blocked_target, "./src/fallback.ts"]}},
    )
    write(tmp_path, "packages/tool/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {"packages/tool/src/fallback.ts"}


@pytest.mark.parametrize("blocked_array", [[None], [None, {}]])
def test_exhausted_blocked_export_array_does_not_reach_outer_default(
    tmp_path,
    blocked_array,
):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {".": {"require": blocked_array, "default": "./src/fallback.cjs"}},
        },
    )
    write(tmp_path, "packages/tool/src/fallback.cjs", "module.exports = {};\n")
    write(tmp_path, "src/app.cjs", 'require("tool");\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.cjs") == set()


@pytest.mark.parametrize("browser_target", [None, "bad"])
def test_optional_array_outcome_can_reach_outer_default(tmp_path, browser_target):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {
                ".": {
                    "import": [{"browser": browser_target}],
                    "default": "./src/fallback.mts",
                }
            },
        },
    )
    write(tmp_path, "packages/tool/src/fallback.mts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {"packages/tool/src/fallback.mts"}


def test_all_undefined_workspace_export_array_reaches_outer_default(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {".": {"require": [{}], "default": "./src/fallback.cts"}},
        },
    )
    write(tmp_path, "packages/tool/src/fallback.cts", "export {};\n")
    write(tmp_path, "src/app.cjs", 'require("tool");\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.cjs") == {"packages/tool/src/fallback.cts"}


def test_mixed_subpath_and_condition_export_keys_are_rejected(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {".": "./src/main.ts", "default": "./src/fallback.ts"},
        },
    )
    write(tmp_path, "packages/tool/src/main.ts", "export {};\n")
    write(tmp_path, "packages/tool/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == set()


def test_numeric_workspace_export_condition_is_rejected(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {".": {"0": "./src/zero.ts", "default": "./src/fallback.ts"}},
        },
    )
    write(tmp_path, "packages/tool/src/zero.ts", "export {};\n")
    write(tmp_path, "packages/tool/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == set()


def test_extreme_numeric_export_condition_name_does_not_abort_scan(tmp_path):
    condition = "9" * 5_000
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {
                ".": {
                    condition: "./src/custom.ts",
                    "default": "./src/fallback.ts",
                }
            },
        },
    )
    write(tmp_path, "packages/tool/src/custom.ts", "export {};\n")
    write(tmp_path, "packages/tool/src/fallback.ts", "export {};\n")
    write(tmp_path, "src/app.mts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.mts") == {
        "packages/tool/src/custom.ts",
        "packages/tool/src/fallback.ts",
    }


def test_nested_dot_condition_is_treated_conservatively(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {
                ".": {
                    "./unused": "./src/custom.cjs",
                    "default": "./src/fallback.cjs",
                }
            },
        },
    )
    write(tmp_path, "packages/tool/src/custom.cjs", "module.exports = {};\n")
    write(tmp_path, "packages/tool/src/fallback.cjs", "module.exports = {};\n")
    write(tmp_path, "src/app.cjs", 'require("tool");\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.cjs") == {
        "packages/tool/src/custom.cjs",
        "packages/tool/src/fallback.cjs",
    }


@pytest.mark.parametrize("metadata", ["tsconfig.json", "package.json"])
def test_extreme_json_integer_warns_without_aborting_scan(tmp_path, metadata):
    write(tmp_path, metadata, '{"value":' + "9" * 5_000 + "}")
    write(tmp_path, "src/app.ts", 'import "./local";\n')
    write(tmp_path, "src/local.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/local.ts"}
    assert "could not parse" in "\n".join(graph.warnings).lower()


@pytest.mark.parametrize("metadata", ["tsconfig.json", "package.json"])
def test_unencodable_virtual_metadata_warns_without_aborting_scan(tmp_path, metadata):
    write(tmp_path, "src/app.ts", 'import "./local";\n')
    write(tmp_path, "src/local.ts", "export {};\n")

    graph = scan_repository(tmp_path, virtual_files={metadata: "\ud800"})

    assert targets_for(graph, "src/app.ts") == {"src/local.ts"}
    assert "could not read" in "\n".join(graph.warnings).lower()


def test_workspace_export_wildcards_prefer_longest_prefix(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/ui/package.json",
        {
            "name": "ui",
            "exports": {
                "./*-generated-component": "./wrong/*.ts",
                "./feature/*": "./right/*.ts",
            },
        },
    )
    write(tmp_path, "packages/ui/wrong/feature/button.ts", "export {};\n")
    write(tmp_path, "packages/ui/right/button-generated-component.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "ui/feature/button-generated-component";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/ui/right/button-generated-component.ts"}


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
    "exports",
    [
        {".": None},
        {".": "../outside.js"},
        {".": "other-package"},
    ],
)
def test_blocked_or_invalid_root_export_does_not_fall_back_to_source(tmp_path, exports):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/locked/package.json",
        {
            "name": "locked",
            "exports": exports,
            "source": "./src/index.ts",
        },
    )
    write(tmp_path, "packages/locked/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "locked";\n')

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


def test_root_package_name_is_not_treated_as_a_workspace(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {"name": "root-package", "source": "./src/index.ts"},
    )
    write(tmp_path, "src/index.ts", "export {};\n")
    write(tmp_path, "src/consumer.ts", 'import "root-package";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/consumer.ts") == set()


def test_recursive_workspace_glob_does_not_implicitly_include_root_package(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {
            "name": "root-package",
            "source": "./src/index.ts",
            "workspaces": ["**"],
        },
    )
    write(tmp_path, "src/index.ts", "export {};\n")
    write(tmp_path, "src/consumer.ts", 'import "root-package";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/consumer.ts") == set()


def test_workspace_globs_support_braces_recursion_and_exclusions(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {
            "workspaces": [
                "!apps/private/**",
                "packages/{ui,data}",
                "apps/**",
            ]
        },
    )
    packages = {
        "packages/ui": "ui",
        "packages/data": "data",
        "apps/team/tools/nested": "nested",
        "apps/private/tools/secret": "secret",
    }
    for directory, name in packages.items():
        write_json(
            tmp_path,
            f"{directory}/package.json",
            {"name": name, "source": "./src/index.ts"},
        )
        write(tmp_path, f"{directory}/src/index.ts", "export {};\n")
    write(
        tmp_path,
        "src/app.ts",
        'import "ui";\nimport "data";\nimport "nested";\nimport "secret";\n',
    )

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "apps/team/tools/nested/src/index.ts",
        "packages/data/src/index.ts",
        "packages/ui/src/index.ts",
    }


def test_later_broad_workspace_pattern_does_not_erase_exact_exclusion(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {"workspaces": ["!packages/excluded", "packages/*"]},
    )
    for directory in ("included", "excluded"):
        write_json(
            tmp_path,
            f"packages/{directory}/package.json",
            {"name": directory, "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{directory}/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "included";\nimport "excluded";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/included/src/index.ts"}


def test_specific_positive_can_remove_an_accumulated_workspace_exclusion(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {"workspaces": ["packages/**", "!packages/b/**", "packages/b/a"]},
    )
    for directory in ("a", "c"):
        write_json(
            tmp_path,
            f"packages/b/{directory}/package.json",
            {"name": directory, "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/b/{directory}/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "a";\nimport "c";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "packages/b/a/src/index.ts",
        "packages/b/c/src/index.ts",
    }


def test_specific_positive_removes_atomic_brace_exclusion(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {
            "workspaces": [
                "packages/**",
                "!packages/{a,b}/**",
                "packages/a/x",
            ]
        },
    )
    for directory in ("a/x", "b/y"):
        name = directory.replace("/", "-")
        write_json(
            tmp_path,
            f"packages/{directory}/package.json",
            {"name": name, "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{directory}/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "a-x";\nimport "b-y";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "packages/a/x/src/index.ts",
        "packages/b/y/src/index.ts",
    }


def test_braced_positive_does_not_remove_literal_exclusion(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {
            "workspaces": [
                "packages/**",
                "!packages/a/**",
                "packages/{a,b}/x",
            ]
        },
    )
    for directory in ("a/x", "b/x"):
        name = directory.replace("/", "-")
        write_json(
            tmp_path,
            f"packages/{directory}/package.json",
            {"name": name, "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{directory}/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "a-x";\nimport "b-x";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/b/x/src/index.ts"}


def test_workspace_globs_exclude_hidden_directories_by_default(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    for directory, name in (("visible", "visible"), (".hidden", "hidden")):
        write_json(
            tmp_path,
            f"packages/{directory}/package.json",
            {"name": name, "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{directory}/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "visible";\nimport "hidden";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/visible/src/index.ts"}


def test_workspace_globs_can_explicitly_include_hidden_directories(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/.*"]})
    write_json(
        tmp_path,
        "packages/.hidden/package.json",
        {"name": "hidden", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/.hidden/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "hidden";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/.hidden/src/index.ts"}


def test_workspace_globs_normalize_windows_separators(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": [r"packages\*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/tool/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/tool/src/index.ts"}


def test_repeated_workspace_patterns_are_deduplicated(tmp_path):
    write_json(
        tmp_path,
        "package.json",
        {"workspaces": [*["packages/*"] * 500, *["!packages/excluded"] * 500]},
    )
    for directory in ("included", "excluded"):
        write_json(
            tmp_path,
            f"packages/{directory}/package.json",
            {"name": directory, "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{directory}/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "included";\nimport "excluded";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/included/src/index.ts"}


def test_excessive_distinct_workspace_patterns_disable_workspace_resolution(tmp_path):
    positives = [f"packages/positive-{index}" for index in range(300)]
    negatives = [f"!packages/negative-{index}" for index in range(300)]
    write_json(
        tmp_path,
        "package.json",
        {"workspaces": ["packages/tool", *positives, *negatives]},
    )
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/tool/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()
    assert "safe analysis limits" in "\n".join(graph.warnings).lower()


def test_excessive_workspace_pattern_complexity_disables_resolution(tmp_path):
    patterns = ["/".join(["packages", f"group-{index}", *(["**"] * 100)]) for index in range(25)]
    write_json(
        tmp_path,
        "package.json",
        {"workspaces": ["packages/tool", *patterns]},
    )
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/tool/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()
    assert "safe analysis limits" in "\n".join(graph.warnings).lower()


def test_excessive_workspace_brace_output_disables_resolution(tmp_path):
    long_prefix = "x" * 60_000
    pattern = f"packages/{long_prefix}{{a,b,c,d,e,f,g,h}}"
    write_json(
        tmp_path,
        "package.json",
        {"workspaces": ["packages/tool", pattern]},
    )
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/tool/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()
    assert "safe analysis limits" in "\n".join(graph.warnings).lower()


def test_workspace_globs_support_bounded_brace_ranges(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/{1..2}"]})
    for name in ("1", "2", "3"):
        write_json(
            tmp_path,
            f"packages/{name}/package.json",
            {"name": f"tool-{name}", "source": "./src/index.ts"},
        )
        write(tmp_path, f"packages/{name}/src/index.ts", "export {};\n")
    write(
        tmp_path,
        "src/app.ts",
        'import "tool-1";\nimport "tool-2";\nimport "tool-3";\n',
    )

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {
        "packages/1/src/index.ts",
        "packages/2/src/index.ts",
    }


@pytest.mark.parametrize(
    "pattern",
    [
        "/".join(["**"] * 1_200),
        "packages/{1..1000000000}",
        f"packages/{{{'9' * 5_000}..2}}",
    ],
)
def test_adversarial_workspace_globs_do_not_abort_scan(tmp_path, pattern):
    write_json(tmp_path, "package.json", {"workspaces": [pattern]})
    write_json(
        tmp_path,
        "packages/1/package.json",
        {"name": "tool", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/1/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

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


def test_symlink_loop_in_workspace_target_warns_instead_of_aborting(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/loop/package.json",
        {"name": "loop", "exports": {".": "./loop"}},
    )
    try:
        (tmp_path / "packages/loop/loop").symlink_to("loop")
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    write(tmp_path, "packages/loop/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "loop";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()
    assert "could not resolve" in "\n".join(graph.warnings).lower()


def test_malformed_workspace_subpaths_do_not_alias_package_root(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {
            "name": "tool",
            "exports": {
                ".": "./src/index.ts",
                "./*": "./src/*.ts",
            },
        },
    )
    write(tmp_path, "packages/tool/src/index.ts", "export {};\n")
    write(tmp_path, "packages/tool/src/feature.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool/";\nimport "tool//feature";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()


@pytest.mark.parametrize(
    "specifier",
    [
        "tool/../secret",
        "tool/./secret",
        "tool/%2e%2e/secret",
        "tool/src%2fsecret",
    ],
)
def test_workspace_request_subpaths_reject_forbidden_segments(tmp_path, specifier):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {"./*": "./src/*"}},
    )
    write(tmp_path, "packages/tool/src/secret.ts", "export {};\n")
    write(tmp_path, "packages/tool/secret.ts", "export {};\n")
    write(tmp_path, "src/app.ts", f'import "{specifier}";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()


def test_workspace_export_wildcard_rejects_forbidden_capture(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {"./x*": "./dir/.*/secret.ts"}},
    )
    write(tmp_path, "packages/tool/secret.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool/x.";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()


@pytest.mark.parametrize(
    ("target", "candidate"),
    [
        ("./src/./secret.ts", "packages/tool/src/secret.ts"),
        ("./src/%2e%2e/secret.ts", "packages/tool/src/%2e%2e/secret.ts"),
        ("./NODE_MODULES/x.ts", "packages/tool/NODE_MODULES/x.ts"),
        ("./src%2fsecret.ts", "packages/tool/src%2fsecret.ts"),
    ],
)
def test_workspace_export_targets_reject_forbidden_segments(tmp_path, target, candidate):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/tool/package.json",
        {"name": "tool", "exports": {".": target}},
    )
    write(tmp_path, candidate, "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == set()


def test_utf8_bom_in_workspace_manifests_is_accepted(tmp_path):
    write(tmp_path, "package.json", '\ufeff{"workspaces":["packages/*"]}')
    write(
        tmp_path,
        "packages/tool/package.json",
        '\ufeff{"name":"tool","source":"./src/index.ts"}',
    )
    write(tmp_path, "packages/tool/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "tool";\n')

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"packages/tool/src/index.ts"}
    assert graph.warnings == []


def test_excessively_nested_workspace_exports_warn_without_aborting(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    export: object = "./src/index.ts"
    for _ in range(80):
        export = {"import": export}
    write_json(
        tmp_path,
        "packages/deep/package.json",
        {"name": "deep", "exports": {".": export}},
    )
    write(tmp_path, "packages/deep/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "deep";\nimport "./local";\n')
    write(tmp_path, "src/local.ts", "export {};\n")

    graph = scan_repository(tmp_path)

    assert targets_for(graph, "src/app.ts") == {"src/local.ts"}
    assert "nested too deeply" in "\n".join(graph.warnings).lower()


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


def test_live_workspace_wins_over_its_historical_rename_overlay(tmp_path):
    write_json(tmp_path, "package.json", {"workspaces": ["packages/*"]})
    write_json(
        tmp_path,
        "packages/new/package.json",
        {"name": "shared", "source": "./src/index.ts"},
    )
    write(tmp_path, "packages/new/src/index.ts", "export {};\n")
    write(tmp_path, "src/app.ts", 'import "shared";\n')

    graph = scan_repository(
        tmp_path,
        virtual_files={
            "packages/old/package.json": json.dumps({"name": "shared", "source": "./src/index.ts"}),
            "packages/old/src/index.ts": "export {};\n",
        },
    )
    report = analyze_impact(
        tmp_path,
        graph,
        ["packages/old/src/index.ts", "packages/new/src/index.ts"],
    )

    assert targets_for(graph, "src/app.ts") == {"packages/new/src/index.ts"}
    assert [item.path for item in report.impacted_files] == ["src/app.ts"]
    assert not any("ambiguous" in warning.lower() for warning in graph.warnings)


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
