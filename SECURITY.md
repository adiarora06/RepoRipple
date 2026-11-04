# Security Policy

## Report a vulnerability privately

Use [GitHub private vulnerability reporting][report] for suspected vulnerabilities in RepoRipple.
Do not open a public issue or pull request containing exploit details, credentials, private source,
or other sensitive evidence.

[report]: https://github.com/adiarora06/RepoRipple/security/advisories/new

Include, when available:

- the affected RepoRipple version or commit;
- the affected surface (CLI, GitHub Action, MCP server, or optional OpenRouter explanation);
- the security impact and the smallest safe reproduction;
- relevant platform and Python-version details; and
- any known mitigation, with secrets and private repository content removed.

Confirmed fixes are coordinated through the private advisory and its temporary private fork when
appropriate. Fix details stay private until the patch, public release, and release guidance can be
published together. After disclosure, the maintained fix lives on `main`; RepoRipple does not
currently publish separately maintained release branches, so users should update to the latest
release when a fix is published.

## Security-sensitive areas

Reports are especially useful for repository-root or symlink escapes, unsafe Git argument handling,
GitHub Action token or fork-permission exposure, MCP root-boundary bypasses, unintended data in an
OpenRouter request, explanation cost-control bypasses, and resource-exhaustion paths that evade the
documented analysis budgets.

Please coordinate public disclosure through the private advisory until a fix and release guidance
are available.

