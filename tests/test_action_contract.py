import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
ACTION = ROOT / "action.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "reporipple.yml"
PINNED_ACTION = re.compile(r"uses:\s+actions/[\w-]+@([0-9a-f]{40})(?:\s|$)")


def _official_action_references(document: str) -> list[str]:
    return [line.strip() for line in document.splitlines() if "uses: actions/" in line]


def test_public_action_emits_both_report_formats_and_summary():
    document = ACTION.read_text(encoding="utf-8")

    assert "using: composite" in document
    assert 'markdown_report="$reports_directory/impact.md"' in document
    assert 'json_report="$reports_directory/impact.json"' in document
    assert 'cat "$markdown_report" >> "$GITHUB_STEP_SUMMARY"' in document


def test_official_actions_are_pinned_to_immutable_commits():
    documents = [
        ACTION.read_text(encoding="utf-8"),
        WORKFLOW.read_text(encoding="utf-8"),
    ]
    references = [
        reference
        for document in documents
        for reference in _official_action_references(document)
    ]

    assert references
    assert all(PINNED_ACTION.search(reference) for reference in references)


def test_pr_workflow_keeps_analysis_unprivileged_and_skips_fork_comments():
    document = WORKFLOW.read_text(encoding="utf-8")
    analyze_job, comment_job = document.split("\n  comment:\n", maxsplit=1)

    assert "pull_request_target" not in document
    assert "pull-requests: write" not in analyze_job
    assert "contents: read" in analyze_job
    assert "persist-credentials: false" in analyze_job
    assert "github.event.pull_request.head.repo.full_name == github.repository" in comment_job
    assert "pull-requests: write" in comment_job
    assert "startsWith(marker)" in comment_job
