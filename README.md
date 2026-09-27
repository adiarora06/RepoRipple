# RepoRipple

**Know what a code change can break before you merge it.**

RepoRipple is a local-first change-impact analyzer for engineers and coding agents. It builds a lightweight dependency graph from a repository, reads the current Git diff, traces reverse dependencies, recommends relevant tests, and emits a review-ready Markdown or JSON report.

The deterministic analyzer requires no API key, hosted service, source upload, or framework integration. An optional, explicitly requested OpenRouter explanation can turn its anonymized evidence into a short narrative without changing the underlying analysis.

## Why RepoRipple?

Code graphs explain how a repository is connected. RepoRipple applies that graph to the change in front of you:

- Which files depend on the code I changed?
- How far does the blast radius travel?
- Which tests are most relevant?
- Did I touch authentication, payments, deployment, or another sensitive area?
- Should this pull request be blocked for additional review?
- What structured context should I give a coding agent?

## Quick start

```bash
git clone https://github.com/adiarora06/RepoRipple.git
cd RepoRipple
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Analyze staged, unstaged, and untracked changes in another repository.
reporipple /path/to/repository

# Compare a feature branch with main.
reporipple /path/to/repository --base main

# Generate machine-readable context for an agent or automation.
reporipple /path/to/repository --base main --format json --output impact.json

# Fail CI when a change reaches high risk.
reporipple . --base origin/main --fail-on high

# Audit the exact anonymized OpenRouter request without sending it.
reporipple . --base origin/main --explain-preview
```

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
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: reporipple
        uses: adiarora06/RepoRipple@00d64bd0763d812e682d90756b88fd82bb7157e7
        with:
          base: ${{ github.event.pull_request.base.sha }}
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: reporipple-impact
          path: |
            ${{ steps.reporipple.outputs.markdown-report }}
            ${{ steps.reporipple.outputs.json-report }}
```

The Action accepts `path`, `base`, `max-depth`, `fail-on`, and `reports-directory`. It outputs
`markdown-report`, `json-report`, and `risk-level`. For reproducible builds, pin RepoRipple to a
release commit SHA and use `fetch-depth: 0` so the requested base revision is available.

This repository's own [pull-request workflow](.github/workflows/reporipple.yml) demonstrates a
fork-safe commenting design. Analysis runs with read-only contents access. A separate job updates
one stable RepoRipple comment only for branches in the same repository; fork pull requests keep
their report in the job summary and downloadable artifact without receiving a write-capable token.

## Coding-agent tools (MCP)

RepoRipple can expose the same deterministic analysis to Codex, OpenCode, Cursor,
Claude Code, and VS Code over a local, read-only MCP server. From a source checkout:

```bash
uv run reporipple mcp --root /path/to/allowed/workspace
```

After the package is published to PyPI, agent configurations can launch it without a
clone:

```bash
uvx reporipple mcp --root /path/to/allowed/workspace
```

The server provides `forecast_change` for proposed edits and `analyze_worktree` for
actual Git changes. See the
[MCP setup guide](https://github.com/adiarora06/RepoRipple/blob/main/docs/mcp.md) for
client-specific commands and configuration.

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
2. Extracts Python imports with the standard-library AST and relative JS/TS imports with a focused parser.
3. Builds forward and reverse dependency relationships.
4. Gets changed files from an explicit base revision or the local worktree.
5. Traverses dependents to a configurable depth.
6. Adds test recommendations, documentation reminders, and deterministic risk signals.

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
- Provider prices are capped at $1 per million input tokens and $4 per million output tokens, with a 450-token response limit.
- Requests have a 10-second timeout and retry at most once for a transient failure.
- Token usage and reported request cost are included in Markdown and JSON output.

The default model is `openai/gpt-5-mini`. Privacy filters may reduce provider availability, and the request fails closed when no eligible provider satisfies the structured-output, privacy, or price requirements. OpenRouter's ZDR policy prevents eligible providers from retaining prompts and responses after processing; it does not mean the request stays on your machine. See OpenRouter's [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [ZDR controls](https://openrouter.ai/docs/guides/get-started/sovereign-ai), and [provider price ceilings](https://openrouter.ai/blog/tutorials/how-to-get-the-lowest-cost-llm-inference-on-openrouter/) documentation.

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
| Reverse-dependency paths | Supported |
| Test-file recommendations | Supported |
| Markdown and JSON reports | Supported |
| Risk-based CI exit code | Supported |
| MCP tools for coding agents | Supported |
| Privacy-filtered OpenRouter explanations | Optional |
| Monorepo package aliases | Planned |
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
