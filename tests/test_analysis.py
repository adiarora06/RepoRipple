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


def test_recommends_project_test_command_when_no_test_file_matches(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    graph = RepositoryGraph(files={"src/app.py"})

    report = analyze_impact(tmp_path, graph, ["src/app.py"])

    assert report.suggested_tests == ["pytest"]
