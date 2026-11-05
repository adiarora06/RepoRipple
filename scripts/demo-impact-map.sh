#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
demo_repository="$repository_root/examples/checkout-demo"
output="${REPORIPPLE_DEMO_OUTPUT:-${TMPDIR:-/tmp}/reporipple-impact-demo}"
command=(uv run --no-project --with-editable "$repository_root" reporipple "$demo_repository" \
  --changed src/checkout_demo/billing/store.py \
  --max-depth 4 \
  --format all \
  --output "$output")

if [[ "${CI:-false}" == "true" ]]; then
  "${command[@]}"
else
  "${command[@]}" --open
fi

echo "RepoRipple review bundle: $output"
echo "RepoRipple impact map: $output/impact.html"
