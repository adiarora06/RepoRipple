# Visual impact map

The RepoRipple impact map is a self-contained HTML review artifact generated from the same
deterministic `ImpactReport` as Markdown, JSON, GitHub Actions, and MCP responses. It makes a blast
radius easier to scan without introducing an account, hosted dashboard, or frontend build step.

## One-command workflow

```bash
reporipple /path/to/repository \
  --base origin/main \
  --format html \
  --output impact.html \
  --open
```

Use `--changed PATH` instead of `--base` to preview a proposed change before editing:

```bash
reporipple . \
  --changed src/billing/store.py \
  --format html \
  --output impact.html \
  --open
```

`--open` is explicit and requires `--format html` or `--format all` together with `--output`.
Without it, RepoRipple only writes the requested artifacts, which is suitable for CI and remote
environments.

Generate the complete review bundle from one scan and open its map with:

```bash
reporipple . --base origin/main --format all --output reporipple-reports --open
```

The output directory contains `impact.md`, `impact.json`, and `impact.html`.
RepoRipple renders all three first, stages them outside the destination, serializes concurrent
writers, and then replaces the previous bundle as a unit. It refuses to replace a directory that
contains unrelated files.

## What the map shows

- Changed files at distance zero.
- Direct and transitive dependents arranged by graph distance.
- Suggested test files highlighted separately from production dependents.
- Complete dependency paths, deterministic risk signals, verification guidance, and scanner
  warnings below the graph.

The canvas is capped at 80 nodes so exceptionally broad changes remain usable. The review-path
list below it is not truncated.

## Privacy and portability

The generated file contains no external JavaScript, fonts, images, analytics, or network calls. A
restrictive content-security policy blocks external resources, and repository-controlled text is
escaped before rendering. RepoRipple includes file paths and report evidence, but never embeds
source code or diffs.

HTML impact maps are deliberately deterministic. Optional OpenRouter explanations remain available
for Markdown and JSON reports but cannot be combined with `--format html`.

## GitHub Actions

The public Action writes `impact.md`, `impact.json`, and `impact.html`. Upload the
`html-report` output alongside the existing artifacts:

```yaml
- uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
  with:
    name: reporipple-impact
    path: |
      ${{ steps.reporipple.outputs.markdown-report }}
      ${{ steps.reporipple.outputs.json-report }}
      ${{ steps.reporipple.outputs.html-report }}
```

This output requires a RepoRipple release that includes the visual impact map. Keep the Action
reference pinned to that release's immutable commit SHA rather than switching to a mutable branch.

## Deterministic demo

[Watch the 22-second demo](https://github.com/adiarora06/RepoRipple/blob/v0.6.0/docs/assets/reporipple-impact-map-demo.mp4) (silent MP4, 720p, 1.1 MB). It
records the real report generated from the included checkout fixture; there is no mocked product
UI, external service, or API key.

From a RepoRipple source checkout:

```bash
./scripts/demo-impact-map.sh
```

The demo analyzes a small checkout service under `examples/checkout-demo`, writes the three-report
bundle to the operating system's temporary directory, and opens its map. Set `CI=true` to skip
opening the browser. The script runs the local source directly with Python and does not resolve or
download packages.
