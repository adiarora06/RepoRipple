# Use RepoRipple with coding agents

RepoRipple's MCP server gives coding agents two deterministic, read-only tools:

- `forecast_change`: accepts repository-relative paths you plan to edit and predicts
  their reverse-dependency impact.
- `analyze_worktree`: reads the current Git changes, or compares `HEAD` with a base
  revision, and returns the actual impact report.

Both tools return typed data containing the changed and impacted files, dependency
paths, suggested tests, documentation reminders, risk level, risk reasons, and graph
size. No model performs the analysis.

## Run from a source checkout

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone RepoRipple,
and start the stdio server:

```bash
git clone https://github.com/adiarora06/RepoRipple.git
cd RepoRipple
uv run reporipple mcp --root /absolute/path/to/your/workspace
```

An MCP server waits for a client on standard input, so an idle command with no terminal
output is expected. Stop it with `Ctrl-C` when testing manually.

## Run the published package with `uvx`

RepoRipple releases include MCP support on PyPI:

```bash
uvx reporipple mcp --root /absolute/path/to/your/workspace
```

`uvx` creates and caches an isolated environment, so users do not need to clone the
repository or manage a virtual environment.

## Codex

Run this from the project you want RepoRipple to inspect. The shell expands `$PWD` to
an absolute allowed root before Codex saves the configuration:

```bash
codex mcp add reporipple -- \
  uvx reporipple mcp --root "$PWD"
codex mcp list
```

Codex CLI and the Codex IDE extension share this configuration. The equivalent
`~/.codex/config.toml` entry is:

```toml
[mcp_servers.reporipple]
command = "uvx"
args = [
  "reporipple", "mcp",
  "--root", "/absolute/path/to/your/workspace"
]
```

## OpenCode v2

Add RepoRipple to the current project:

```bash
opencode mcp add reporipple -- \
  uvx reporipple mcp --root .
opencode mcp list
```

Or add it manually to `opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "reporipple": {
        "type": "local",
        "command": [
          "uvx", "reporipple", "mcp", "--root", "."
        ],
        "cwd": "."
      }
    }
  }
}
```

## Cursor

Create `.cursor/mcp.json` for one project, or `~/.cursor/mcp.json` for every project.
Replace the root with an absolute path:

```json
{
  "mcpServers": {
    "reporipple": {
      "command": "uvx",
      "args": [
        "reporipple", "mcp",
        "--root", "/absolute/path/to/your/workspace"
      ]
    }
  }
}
```

Restart Cursor, then confirm that `forecast_change` and `analyze_worktree` appear under
the RepoRipple server's available tools.

## Claude Code

Add RepoRipple at project scope so Claude Code writes a shareable `.mcp.json` entry:

```bash
claude mcp add --scope project --transport stdio reporipple -- \
  uvx reporipple mcp --root .
claude mcp list
```

Use `--scope user` instead to make the server available in all of your local projects.

## VS Code and GitHub Copilot

Create `.vscode/mcp.json` in the workspace:

```json
{
  "servers": {
    "reporipple": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "reporipple", "mcp",
        "--root", "${workspaceFolder}"
      ]
    }
  }
}
```

Run **MCP: List Servers**, start RepoRipple, and enable its tools in Copilot Chat's
Agent mode. Workspace MCP configuration executes local code, so review the command
before trusting a repository.

## Example prompts

```text
Use RepoRipple to forecast the impact of changing src/billing/store.py and
src/billing/models.py. Explain the dependency paths and tests I should run.
```

```text
Use RepoRipple to analyze my current worktree. Focus the review on high-risk paths
and missing tests.
```

For a server whose allowed root contains several repositories, pass the tool's
`repository` argument as a path relative to that root.

## Access boundary and privacy

- `--root` defaults to the server process's current directory.
- Requested repositories must resolve to that directory or one of its descendants.
- Proposed changed files must stay inside the selected repository.
- Symlinked source files are not scanned.
- Tools read repository state but never edit files, execute project code, or access the
  network.
- Protocol messages use stdout; logs and startup errors use stderr so they cannot
  corrupt the MCP stream.

The root boundary is enforced by RepoRipple even when an MCP client ignores tool
annotations. Give each agent the narrowest useful root.

Client configuration references: [Codex MCP](https://developers.openai.com/codex/extend/mcp),
[OpenCode MCP](https://opencode.ai/v2/docs/mcp-servers),
[Cursor MCP](https://docs.cursor.com/context/model-context-protocol),
[Claude Code MCP](https://code.claude.com/docs/en/mcp), and
[VS Code MCP](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

## Troubleshooting

- **`MCP runtime is unavailable`**: reinstall RepoRipple so its runtime dependencies
  are restored.
- **Server starts but prints nothing**: this is normal for stdio; inspect it through an
  MCP client.
- **Repository is outside the allowed root**: restart the server with a suitable
  absolute `--root`, or request a repository beneath the current root.
- **`uvx` cannot find RepoRipple**: confirm that PyPI is reachable, then retry with
  `uvx --refresh reporipple mcp --root /absolute/path/to/your/workspace` or use the
  source-checkout command above.
