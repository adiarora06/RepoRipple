# RepoRipple

<!-- mcp-name: io.github.adiarora06/reporipple -->

**Know what a code change can break before you merge it.**

[![PyPI](https://img.shields.io/pypi/v/reporipple?label=PyPI)](https://pypi.org/project/reporipple/)
[![Python versions](https://img.shields.io/pypi/pyversions/reporipple)](https://pypi.org/project/reporipple/)
[![CI](https://github.com/adiarora06/RepoRipple/actions/workflows/ci.yml/badge.svg)](https://github.com/adiarora06/RepoRipple/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/adiarora06/RepoRipple/blob/v0.3.0/LICENSE)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-6f42c1)](https://github.com/adiarora06/RepoRipple/blob/v0.3.0/docs/mcp.md)

RepoRipple is a local-first change-impact analyzer for engineers and coding agents. It builds a lightweight dependency graph from a repository, reads the current Git diff, traces reverse dependencies, recommends relevant tests, and emits a review-ready Markdown or JSON report.

The deterministic analyzer requires no API key, hosted service, source upload, or framework integration. An optional, explicitly requested OpenRouter explanation can turn its anonymized evidence into a short narrative without changing the underlying analysis.

[PyPI](https://pypi.org/project/reporipple/) ·
[Portfolio case study](https://www.adiarora.dev/open-source/reporipple) ·
[MCP setup](https://github.com/adiarora06/RepoRipple/blob/v0.3.0/docs/mcp.md) ·
[v0.3.0 release](https://github.com/adiarora06/RepoRipple/releases/tag/v0.3.0)

![RepoRipple traces a Git change through its dependency blast radius and produces a focused risk report](https://raw.githubusercontent.com/adiarora06/RepoRipple/v0.3.0/docs/assets/reporipple-hero.png)

## Why RepoRipple?

Code graphs explain how a repository is connected. RepoRipple applies that graph to the change in front of you:

- Which files depend on the code I changed?
- How far does the blast radius travel?
- Which tests are most relevant?
- Did I touch authentication, payments, deployment, or another sensitive area?
- Should this pull request be blocked for additional review?
- What structured context should I give a coding agent?

## Install and run

```bash
pip install reporipple

# Analyze staged, unstaged, and untracked changes.
reporipple .

# Compare a feature branch with main.
reporipple . --base origin/main

# Generate machine-readable context for an agent or automation.
reporipple . --base origin/main --format json --output impact.json

# Fail CI when a change reaches high risk.
reporipple . --base origin/main --fail-on high

# Audit the exact anonymized OpenRouter request without sending it.
reporipple . --base origin/main --explain-preview
```

Run it once without installing:

```bash
uvx reporipple . --base origin/main
```

## Three product surfaces

| Surface | Best for | Output |
| --- | --- | --- |
| CLI | Local review, scripts, and CI gates | Markdown or JSON impact report |
| GitHub Action | Pull-request evidence and risk thresholds | Job summary, artifact, and optional stable PR comment |
| MCP server | Codex, OpenCode, Cursor, Claude Code, and VS Code | Typed `forecast_change` and `analyze_worktree` tools |

## GitHub Action

Add RepoRipple to a pull-request workflow to create Markdown and JSON impact reports and append
the Markdown report to the GitHub job summary:

```yaml
name: RepoRipple

on:
  pull_request:

permissions:
  contents: read

jobs:
  impact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: reporipple
        uses: adiarora06/RepoRipple@996f43f28a51ba8d6788a73a349f4ebb0f47a186 # v0.3.0
        with:
          base: ${{ github.event.pull_request.base.sha }}
      - uses: actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4 # v5
        with:
          name: reporipple-impact
          path: |
            ${{ steps.reporipple.outputs.markdown-report }}
            ${{ steps.reporipple.outputs.json-report }}
```

The Action accepts `path`, `base`, `max-depth`, `fail-on`, and `reports-directory`. It outputs
`markdown-report`, `json-report`, and `risk-level`. For reproducible builds, pin RepoRipple to a
release commit SHA and use `fetch-depth: 0` so the requested base revision is available.

This repository's own [pull-request workflow](https://github.com/adiarora06/RepoRipple/blob/v0.3.0/.github/workflows/reporipple.yml) demonstrates a
fork-safe commenting design. Analysis runs with read-only contents access. A separate job updates
one stable RepoRipple comment only for branches in the same repository; fork pull requests keep
their report in the job summary and downloadable artifact without receiving a write-capable token.

## Coding-agent tools (MCP)

RepoRipple can expose the same deterministic analysis to Codex, OpenCode, Cursor,
Claude Code, and VS Code over a local, read-only MCP server. From a source checkout:

```bash
uv run reporipple mcp --root /path/to/allowed/workspace
```

Launch the published package without a clone:

```bash
uvx reporipple mcp --root /path/to/allowed/workspace
```

The server provides `forecast_change` for proposed edits and `analyze_worktree` for
actual Git changes. See the
[MCP setup guide](https://github.com/adiarora06/RepoRipple/blob/main/docs/mcp.md) for
client-specific commands and configuration.

The [architecture guide](https://github.com/adiarora06/RepoRipple/blob/v0.3.0/docs/architecture.md) explains how the CLI, GitHub Action,
MCP server, and optional explanation layer share one deterministic analysis engine.

## Example report

```markdown
# RepoRipple impact report: checkout-service

**Risk:** `high` · **Graph:** 84 files / 137 dependency edges

## Changed files
- `src/billing/store.py`

## Impacted files
- `src/billing/service.py` — distance 1 via `store.py` → `service.py`
- `src/api/checkout.py` — distance 2 via `store.py` → `service.py` → `checkout.py`

## Suggested verification
- `tests/test_billing_service.py`
- `tests/test_checkout.py`
```

## How it works

1. Discovers Python, JavaScript, and TypeScript source files.
2. Extracts Python imports with the standard-library AST and JS/TS imports with a focused parser.
3. Resolves JS/TS dependencies in a deterministic order: relative paths, the nearest
   `tsconfig.json` or `jsconfig.json` `paths` mappings, its `baseUrl`, and then npm/Yarn workspace
   packages declared by the root `package.json`.
4. Builds forward and reverse dependency relationships.
5. Gets added, modified, deleted, and renamed files from an explicit base revision or the local
   worktree.
6. Retains pre-change source for deleted and renamed files so their remaining dependents can still
   be traced.
7. Traverses dependents to a configurable depth.
8. Adds test recommendations, documentation reminders, and deterministic risk signals.

Workspace resolution is local and source-aware. RepoRipple matches imports to explicitly declared
`package.json` workspaces by package name, respects their public export boundaries, and follows
entry points that resolve to source files in the repository. Workspace globs support recursive
patterns, bounded brace alternatives and ranges, and exclusions. Conditional exports distinguish
ES module and CommonJS entry points: `.mts`/`.mjs` use the import profile, `.cts`/`.cjs` use the
require profile, and ambiguous TypeScript/JavaScript files conservatively inspect both. RepoRipple
also keeps applicable custom conditions declared before a syntax or `default` fallback so it does
not silently miss browser, platform, or source-only dependency edges.

Custom conditions are evaluated without assuming one runtime condition set. Nested or repeated
custom conditions can therefore produce conservative extra edges that no single runtime would
select; impact analysis favors that visible over-approximation over silently missing a dependent.

RepoRipple does not inspect installed `node_modules`, contact a registry, or run a package manager.
`pnpm-workspace.yaml`, external packages, and workspace entry points that exist only as ignored or
missing build output are not currently resolved. Pathological workspace glob sets that exceed the
resolver's fixed safety budgets fail closed instead of consuming unbounded scan time. The current
limits are 512 effective patterns, 2,048 aggregate path components across unique patterns, 64 KiB
of raw patterns, and 256 KiB after brace expansion; a scan warning identifies this case. Changes
to `tsconfig.json`, `jsconfig.json`, and package manifests are flagged as configuration risk, but
those metadata files are not themselves graph nodes, so a metadata-only change does not yet
enumerate every affected importer.

The core intentionally avoids LLM scoring. Results stay reproducible, private, fast, and usable in CI. Optional AI explanations can be layered over the JSON output without making correctness depend on a model.

## Optional OpenRouter explanation

AI explanation is off by default and is activated only by `--explain`. The deterministic risk level, evidence, report, and `--fail-on` exit status remain authoritative even if OpenRouter is unavailable or returns an invalid response.

First inspect the exact key-free body that would leave your machine:

```bash
reporipple /path/to/repository --base main --explain-preview
```

The preview does not read an API key and does not make a network request. When you are satisfied with the payload, provide the key through the environment and explicitly request an explanation:

```bash
export OPENROUTER_API_KEY="your-key"
reporipple /path/to/repository --base main --explain
```

There is no command-line key option and RepoRipple does not read a key from a file. The integration uses only the Python standard library and applies all of these controls to every request:

- Repository names, paths, source, diffs, scanner-warning text, and user identifiers are not transmitted.
- Files and risk signals become opaque evidence IDs such as `E001`; returned IDs are schema-validated and mapped back to labels locally.
- The response must satisfy a strict JSON Schema, and unknown evidence IDs or extra fields are rejected.
- OpenRouter routing requires zero data retention (`zdr: true`), denies data collection, and selects only providers that support every requested parameter.
- Provider prices are capped at $0.25 per million input tokens and $1 per million output tokens, with a 450-token response limit.
- Requests have a 10-second timeout and retry at most once after an explicit retryable HTTP response; ambiguous network timeouts are not retried.
- Token usage and reported request cost are included in Markdown and JSON output.

The pinned default model is `openai/gpt-6-luna`. Override it with `--explain-model` or
`REPORIPPLE_OPENROUTER_MODEL`; privacy, schema, and price controls remain mandatory. Privacy
filters may reduce provider availability, and the request fails closed when no eligible provider
satisfies them. OpenRouter's ZDR policy prevents eligible providers from retaining prompts and
responses after processing; it does not mean the request stays on your machine. See OpenRouter's
[structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
[ZDR controls](https://openrouter.ai/docs/guides/features/zdr), and
[provider routing controls](https://openrouter.ai/docs/guides/routing/provider-selection).

## CLI reference

```text
reporipple [PATH]
  --base REVISION       compare REVISION...HEAD
  --changed PATH        analyze an explicit path; repeat as needed
  --max-depth N         reverse dependency traversal depth (default: 4)
  --format markdown|json
  --output FILE
  --fail-on medium|high
  --explain             request an optional privacy-filtered OpenRouter explanation
  --explain-preview     show the exact sanitized request without sending it
  --explain-model NAME  use a pinned provider/model slug for either explanation mode

reporipple mcp
  --root PATH            restrict tool access to PATH and its descendants
```

When no base or explicit path is supplied, RepoRipple analyzes staged, unstaged, and untracked files. On a clean checkout it falls back to the latest commit.

`--explain` and `--explain-preview` are mutually exclusive. With JSON output, either flag returns a wrapper containing `deterministic_report` plus the explanation or preview; ordinary JSON output is unchanged.

## Supported analysis

| Capability | Status |
| --- | --- |
| Python absolute and relative imports | Supported |
| JavaScript/TypeScript relative imports | Supported |
| JavaScript/TypeScript `paths` and `baseUrl` aliases | Supported |
| npm/Yarn `package.json` workspace package imports | Supported |
| Deleted and renamed source files | Supported |
| Reverse-dependency paths | Supported |
| Test-file recommendations | Supported |
| Markdown and JSON reports | Supported |
| Risk-based CI exit code | Supported |
| MCP tools for coding agents | Supported |
| Privacy-filtered OpenRouter explanations | Optional |
| `pnpm-workspace.yaml` and external package resolution | Not supported |
| Go, Rust, and Java imports | Planned |
| GitHub pull-request reports and comments | Supported |

## Development

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest
uv build
```

## Privacy and security

RepoRipple's deterministic analysis runs locally and does not transmit repository contents. It
invokes Git using argument arrays rather than a shell and reads only supported, non-symlinked
source files outside common generated and dependency directories. The MCP server constrains every
repository request to its configured `--root` and exposes read-only tools only. Network access
occurs only when `--explain` is present; `--explain-preview` remains fully local so the outbound
body can be audited first.

## License

MIT
