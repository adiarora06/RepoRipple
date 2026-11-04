## Summary

<!-- What changes for RepoRipple users, and why? -->

## Risk-sensitive boundaries

<!-- Note any impact on filesystem/Git handling, Action permissions, MCP root constraints, OpenRouter data, or analysis budgets. Write "None" when not applicable. -->

## Verification

<!-- List the focused tests and local commands you ran. -->

## Checklist

- [ ] I kept the deterministic report authoritative across the CLI, Action, and MCP surfaces.
- [ ] I added or updated focused tests for behavior changes.
- [ ] I ran `.venv/bin/ruff check .` and `.venv/bin/pytest`.
- [ ] I updated user-facing documentation and `CHANGELOG.md` when public behavior changed.
- [ ] I did not include secrets, private source, local paths, or generated build artifacts.

