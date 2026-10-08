# Changelog

All notable changes to RepoRipple are documented here.

## Unreleased

### Added

- JavaScript and TypeScript import resolution through the nearest `tsconfig.json` or
  `jsconfig.json` `paths` mappings and `baseUrl`.
- Local package-name and export resolution for npm/Yarn workspaces declared in the root
  `package.json`.

### Changed

- JS/TS dependency graphs can now include aliases and cross-workspace imports that were previously
  invisible. Reports may therefore contain more edges, wider blast radii, and higher deterministic
  risk levels for the same change.

## 0.3.0 - 2026-09-30

### Added

- Structured Git change discovery with statuses, rename origins, and historical source content.
- End-to-end impact tracing for deleted files and both sides of a rename in the CLI and MCP server.
- Deterministic warnings for ambiguous Python modules and oversized source files.

### Changed

- Repository discovery now prunes built-in and `.gitignore`-excluded directories before walking
  them and skips parsing source files larger than 1 MB.
- Sensitive-area scoring recognizes exact concepts in snake case, kebab case, camel case, and
  plural filenames, including sensitive production files reached by a change.
- Git path parsing now uses NUL-delimited output so unusual filenames remain intact.

### Security

- Base revisions are validated and resolved to commit IDs before use, preventing option-like
  input from reaching `git diff`.

## 0.2.0 - 2026-09-27

### Added

- A reusable GitHub Action that generates Markdown and JSON impact reports.
- A fork-safe pull-request workflow with job summaries, artifacts, and an idempotent comment.
- A local, read-only MCP server for Codex, OpenCode, Cursor, Claude, and VS Code.
- `forecast_change` and `analyze_worktree` MCP tools with enforced workspace boundaries.
- Explicit `--explain` and `--explain-preview` OpenRouter modes with anonymized evidence.
- Tokenless PyPI trusted publishing and MCP Registry release automation.

### Security

- MCP repository access is constrained to an operator-selected root.
- Symlinked source files are excluded from scanning.
- OpenRouter explanations require explicit activation and never receive repository paths, diffs,
  source code, warning text, or user identity.
- GitHub Action analysis runs without write permission; only same-repository pull requests can
  reach the separate comment job.

## 0.1.0 - 2026-09-25

- Initial local-first Python, JavaScript, and TypeScript change-impact analyzer.
- Reverse-dependency traversal, test recommendations, risk signals, Markdown/JSON reports, and
  CI thresholds.
