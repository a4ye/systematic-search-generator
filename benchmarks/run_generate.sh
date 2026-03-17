#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 1 ]]; then
  echo "Usage: $0 <study_id...>" >&2
  exit 1
fi

uv run python -m src.generate_query "$@" \
  -n 5 \
  --seeds 23406311,16919107,31826369,31309323,24472587 \
  --seed-fields tm \
  --citations \
  --citation-depth 1 \
  --two-pass \
  --two-pass-max 10 \
  --similar 100 \
  --mesh-entry-terms \
  --mesh-entry-max 8 \
  --tfidf \
  --tfidf-top 8 \
  --tfidf-max-results 30000 \
  --block-drop \
  --similar-augment 100 \
  --similar-augment-sample 20

notify-send done