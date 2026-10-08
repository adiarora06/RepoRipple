import pytest

from reporipple.analysis import analyze_impact
from reporipple.models import DependencyEdge, RepositoryGraph


def test_traces_transitive_reverse_dependencies(tmp_path):
    graph = RepositoryGraph(
        files={"src/store.py", "src/service.py", "src/api.py", "tests/test_service.py"},
        edges=[
            DependencyEdge("src/service.py", "src/store.py", "python-import"),
            DependencyEdge("src/api.py", "src/service.py", "python-import"),
            DependencyEdge("tests/test_service.py", "src/service.py", "python-import"),
        ],
    )

    report = analyze_impact(tmp_path, graph, ["src/store.py"])

    assert [(item.path, item.distance) for item in report.impacted_files] == [
        ("src/service.py", 1),
        ("src/api.py", 2),
        ("tests/test_service.py", 2),
    ]
    assert report.suggested_tests == ["tests/test_service.py"]


def test_flags_sensitive_wide_changes_as_high_risk(tmp_path):
    files = {"src/auth/session.py", *(f"src/consumer_{index}.py" for index in range(4))}
    graph = RepositoryGraph(
        files=files,
        edges=[
            DependencyEdge(f"src/consumer_{index}.py", "src/auth/session.py", "python-import")
            for index in range(4)
        ],
    )

    report = analyze_impact(tmp_path, graph, ["src/auth/session.py"])

    assert report.risk_level == "high"
    assert any("Sensitive area" in reason for reason in report.risk_reasons)
    assert any("Moderate blast radius" in reason for reason in report.risk_reasons)


@pytest.mark.parametrize(
    ("path", "concept"),
    [
        ("src/payment.py", "payment"),
        ("src/auth_service.py", "auth"),
        ("src/paymentGateway.ts", "payment"),
        ("src/security-check.ts", "security"),
        ("src/migrations.py", "migration"),
        ("src/permissions.ts", "permissions"),
    ],
)
def test_detects_sensitive_concepts_in_file_stems(tmp_path, path, concept):
    graph = RepositoryGraph(files={path})

    report = analyze_impact(tmp_path, graph, [path])

    assert report.risk_level == "high"
    assert f"Sensitive area changed: {concept}" in report.risk_reasons


def test_reports_sensitive_impacted_files(tmp_path):
    graph = RepositoryGraph(
        files={"src/shared.py", "src/payment_service.py", "src/authGateway.ts"},
        edges=[
            DependencyEdge("src/payment_service.py", "src/shared.py", "python-import"),
            DependencyEdge("src/authGateway.ts", "src/shared.py", "typescript-import"),
        ],
    )

    report = analyze_impact(tmp_path, graph, ["src/shared.py"])

    assert report.risk_level == "medium"
    assert (
        "Sensitive dependent files affected: src/authGateway.ts (auth); "
        "src/payment_service.py (payment)"
    ) in report.risk_reasons


def test_ignores_benign_sensitive_substrings(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    paths = {
        "src/author.py",
        "src/paymentology.py",
        "src/securitys.py",
        "src/migratory.py",
    }
    graph = RepositoryGraph(files=paths)

    for path in sorted(paths):
        report = analyze_impact(tmp_path, graph, [path])

        assert report.risk_level == "low"
        assert not any("Sensitive" in reason for reason in report.risk_reasons)


@pytest.mark.parametrize("path", ["tests/test_payment.py", "docs/authentication.md"])
def test_sensitive_terms_in_tests_and_docs_do_not_raise_risk(tmp_path, path):
    graph = RepositoryGraph(files={path})

    report = analyze_impact(tmp_path, graph, [path])

    assert report.risk_level == "low"
    assert not any("Sensitive" in reason for reason in report.risk_reasons)


def test_keeps_configuration_changes_medium_risk(tmp_path):
    graph = RepositoryGraph(files={"package.json"})

    report = analyze_impact(tmp_path, graph, ["package.json"])

    assert report.risk_level == "medium"
    assert "Runtime, dependency, or deployment configuration changed" in report.risk_reasons


@pytest.mark.parametrize(
    "path",
    [
        "packages/web/tsconfig.json",
        "packages/web/tsconfig.build.json",
        "apps/admin/jsconfig.json",
        "apps/admin/jsconfig.test.json",
    ],
)
def test_nested_js_and_ts_configs_count_as_configuration_risk(tmp_path, path):
    graph = RepositoryGraph(files={path})

    report = analyze_impact(tmp_path, graph, [path])

    assert report.risk_level == "medium"
    assert "Runtime, dependency, or deployment configuration changed" in report.risk_reasons


@pytest.mark.parametrize(
    "path", ["packages/web/tsconfig.build.json", "apps/admin/jsconfig.json"]
)
def test_nested_js_and_ts_configs_trigger_documentation_guidance(tmp_path, path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    graph = RepositoryGraph(files={path})

    report = analyze_impact(tmp_path, graph, [path])

    assert report.documentation_to_review == ["README.md", "docs", "CHANGELOG.md"]


def test_recommends_project_test_command_when_no_test_file_matches(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    graph = RepositoryGraph(files={"src/app.py"})

    report = analyze_impact(tmp_path, graph, ["src/app.py"])

    assert report.suggested_tests == ["pytest"]
