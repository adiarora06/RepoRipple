import json

from reporipple.models import ImpactedFile, ImpactReport
from reporipple.report import render_json, render_markdown


def sample_report() -> ImpactReport:
    return ImpactReport(
        repository="demo",
        changed_files=["src/store.py"],
        impacted_files=[
            ImpactedFile("src/service.py", 1, ("src/store.py", "src/service.py"))
        ],
        suggested_tests=["tests/test_service.py"],
        documentation_to_review=[],
        risk_level="low",
        risk_reasons=["Localized change"],
        graph_files=3,
        graph_edges=1,
    )


def test_json_output_is_machine_readable():
    payload = json.loads(render_json(sample_report()))

    assert payload["risk_level"] == "low"
    assert payload["impacted_files"][0]["distance"] == 1


def test_markdown_output_explains_dependency_path():
    output = render_markdown(sample_report())

    assert "RepoRipple impact report: demo" in output
    assert "`src/store.py` → `src/service.py`" in output
