"""Command-line interface for RepoRipple."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reporipple.analysis import analyze_impact
from reporipple.explain import (
    ExplanationError,
    build_evidence_bundle,
    build_openrouter_request,
    explain_report,
    explanation_to_dict,
    render_explanation_markdown,
    render_preview_markdown,
)
from reporipple.git import GitError, changed_files
from reporipple.report import render_json, render_markdown
from reporipple.scanner import scan_repository

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reporipple",
        description="Trace the blast radius of a Git change before it surprises you.",
    )
    parser.add_argument(
        "path", nargs="?", default=".", help="Repository path (default: current directory)"
    )
    parser.add_argument("--base", help="Compare BASE...HEAD instead of worktree changes")
    parser.add_argument(
        "--changed",
        action="append",
        default=[],
        metavar="PATH",
        help="Analyze an explicit changed path; repeat for multiple paths",
    )
    parser.add_argument("--max-depth", type=int, default=4, help="Maximum reverse dependency depth")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--fail-on",
        choices=("medium", "high"),
        help="Exit with status 2 when the report reaches this risk level",
    )
    parser.add_argument("--output", type=Path, help="Write the report to a file instead of stdout")
    explanation = parser.add_mutually_exclusive_group()
    explanation.add_argument(
        "--explain",
        action="store_true",
        help="Append an opt-in, privacy-filtered OpenRouter explanation",
    )
    explanation.add_argument(
        "--explain-preview",
        action="store_true",
        help="Show the exact sanitized OpenRouter request without sending it",
    )
    parser.add_argument(
        "--explain-model",
        help=(
            "Pinned OpenRouter provider/model slug; valid only with --explain or "
            "--explain-preview"
        ),
    )
    return parser


def build_mcp_parser() -> argparse.ArgumentParser:
    """Build the parser for the local MCP server."""
    parser = argparse.ArgumentParser(
        prog="reporipple mcp",
        description="Expose RepoRipple's read-only analysis tools over MCP stdio.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help=(
            "Limit repository access to this directory and its descendants "
            "(default: current directory)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "mcp":
        return _run_mcp(raw_args[1:])

    args = build_parser().parse_args(raw_args)
    if args.explain_model and not (args.explain or args.explain_preview):
        print("error: --explain-model requires --explain or --explain-preview", file=sys.stderr)
        return 1
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: repository path does not exist: {root}", file=sys.stderr)
        return 1
    if args.max_depth < 1:
        print("error: --max-depth must be at least 1", file=sys.stderr)
        return 1

    try:
        changed = args.changed or changed_files(root, args.base)
        graph = scan_repository(root)
        report = analyze_impact(root, graph, changed, max_depth=args.max_depth)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rendered = render_json(report) if args.format == "json" else render_markdown(report)
    if args.explain_preview:
        bundle = build_evidence_bundle(report)
        try:
            request_payload = build_openrouter_request(bundle, model=args.explain_model)
        except ExplanationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.format == "json":
            rendered = json.dumps(
                {
                    "deterministic_report": report.to_dict(),
                    "openrouter_preview": {
                        "request_sent": False,
                        "request": request_payload,
                    },
                },
                indent=2,
                sort_keys=True,
            )
        else:
            rendered = rendered.rstrip() + "\n\n" + render_preview_markdown(request_payload)
    elif args.explain:
        try:
            bundle, explanation = explain_report(report, model=args.explain_model)
        except ExplanationError as exc:
            print(
                f"warning: optional OpenRouter explanation unavailable: {exc}; "
                "the deterministic report is unchanged",
                file=sys.stderr,
            )
        except Exception:
            print(
                "warning: optional OpenRouter explanation failed unexpectedly; "
                "the deterministic report is unchanged",
                file=sys.stderr,
            )
        else:
            if args.format == "json":
                rendered = json.dumps(
                    {
                        "deterministic_report": report.to_dict(),
                        "openrouter_explanation": explanation_to_dict(
                            explanation, bundle.local_labels
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
            else:
                rendered = (
                    rendered.rstrip()
                    + "\n\n"
                    + render_explanation_markdown(explanation, bundle.local_labels)
                )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.fail_on and RISK_ORDER[report.risk_level] >= RISK_ORDER[args.fail_on]:
        return 2
    return 0


def _run_mcp(argv: list[str]) -> int:
    args = build_mcp_parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"error: allowed root does not exist: {root}", file=sys.stderr)
        return 1

    try:
        from reporipple.mcp_server import run_server
    except (ImportError, ModuleNotFoundError):
        print(
            "error: MCP runtime is unavailable; reinstall RepoRipple and its dependencies",
            file=sys.stderr,
        )
        return 1

    run_server(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
