from reporipple.impact_map import MAX_MAP_NODES, render_impact_map
from reporipple.models import ImpactedFile, ImpactReport


def sample_report() -> ImpactReport:
    return ImpactReport(
        repository="checkout-service",
        changed_files=["src/billing/store.py"],
        impacted_files=[
            ImpactedFile(
                "src/billing/service.py",
                1,
                ("src/billing/store.py", "src/billing/service.py"),
            ),
            ImpactedFile(
                "src/api/checkout.py",
                2,
                (
                    "src/billing/store.py",
                    "src/billing/service.py",
                    "src/api/checkout.py",
                ),
            ),
            ImpactedFile(
                "tests/test_checkout.py",
                3,
                (
                    "src/billing/store.py",
                    "src/billing/service.py",
                    "src/api/checkout.py",
                    "tests/test_checkout.py",
                ),
            ),
        ],
        suggested_tests=["tests/test_checkout.py"],
        documentation_to_review=["README.md"],
        risk_level="high",
        risk_reasons=["Sensitive area changed: billing"],
        graph_files=4,
        graph_edges=3,
        warnings=[],
    )


def test_html_impact_map_is_self_contained_and_deterministic():
    first = render_impact_map(sample_report())
    second = render_impact_map(sample_report())

    assert first == second
    assert first.startswith("<!doctype html>")
    assert "RepoRipple impact map — checkout-service" in first
    assert "default-src 'none'" in first
    assert "http://" not in first
    assert "https://" not in first
    assert 'class="risk risk-high"' in first
    assert 'class="node node-changed"' in first
    assert 'class="node node-test"' in first
    assert 'class="edge"' in first
    assert "src/billing/store.py → src/billing/service.py → src/api/checkout.py" in first
    assert 'role="img"' in first
    assert 'tabindex="0" aria-label="Scrollable blast-radius map"' in first
    assert "No source code or repository paths were" in first
    assert "transmitted.</footer>" in first


def test_html_impact_map_escapes_repository_controlled_text():
    report = sample_report()
    report.repository = 'demo</title><script>alert("x")</script>'
    report.changed_files = ['src/<img src=x onerror="alert(1)">.py']
    report.impacted_files = []
    report.suggested_tests = []
    report.risk_reasons = ["Review <unsafe> & verify"]

    output = render_impact_map(report)

    assert "<script>" not in output
    assert "<img src=x" not in output
    assert "demo&lt;/title&gt;&lt;script&gt;" in output
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in output
    assert "Review &lt;unsafe&gt; &amp; verify" in output


def test_html_map_caps_visual_nodes_but_keeps_complete_review_list():
    report = sample_report()
    report.impacted_files = [
        ImpactedFile(
            f"src/consumer_{index:03}.py",
            1,
            ("src/billing/store.py", f"src/consumer_{index:03}.py"),
        )
        for index in range(MAX_MAP_NODES + 5)
    ]

    output = render_impact_map(report)

    assert f"Map limited to {MAX_MAP_NODES} nodes" in output
    assert "src/consumer_084.py" in output
    assert output.count('class="node node-') == MAX_MAP_NODES


def test_html_map_includes_suggested_test_without_a_dependency_edge():
    report = sample_report()
    report.impacted_files = report.impacted_files[:1]
    report.suggested_tests = ["tests/test_store.py"]

    output = render_impact_map(report)

    assert "tests/test_store.py" in output
    assert "SUGGESTED TEST" in output
    assert output.count('class="node node-test"') == 1


def test_html_map_reserves_space_for_dependents_and_tests_after_a_wide_change():
    report = sample_report()
    report.changed_files = [f"src/changed_{index:03}.py" for index in range(MAX_MAP_NODES + 20)]
    report.impacted_files = [
        ImpactedFile("src/dependent.py", 1, ("src/changed_000.py", "src/dependent.py"))
    ]
    report.suggested_tests = ["tests/test_independent.py"]

    output = render_impact_map(report)

    assert output.count('class="node node-') == MAX_MAP_NODES
    assert "src/dependent.py" in output
    assert "tests/test_independent.py" in output
    assert "SUGGESTED TEST" in output
