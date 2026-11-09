# Changelog

All notable changes to RepoRipple are documented here.

## Unreleased

## 0.6.0 - 2026-11-08

### Added

- A self-contained visual impact map via `--format html`, with deterministic SVG dependency paths,
  accessible review details, restrictive content security, and an explicit `--open` workflow.
- A one-scan `--format all` review bundle that stages and publishes Markdown, JSON, and HTML
  together without replacing unrelated directory contents.
- The public GitHub Action now emits `impact.html` and exposes it through the `html-report` output.
- A deterministic checkout-service fixture and one-command demo for recording or evaluating the
  impact-map workflow without an API key or network service.
- Contributor and security documentation, issue forms, and a pull-request template for a clearer
  open-source contribution path.

### Changed

- Visual node selection now reserves room for dependents and suggested tests when a change exceeds
  the 80-node canvas limit, and filename-matched tests remain visible without a dependency edge.
- `--open` treats browser-launch failures as non-fatal after the report is written, while CLI help
  distinguishes single-report files from all-format bundle directories.

### Security

- HTML reports escape repository-controlled labels, load no external resources, and enforce a
  restrictive content security policy.
- Review bundles are serialized, staged, and replaced together; symlinked destinations and
  directories containing unrelated files are rejected instead of being overwritten.
- Tagged release distributions now receive GitHub build-provenance attestations before trusted
  publication to PyPI.

## 0.5.1 - 2026-11-03

### Fixed

- The public GitHub Action no longer requires consumer repositories to contain a Python dependency
  manifest, so JavaScript-only projects can generate impact reports without compatibility files.

### Security

- Updated the immutable `actions/setup-python` and PyPI publishing action revisions used by the
  public Action, CI, and release workflow.

## 0.5.0 - 2026-10-29

### Added

- A conventional `reporipple --version` command for installation diagnostics and support reports.
- Configuration-aware impact tracing from `tsconfig.json`, `jsconfig.json`, their local `extends`
  chains, and `package.json` manifests to governed JS/TS files and workspace importers.

### Changed

- GitHub Actions are pinned to immutable commit SHAs, release jobs no longer cache mutable Python
  packages, and concurrent runs for the same release tag are serialized.
- Dependabot now groups GitHub Actions updates and waits seven days before proposing routine version
  updates, reducing automated pull-request noise without delaying security updates.
- Metadata-only changes now continue through ordinary reverse imports, while source-file inventory
  and the public report and MCP response shapes remain unchanged.
- Deleted project configs and root manifests remain historical impact targets without controlling
  current alias, inherited `baseUrl`, or workspace resolution; extensionless `extends` prefers a
  live fallback, deleted config chains are not traversed, package history stops at the nearest live
  boundary, and unmatched external imports no longer depend on the root workspace manifest.
- Configuration traversal and metadata storage now have explicit deterministic work and memory
  budgets, including 64 loaded config nodes per top-level resolution and 100,000 repository-wide
  source-to-metadata relationships. Loaded live config paths take priority over historical paths
  in the per-source metadata cap.
- The README overview is more concise and no longer embeds a large hero image.

## 0.4.0 - 2026-10-08

### Added

- JavaScript and TypeScript import resolution through the nearest `tsconfig.json` or
  `jsconfig.json` `paths` mappings, `baseUrl`, local `extends`, and TypeScript-compatible module
  extension substitution.
- Local package-name and export resolution for npm/Yarn workspaces declared in the root
  `package.json`, including bounded recursive globs, brace alternatives and ranges, npm-compatible
  exclusions, and conservative syntax-aware conditional exports.

### Changed

- JS/TS dependency graphs can now include aliases and cross-workspace imports that were previously
  invisible. Reports may therefore contain more edges, wider blast radii, and higher deterministic
  risk levels for the same change.
- Repository source and resolver metadata reads now reject symbolic-link traversal, including
  link swaps during reads on platforms with descriptor-relative file access.

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
