import json
import re
import tomllib
from pathlib import Path

from reporipple import __version__

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PINNED_ACTION = re.compile(r"uses:\s+[^\s]+@([0-9a-f]{40})(?:\s|$)")


def test_package_and_registry_versions_match():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    assert project["project"]["version"] == __version__
    assert registry["version"] == __version__
    assert registry["packages"][0]["version"] == __version__


def test_pypi_readme_proves_mcp_namespace_ownership():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "<!-- mcp-name: io.github.adiarora06/reporipple -->" in readme


def test_published_markdown_has_no_relative_links():
    published_markdown = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]

    for path in published_markdown:
        content = path.read_text(encoding="utf-8")
        relative_links = re.findall(r"\[[^]]+\]\((?!https?://|#)([^)]+)\)", content)
        assert relative_links == [], f"relative Markdown links in {path.relative_to(ROOT)}"


def test_release_actions_are_immutably_pinned_and_publish_with_oidc():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    references = [line.strip() for line in workflow.splitlines() if "uses:" in line]

    assert references
    assert all(PINNED_ACTION.search(reference) for reference in references)
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "actions/attest-build-provenance@" in workflow
    assert "publish-python:\n    name: Publish to PyPI\n    needs: attest" in workflow
    assert "environment:\n      name: pypi" in workflow
    assert "login github-oidc" in workflow


def test_release_smoke_exercises_the_visual_review_bundle():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "/tmp/reporipple-smoke/bin/reporipple examples/checkout-demo" in workflow
    assert "--format all" in workflow
    assert "test -s /tmp/reporipple-smoke-reports/impact.md" in workflow
    assert "test -s /tmp/reporipple-smoke-reports/impact.json" in workflow
    assert "test -s /tmp/reporipple-smoke-reports/impact.html" in workflow


def test_sdist_excludes_large_demo_media():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = set(project["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"])

    assert "/docs/assets/*.mp4" in excluded
    assert "/docs/assets/*.png" in excluded
