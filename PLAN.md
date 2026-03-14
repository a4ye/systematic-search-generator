# Plan: Forward/Backward Citation Searching via OpenAlex

## Overview

Add a `--citations` flag to `generate_query.py` that performs forward/backward citation searching on the seed papers via the OpenAlex API, then unions the resulting PMIDs with the Boolean query results before evaluation.

## New Files

### 1. `src/citation/openalex.py` — OpenAlex API client

- `OpenAlexClient` class with a `requests.Session`
- Polite pool header (`mailto:` email from config) for better rate limits
- `get_citations(pmid) -> CitationResult` method:
  - Calls `GET https://api.openalex.org/works/pmid:{pmid}` to get the work and its `referenced_works` (backward citations as OpenAlex IDs)
  - Resolves backward OpenAlex IDs to PMIDs in batches: `GET https://api.openalex.org/works?filter=openalex:{id1}|{id2}|...&select=ids&per_page=200`
  - Fetches forward citations (papers citing this work): `GET https://api.openalex.org/works?filter=cites:{openalex_id}&select=ids&per_page=200` with pagination
  - Returns `CitationResult(forward_pmids=set[str], backward_pmids=set[str])`
- Rate limiting: short sleep between requests
- Error handling: skip papers not found in OpenAlex

### 2. `src/cache/citation_cache.py` — Citation cache

- Follows the existing cache pattern (JSON file, load-on-init)
- File: `citation_cache.json` in `.cache/`
- Key: PMID string
- Value: `{"forward_pmids": [...], "backward_pmids": [...], "cached_at": timestamp}`
- No TTL (citations change slowly, aggressive caching is fine)

### 3. `src/citation/__init__.py` — empty init

## Modified Files

### `generate_query.py`

1. Add `--citations` flag (action=store_true, default False)
2. After Boolean query PMIDs are obtained (`llm_results`), if `--citations` is enabled:
   - Use the same seed papers already loaded for the prompt (requires `--seeds N` to be set)
   - For each seed paper with a PMID, call `OpenAlexClient.get_citations()`
   - Collect all citation PMIDs (forward ∪ backward)
   - Build an augmented `PubMedSearchResults` by adding citation PMIDs to the existing `pmid_map`
   - Update `result_count` to reflect the union
   - Log stats: how many citation PMIDs were found, how many were new
3. The augmented results are then evaluated as usual by `calculate_metrics_with_pubmed_check`
4. Results file metadata includes `--citations` status and citation count

## Flow

```
Existing:   Protocol PDF → LLM → Boolean Query → PubMed → PMIDs → Evaluate

With citations:
  Protocol PDF → LLM → Boolean Query → PubMed → PMIDs ─┐
  Seed papers → OpenAlex → Citation PMIDs ───────────────┤
                                                         ▼
                                                   Union PMIDs → Evaluate
```

## Key Decisions

- Uses the SAME seed papers selected by `--seeds N` for both prompting and citations (no cherry-picking)
- 1-hop only (direct citations of seed papers, not citations-of-citations)
- Citation PMIDs are added to pmid_map only (no DOI data from OpenAlex needed for matching)
- OpenAlex API requires a free API key as of Feb 2026; will use email as polite pool identifier
- Forward citation pagination capped at a reasonable limit (e.g., 2000 per seed paper) to avoid runaway requests
