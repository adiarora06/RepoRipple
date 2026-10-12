# RepoRipple architecture

RepoRipple keeps one deterministic analysis engine at the center and exposes it through several
small adapters. The optional model layer explains evidence; it never creates or changes that
evidence.

```mermaid
flowchart LR
    Source[Repository source files] --> Resolve[Deterministic import resolution]
    Config[tsconfig / jsconfig / package.json] --> Resolve
    Source --> Govern[Metadata governance relationships]
    Config --> Govern
    Resolve --> Core[Deterministic impact engine]
    Govern --> Core
    Diff[Git diff or proposed files] --> Core
    Core --> Report[Markdown and JSON]
    Report --> CLI[Local CLI]
    Report --> Action[GitHub Action]
    Report --> MCP[Read-only MCP tools]
    Report --> Sanitize[Evidence anonymizer]
    Sanitize -->|explicit --explain only| Router[OpenRouter explanation]
    Router --> Narrative[Optional narrative]
    Report --> Final[Authoritative result]
    Narrative --> Final
```

## Responsibility boundaries

| Layer | Responsibility | Network access |
| --- | --- | --- |
| Core scanner and analyzer | Build the import graph, trace reverse dependencies, suggest tests, and score deterministic risk | Never |
| CLI | Select changes and render reports | Never, unless `--explain` is explicitly present |
| GitHub Action | Run the CLI in CI and publish summaries, artifacts, and eligible PR comments | GitHub only |
| MCP server | Give coding agents typed, read-only access within an allowed workspace root | Never |
| OpenRouter adapter | Explain an anonymized evidence bundle | Explicit opt-in only |

## JavaScript and TypeScript resolution

RepoRipple resolves each JavaScript or TypeScript import against repository source files in this
order:

1. Relative paths.
2. `paths` mappings from the nearest applicable `tsconfig.json` or `jsconfig.json`, using the most
   specific matching pattern and its declared target order.
3. That configuration's `baseUrl`.
4. A uniquely named npm/Yarn workspace declared by the root `package.json`.

Workspace package resolution observes declared export boundaries and local entry points. A bare
specifier that is not one of those workspaces remains external and does not become a graph edge.
Workspace selection supports recursive globs, bounded brace alternatives and ranges, and
exclusions. Export conditions are syntax-aware: `.mts`/`.mjs` use an import profile,
`.cts`/`.cjs` use a require profile, and ambiguous TypeScript/JavaScript files inspect both.
Applicable custom conditions declared before a syntax or `default` fallback are included
conservatively, preserving browser-, platform-, and source-specific dependency edges without
assuming one deployment environment.

The resolver intentionally does not correlate repeated custom-condition names across nested
objects. That can retain extra edges that no single runtime condition set would choose, but avoids
false-negative impact reports when the deployment condition set is unknown.

### Configuration-aware impact

The scanner keeps metadata relationships separate from ordinary import edges so the public source
inventory and report shape remain stable. Reverse traversal nevertheless treats both kinds of
relationship uniformly:

- A JS/TS file depends on its nearest `tsconfig.json` or `jsconfig.json` and every successfully
  located local configuration in that file's `extends` chain. Malformed configs still retain the
  relationship so fixing them produces a useful blast radius.
- A JS/TS file depends on its nearest `package.json`, which governs its package boundary and module
  interpretation.
- A bare workspace import also depends on the root workspace manifest and the resolved workspace
  package manifest, because either can change the binding or public entry point.

Metadata paths do not need to be source nodes to seed impact analysis. They are reverse-dependency
targets, so a metadata-only diff reaches directly governed files at distance one and then follows
normal importer edges up to the configured depth. The source-file count remains a count of parsed
repository sources; the edge count includes these metadata relationships.

RepoRipple does not inspect `node_modules`, execute a package manager, or parse
`pnpm-workspace.yaml`. Consequently, configurations whose only targets are ignored or unavailable
build artifacts can remain unresolved. Pathological workspace glob sets that exceed fixed matching
budgets fail closed with a warning: 512 effective patterns, 2,048 aggregate path components across
unique patterns, 64 KiB of raw patterns, and 256 KiB after brace expansion. Project-config
traversal is separately capped at 16 levels and 64 metadata dependencies per source, including
when parsed configs are reused from cache. Resolver metadata changes receive configuration-risk
and documentation signals and now enumerate governed sources and currently identifiable importers.
Historical overlays preserve deleted and renamed metadata. An in-place manifest edit that
completely removes a workspace's old package name cannot identify external importers of that
former name without constructing a second historical graph; sources owned by the edited package
remain visible.

## Relationship to Graphify

RepoRipple is not an official Graphify extension and does not depend on Graphify. Graphify builds a
broad, persistent knowledge graph for repository exploration; RepoRipple is a focused, Git-native
gate for one proposed or actual change. The products overlap in dependency analysis but serve
different default workflows.

A future compatibility adapter could consume `graphify-out/graph.json` for richer language and
cross-system coverage while retaining RepoRipple's reports, policies, and CI behavior. Until that
adapter exists, describe RepoRipple as standalone—not as endorsed by or built into Graphify.

## Trust model

- Repository files are parsed, never executed.
- TypeScript, JavaScript, and workspace configuration is treated as data. RepoRipple does not load
  configuration modules, run package scripts, or invoke npm, Yarn, or another package manager.
- Alias and workspace targets must normalize inside the repository and resolve to a discovered
  source file before they can become dependency edges.
- Git is invoked with argument arrays rather than a shell; user-provided base revisions are
  resolved to commit IDs before they reach diff operations.
- Deleted and renamed source and resolver-metadata files are read from the comparison revision and
  overlaid in memory so their surviving reverse dependencies remain visible without changing the
  worktree.
- MCP tools reject repositories and changed paths outside the configured root.
- The GitHub workflow never runs untrusted pull-request code with a write-capable token.
- The optional explanation request contains opaque evidence IDs and generic metadata, not code or
  paths. The local process resolves cited evidence IDs back to human-readable labels.
