#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 1 ]]; then
  echo "Usage: $0 <study_id...>" >&2
  exit 1
fi

uv run python generate_query.py "$@" \
  -n 5 \
  --seeds 5 \
  --save-prompt \
  --seed-fields tm \
  --show-missed \
  --citations \
  --citation-depth 1 \
  --two-pass \
  --two-pass-max 5 \
  --similar 100 \
  --mesh-entry-terms \
  --mesh-entry-max 6
