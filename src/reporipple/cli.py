"""Command-line interface for RepoRipple."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reporipple.analysis import analyze_impact
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.fail_on and RISK_ORDER[report.risk_level] >= RISK_ORDER[args.fail_on]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
