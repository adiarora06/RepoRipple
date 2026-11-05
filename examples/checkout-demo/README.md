# Checkout impact-map demo

This intentionally small service gives RepoRipple a deterministic dependency chain to visualize.
Changing `src/checkout_demo/billing/store.py` reaches the billing service, checkout API, web route,
application entry point, analytics adapter, and matching tests.

From the RepoRipple source checkout, run:

```bash
./scripts/demo-impact-map.sh
```

The script writes Markdown, JSON, and self-contained HTML reports to the operating system's
temporary directory and opens the visual map in the default browser. Set `CI=true` to generate the
bundle without opening a browser. The script runs RepoRipple from local source with Python and does
not resolve or download packages.
