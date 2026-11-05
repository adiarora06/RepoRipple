"""Self-contained visual impact reports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import escape

from reporipple.models import ImpactReport

MAX_MAP_NODES = 80
NODE_WIDTH = 232
NODE_HEIGHT = 58
COLUMN_GAP = 72
ROW_GAP = 26
MAP_PADDING = 36


@dataclass(frozen=True)
class _MapNode:
    path: str
    distance: int
    kind: str


def render_impact_map(report: ImpactReport) -> str:
    """Render a portable HTML report with a deterministic blast-radius map."""
    graph = _render_graph(report)
    changed = _code_list(report.changed_files, "No changed files detected.")
    tests = _code_list(report.suggested_tests, "No matching tests or test command detected.")
    reasons = _code_list(report.risk_reasons, "No elevated risk signals detected.")
    impacted = _render_impacted_files(report)
    documentation = _optional_section(
        "Documentation to review",
        _code_list(report.documentation_to_review, ""),
        bool(report.documentation_to_review),
    )
    warnings = _optional_section(
        "Scanner warnings",
        _code_list(report.warnings, ""),
        bool(report.warnings),
        class_name="warnings",
    )
    repository = escape(report.repository)
    risk = escape(report.risk_level)
    impact_count = len(report.impacted_files)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;
                 base-uri 'none'; form-action 'none'">
  <title>RepoRipple impact map — {repository}</title>
  <style>
    :root {{ color-scheme: dark; --ink: #edf3ff; --muted: #9aa9c4; --line: #283957;
      --panel: #101a2e; --panel-strong: #15233b; --accent: #70a5ff; --teal: #5ee5c2;
      --amber: #ffc86b; --red: #ff7f8f; --shadow: 0 24px 70px rgba(0, 0, 0, .28); }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-width: 320px; background:
      radial-gradient(circle at 8% 0%, rgba(74, 126, 255, .18), transparent 32rem),
      radial-gradient(circle at 88% 8%, rgba(50, 220, 185, .10), transparent 28rem), #09111f;
      color: var(--ink); font: 15px/1.55 ui-sans-serif, system-ui, -apple-system,
      BlinkMacSystemFont,
      "Segoe UI", sans-serif; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0 72px; }}
    header {{ display: grid; grid-template-columns: 1fr auto; gap: 28px; align-items: end;
      padding: 30px; border: 1px solid var(--line); border-radius: 22px;
      background: linear-gradient(145deg, rgba(21, 35, 59, .96), rgba(12, 22, 39, .96));
      box-shadow: var(--shadow); }}
    .eyebrow {{ margin: 0 0 8px; color: var(--teal); font-size: 12px; font-weight: 800;
      letter-spacing: .14em; text-transform: uppercase; }}
    h1 {{ margin: 0; font-size: clamp(28px, 5vw, 48px); line-height: 1.05;
      letter-spacing: -.04em; }}
    .lede {{ max-width: 680px; margin: 14px 0 0; color: var(--muted); font-size: 17px; }}
    .risk {{ display: grid; gap: 5px; min-width: 146px; padding: 18px 20px; border-radius: 16px;
      border: 1px solid color-mix(in srgb, var(--risk) 44%, transparent);
      background: color-mix(in srgb, var(--risk) 12%, var(--panel)); }}
    .risk span {{ color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .12em;
      text-transform: uppercase; }}
    .risk strong {{ color: var(--risk); font-size: 23px; text-transform: capitalize; }}
    .risk-low {{ --risk: var(--teal); }} .risk-medium {{ --risk: var(--amber); }}
    .risk-high {{ --risk: var(--red); }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px;
      margin: 18px 0; }}
    .stat, .panel {{ border: 1px solid var(--line); background: rgba(16, 26, 46, .9); }}
    .stat {{ padding: 18px; border-radius: 15px; }}
    .stat strong {{ display: block; font-size: 25px; line-height: 1.1; }}
    .stat span {{ color: var(--muted); font-size: 12px; }}
    .panel {{ margin-top: 18px; padding: 24px; border-radius: 18px;
      box-shadow: 0 14px 36px rgba(0,0,0,.16); }}
    .panel h2 {{ margin: 0 0 4px; font-size: 20px; letter-spacing: -.02em; }}
    .panel-copy {{ margin: 0 0 18px; color: var(--muted); }}
    .map-frame {{ overflow-x: auto; padding: 12px; border: 1px solid #20324f; border-radius: 14px;
      background: #0a1323; }}
    svg {{ display: block; max-width: none; }}
    .edge {{ fill: none; stroke: #435b82; stroke-width: 2; opacity: .82; }}
    .node rect {{ stroke-width: 1.5; }}
    .node text {{ fill: var(--ink); font-size: 12px; font-weight: 650; }}
    .node .meta {{ fill: #95a8c7; font-size: 10px; font-weight: 750; letter-spacing: .08em; }}
    .node-changed rect {{ fill: #1e3f75; stroke: #70a5ff; }}
    .node-impact rect {{ fill: #12263b; stroke: #42678f; }}
    .node-test rect {{ fill: #123a35; stroke: #54d8b7; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 14px; color: var(--muted);
      font-size: 12px; }}
    .legend span::before {{ content: ""; display: inline-block; width: 9px; height: 9px;
      margin-right: 7px; border-radius: 3px; background: var(--legend); }}
    .legend .changed {{ --legend: #70a5ff; }} .legend .affected {{ --legend: #42678f; }}
    .legend .test {{ --legend: #54d8b7; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    ul {{ margin: 14px 0 0; padding: 0; list-style: none; }}
    li {{ margin-top: 8px; color: #c9d5e9; }}
    code {{ overflow-wrap: anywhere; color: #dbe7ff; font: 12.5px/1.45 ui-monospace, SFMono-Regular,
      Menlo, Consolas, monospace; }}
    .impact-list li {{ display: grid; grid-template-columns: auto 1fr; gap: 12px; padding: 12px 0;
      border-top: 1px solid rgba(58, 78, 112, .45); }}
    .distance {{ min-width: 32px; height: 25px; padding: 3px 8px; border-radius: 999px;
      background: #1e3150; color: var(--accent); text-align: center; font-size: 11px;
      font-weight: 800; }}
    .via {{ display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }}
    .warnings {{ border-color: #6d5430; background: rgba(52, 37, 17, .72); }}
    footer {{ margin-top: 24px; color: #7788a5; text-align: center; font-size: 12px; }}
    @media (max-width: 720px) {{ header {{ grid-template-columns: 1fr; }} .risk {{ min-width: 0; }}
      .stats {{ grid-template-columns: repeat(2, 1fr); }} .grid {{ grid-template-columns: 1fr; }}
      .panel {{ padding: 18px; }} }}
    @media (prefers-reduced-motion: no-preference) {{
      .panel, header {{ animation: rise .45s ease-out both; }}
      .panel:nth-of-type(2) {{ animation-delay: .06s; }} @keyframes rise {{ from {{ opacity: 0;
      transform: translateY(8px); }} }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <p class="eyebrow">RepoRipple impact map</p>
      <h1>{repository}</h1>
      <p class="lede">A deterministic view of how this change travels through the repository,
        which checks matter, and why the risk level was assigned.</p>
    </div>
    <div class="risk risk-{risk}"><span>Deterministic risk</span><strong>{risk}</strong></div>
  </header>
  <section class="stats" aria-label="Repository impact statistics">
    <div class="stat"><strong>{len(report.changed_files)}</strong><span>changed files</span></div>
    <div class="stat"><strong>{impact_count}</strong><span>affected files</span></div>
    <div class="stat"><strong>{report.graph_files}</strong><span>source files scanned</span></div>
    <div class="stat"><strong>{report.graph_edges}</strong><span>dependency edges</span></div>
  </section>
  <section class="panel">
    <h2>Blast-radius map</h2>
    <p class="panel-copy">Follow the ripple from each changed file to its direct and
      transitive dependents.</p>
    <div class="map-frame" tabindex="0" aria-label="Scrollable blast-radius map">{graph}</div>
    <div class="legend" aria-label="Map legend"><span class="changed">Changed</span>
      <span class="affected">Affected</span><span class="test">Suggested test</span></div>
  </section>
  <div class="grid">
    <section class="panel"><h2>Changed files</h2>{changed}</section>
    <section class="panel"><h2>Suggested verification</h2>{tests}</section>
  </div>
  <section class="panel"><h2>Review paths</h2>{impacted}</section>
  <section class="panel"><h2>Risk signals</h2>{reasons}</section>
  {documentation}
  {warnings}
  <footer>Generated locally by RepoRipple. No source code or repository paths were
    transmitted.</footer>
</main>
</body>
</html>
"""


def _render_graph(report: ImpactReport) -> str:
    nodes = _select_nodes(report)
    if not nodes:
        return '<p class="panel-copy">No changed or affected source files to map.</p>'

    grouped: dict[int, list[_MapNode]] = {}
    for node in nodes:
        grouped.setdefault(node.distance, []).append(node)
    for values in grouped.values():
        values.sort(key=lambda node: node.path)

    positions: dict[str, tuple[int, int]] = {}
    for distance, values in grouped.items():
        for index, node in enumerate(values):
            positions[node.path] = (
                MAP_PADDING + distance * (NODE_WIDTH + COLUMN_GAP),
                MAP_PADDING + index * (NODE_HEIGHT + ROW_GAP),
            )

    selected = set(positions)
    edges = {
        (source, target)
        for item in report.impacted_files
        for source, target in zip(item.via, item.via[1:], strict=False)
        if source in selected and target in selected
    }
    edge_markup = []
    for source, target in sorted(edges):
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        start_x = source_x + NODE_WIDTH
        start_y = source_y + NODE_HEIGHT // 2
        end_x = target_x
        end_y = target_y + NODE_HEIGHT // 2
        bend = max(24, (end_x - start_x) // 2)
        edge_markup.append(
            f'<path class="edge" marker-end="url(#arrow)" '
            f'd="M {start_x} {start_y} C {start_x + bend} {start_y}, '
            f'{end_x - bend} {end_y}, {end_x} {end_y}"/>'
        )

    node_markup = []
    for node in nodes:
        x, y = positions[node.path]
        label = escape(_shorten(node.path))
        full_path = escape(node.path)
        meta = "CHANGED" if node.distance == 0 else f"DISTANCE {node.distance}"
        node_markup.append(
            f'<g class="node node-{node.kind}" transform="translate({x} {y})">'
            f"<title>{full_path}</title><rect width=\"{NODE_WIDTH}\" "
            f"height=\"{NODE_HEIGHT}\" rx=\"11\"/>"
            f'<text x="14" y="24">{label}</text>'
            f'<text class="meta" x="14" y="43">{meta}</text></g>'
        )

    width = max(
        720,
        MAP_PADDING * 2 + (max(grouped) + 1) * NODE_WIDTH + max(grouped) * COLUMN_GAP,
    )
    height = max(
        230,
        MAP_PADDING * 2
        + max(Counter(node.distance for node in nodes).values()) * (NODE_HEIGHT + ROW_GAP),
    )
    omitted = len(report.changed_files) + len(report.impacted_files) - len(nodes)
    note = (
        f'<text x="{MAP_PADDING}" y="{height - 14}" fill="#95a8c7" font-size="11">'
        f"Map limited to {MAX_MAP_NODES} nodes; {omitted} additional files remain "
        "in the review list."
        "</text>"
        if omitted > 0
        else ""
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="map-title map-description">'
        '<title id="map-title">Repository change blast radius</title>'
        '<desc id="map-description">Changed files flow left to right into direct and transitive '
        'dependents. Suggested tests are highlighted in green.</desc>'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
        'fill="#5c759e"/></marker></defs>'
        + "".join(edge_markup)
        + "".join(node_markup)
        + note
        + "</svg>"
    )


def _select_nodes(report: ImpactReport) -> list[_MapNode]:
    tests = set(report.suggested_tests)
    candidates = [
        *(_MapNode(path, 0, "changed") for path in sorted(report.changed_files)),
        *(
            _MapNode(item.path, item.distance, "test" if item.path in tests else "impact")
            for item in report.impacted_files
        ),
    ]
    unique: dict[str, _MapNode] = {}
    for node in sorted(candidates, key=lambda item: (item.distance, item.path)):
        unique.setdefault(node.path, node)
    return list(unique.values())[:MAX_MAP_NODES]


def _render_impacted_files(report: ImpactReport) -> str:
    if not report.impacted_files:
        return "<p>No reverse dependencies detected.</p>"
    rows = []
    for item in report.impacted_files:
        path = escape(item.path)
        via = " → ".join(escape(part) for part in item.via)
        rows.append(
            '<li><span class="distance" title="Dependency distance">'
            f"{item.distance}</span><div><code>{path}</code>"
            f'<span class="via">via {via}</span></div></li>'
        )
    return '<ul class="impact-list">' + "".join(rows) + "</ul>"


def _code_list(items: list[str], empty: str) -> str:
    if not items:
        return f"<p>{escape(empty)}</p>"
    return "<ul>" + "".join(f"<li><code>{escape(item)}</code></li>" for item in items) + "</ul>"


def _optional_section(
    title: str,
    body: str,
    visible: bool,
    *,
    class_name: str = "",
) -> str:
    if not visible:
        return ""
    classes = "panel" + (f" {class_name}" if class_name else "")
    return f'<section class="{classes}"><h2>{escape(title)}</h2>{body}</section>'


def _shorten(path: str, limit: int = 31) -> str:
    if len(path) <= limit:
        return path
    left = (limit - 1) // 2
    right = limit - left - 1
    return f"{path[:left]}…{path[-right:]}"
