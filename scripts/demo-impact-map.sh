#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
demo_repository="$repository_root/examples/checkout-demo"
output="${REPORIPPLE_DEMO_OUTPUT:-${TMPDIR:-/tmp}/reporipple-impact-demo}"
python_executable="${PYTHON:-python3}"
source_path="$repository_root/src${PYTHONPATH:+:$PYTHONPATH}"
command=("$python_executable" -m reporipple.cli "$demo_repository" \
  --changed src/checkout_demo/billing/store.py \
  --max-depth 4 \
  --format all \
  --output "$output")

if [[ "${CI:-false}" == "true" ]]; then
  PYTHONPATH="$source_path" "${command[@]}"
else
  PYTHONPATH="$source_path" "${command[@]}" --open
fi

echo "RepoRipple review bundle: $output"
echo "RepoRipple impact map: $output/impact.html"
