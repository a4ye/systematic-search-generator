#!/bin/bash

uv run python -m src.generate_query --studies 34,43,76,77,88,92,101,110,118,131,143 \
  -n 5 \
  --seeds 5 \
  --save-prompt \
  --seed-fields tm \
  --show-missed \
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
