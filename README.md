# RepoRipple

**Know what a code change can break before you merge it.**

RepoRipple is a local-first change-impact analyzer for engineers and coding agents. It builds a lightweight dependency graph from a repository, reads the current Git diff, traces reverse dependencies, recommends relevant tests, and emits a review-ready Markdown or JSON report.

No API key, hosted service, source upload, or framework integration is required.

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

## CLI reference

```text
reporipple [PATH]
  --base REVISION       compare REVISION...HEAD
  --changed PATH        analyze an explicit path; repeat as needed
  --max-depth N         reverse dependency traversal depth (default: 4)
  --format markdown|json
  --output FILE
  --fail-on medium|high
```

When no base or explicit path is supplied, RepoRipple analyzes staged, unstaged, and untracked files. On a clean checkout it falls back to the latest commit.

## Supported analysis

| Capability | Status |
| --- | --- |
| Python absolute and relative imports | Supported |
| JavaScript/TypeScript relative imports | Supported |
| Reverse-dependency paths | Supported |
| Test-file recommendations | Supported |
| Markdown and JSON reports | Supported |
| Risk-based CI exit code | Supported |
| Monorepo package aliases | Planned |
| Go, Rust, and Java imports | Planned |
| GitHub pull-request reports and comments | Supported |

## Development

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest
```

## Privacy and security

RepoRipple runs locally and does not transmit repository contents. It invokes Git using argument arrays rather than a shell and reads only supported source files outside common generated and dependency directories.

## License

MIT
