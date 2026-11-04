# Contributing to RepoRipple

RepoRipple turns repository structure and Git changes into a deterministic change-impact report.
Contributions should preserve that predictable core across the CLI, GitHub Action, MCP server,
and optional explanation layer.

## Choose the right channel

- Use the bug template for reproducible incorrect behavior.
- Use the feature template to propose a new analysis rule, language, or product-surface change.
- Report suspected vulnerabilities through [GitHub private vulnerability reporting][report]. Do
  not put exploit details in a public issue or pull request.

[report]: https://github.com/adiarora06/RepoRipple/security/advisories/new

## Set up the project

RepoRipple supports Python 3.11 and newer. The commands below match the documented local workflow;
CI runs the lint and test steps on Python 3.11, 3.12, and 3.13.

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest
uv build
```

Run the CLI from the editable environment with `.venv/bin/reporipple`. To exercise the MCP entry
point, use `.venv/bin/reporipple mcp --root /path/to/allowed/workspace`.

## Preserve RepoRipple's trust boundaries

- Deterministic evidence, risk, and `--fail-on` behavior remain authoritative. An optional LLM
  explanation may summarize evidence but must not change the result.
- Repository files are parsed as data, not executed. Keep Git invocations shell-free and retain
  path, symlink, file-size, traversal, and resolver-work limits.
- MCP tools stay read-only and reject repositories or changed paths outside their configured root.
- Explanation requests stay opt-in and must not transmit source, paths, diffs, warnings, user
  identity, or secrets. Preserve the existing schema, privacy, and price controls.
- GitHub Actions must remain least-privilege and safe for pull requests from forks. Never expose a
  write-capable token to untrusted pull-request code.

The [architecture guide](docs/architecture.md) describes these boundaries in more detail.

## Test the affected surface

Add a focused regression test for behavior changes, then run the complete lint and test commands
above. Useful starting points are:

| Area | Tests |
| --- | --- |
| Core analysis and reports | `test_analysis.py`, `test_report.py`, `test_scanner.py` |
| JavaScript/TypeScript resolution | `test_javascript_resolution.py`, `test_workspace_resolution.py`, `test_configuration_impact.py` |
| Filesystem, Git, and MCP boundaries | `test_filesystem.py`, `test_git.py`, `test_mcp_server.py` |
| CLI and optional explanation | `test_cli.py`, `test_explain.py` |
| Action and release contracts | `test_action_contract.py`, `test_release_contract.py` |

Tests live under [`tests/`](tests/). Prefer a small fixture that proves the new edge case over a
large example repository.

## Open a pull request

Keep each pull request focused and explain the user-visible effect, risk-sensitive boundaries it
touches, and verification performed. Update the README, architecture or MCP guide, and changelog
when public behavior changes. Maintainers handle release version bumps and tags separately.

