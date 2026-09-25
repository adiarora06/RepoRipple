"""Human- and machine-readable report rendering."""

from __future__ import annotations

import json

from reporipple.models import ImpactReport


def render_json(report: ImpactReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_markdown(report: ImpactReport) -> str:
    lines = [
        f"# RepoRipple impact report: {report.repository}",
        "",
        f"**Risk:** `{report.risk_level}` · **Graph:** {report.graph_files} files / "
        f"{report.graph_edges} dependency edges",
        "",
        "## Changed files",
        "",
    ]
    lines.extend(_bullets(report.changed_files, "No changed files detected."))
    lines.extend(["", "## Impacted files", ""])
    if report.impacted_files:
        lines.extend(
            f"- `{item.path}` — distance {item.distance} via "
            + " → ".join(f"`{path}`" for path in item.via)
            for item in report.impacted_files
        )
    else:
        lines.append("- No reverse dependencies detected.")

    lines.extend(["", "## Suggested verification", ""])
    lines.extend(_bullets(report.suggested_tests, "No matching tests or test command detected."))
    lines.extend(["", "## Risk signals", ""])
    lines.extend(_bullets(report.risk_reasons, "No elevated risk signals detected."))

    if report.documentation_to_review:
        lines.extend(["", "## Documentation to review", ""])
        lines.extend(_bullets(report.documentation_to_review, ""))
    if report.warnings:
        lines.extend(["", "## Scanner warnings", ""])
        lines.extend(_bullets(report.warnings, ""))
    return "\n".join(lines).rstrip() + "\n"


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"- `{item}`" for item in items] if items else [f"- {empty}"]
