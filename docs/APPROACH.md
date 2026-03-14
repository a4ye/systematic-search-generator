# How the Pipeline Works

This document describes the end-to-end approach used by `generate_query.py` to automatically generate and evaluate PubMed search strategies for systematic reviews.

## Overview

The pipeline takes a PROSPERO protocol PDF and produces a PubMed Boolean query, then evaluates it against a list of known included studies. Several augmentation layers can be stacked on top of the base query to improve recall without relying on ground truth (no information leakage).

```
PROSPERO PDF
    │
    ▼
[1] Extract plan (LLM)
    │
    ▼
[2] Generate Boolean query (LLM, optionally N times)
    │  ├── seed papers injected into prompt
    │  └── queries OR-merged if N > 1
    │
    ▼
[3] MeSH entry-term expansion (offline, no LLM)
    │
    ▼
[4] Execute on PubMed → base result set
    │
    ▼
[5] Two-pass supplement (LLM, iterative)
    │
    ▼
[6] TF-IDF term mining (no LLM)
    │
    ▼
[7] Citation searching (OpenAlex API)
    │
    ▼
[8] PubMed Similar Articles (Entrez API)
    │
    ▼
[9] Evaluate against included studies
```

All augmentation steps (5-8) union their results into a single combined result set. Each step uses only the seed papers (known beforehand) — never the full included studies list — so there is no information leakage.

## Step-by-step

### 1. Plan extraction (`--extract`)

The PROSPERO protocol PDF is sent to the LLM (GPT-5.3) with an extraction prompt that pulls out the structured review plan: title, condition, PICO elements (excluding outcomes). The LLM is instructed to copy text verbatim from the document.

### 2. Query generation (`-n`, `--seeds`, `--seed-fields`, `--double-prompt`)

The extracted plan is combined with a query generation prompt containing 11 instructions for building a PubMed Boolean query optimized for sensitivity. Key instructions include:

- Identify 2-3 core concept blocks (condition, phenomenon, population modifier)
- Combine MeSH terms and free-text synonyms with OR within blocks
- Avoid overly generic terms that explode result counts
- Use vocabulary from the literature, not protocol wording

**Seed papers** (`--seeds N`): N randomly selected known relevant papers from the `seed_papers/` cache are appended to the prompt. The LLM is told to use their MeSH terms, keywords, and vocabulary to inform term selection. Fields included are controlled by `--seed-fields` (t=title, a=abstract, m=MeSH, k=keywords).

**Query ensembling** (`-n N`): The query generation is run N times in parallel. Each run produces a slightly different Boolean query due to LLM sampling. The unique queries are OR-merged into a single union query before execution. This increases vocabulary coverage since different runs emphasize different synonyms.

### 3. MeSH entry-term expansion (`--mesh-entry-terms`)

After the LLM generates the query, MeSH headings in the query (e.g., `"Colorectal Neoplasms"[Mesh]`) are detected and expanded with entry-term synonyms from the MeSH database. For example, `"Colorectal Neoplasms"[Mesh]` might get `"Colorectal Tumor"[tiab]` and `"Colorectal Cancer"[tiab]` appended as OR terms.

This is a deterministic, offline step — it uses the local MeSH XML database with no API calls. It catches free-text variants that the LLM may have missed.

### 4. PubMed execution

The final query is executed against PubMed via the NCBI Entrez API. Results are cached locally (keyed by exact query string) so repeated runs with the same query skip the API entirely.

### 5. Two-pass supplement (`--two-pass`, `--two-pass-max`)

After the initial query is executed, the pipeline checks which seed papers were captured by the results (matching on PMID and DOI). If any seed papers are missed:

1. The missed seed papers are formatted and sent to the LLM along with the original query
2. The LLM generates a *supplementary* query targeting the vocabulary gap
3. The supplement query is executed on PubMed and results are merged (union)
4. This repeats up to `--two-pass-max` times or until all seed papers are captured

This is a closed-loop repair: the system only checks whether its own query retrieves papers it was already shown (the seeds), so no ground truth is used.

### 6. TF-IDF term mining (`--tfidf`, `--tfidf-top`)

Seed paper titles and abstracts are tokenized and scored with TF-IDF to identify distinctive terms that characterize the topic. The top-ranked terms (after filtering stopwords and overly common biomedical vocabulary) are used to build a supplemental PubMed query.

The pipeline iteratively tries the top N terms, narrowing down if the result count exceeds `--tfidf-max-results`, and falls back to title-only field restriction if needed. Results are merged into the main result set.

### 7. Citation searching (`--citations`, `--citation-depth`, `--citation-direction`)

For each seed paper with a PMID, the pipeline queries the OpenAlex API to retrieve:

- **Forward citations**: papers that cite the seed paper
- **Backward citations**: papers referenced by the seed paper

The PMIDs from these citations are added to the result set. This is purely graph-based traversal — it follows the citation network from known relevant papers regardless of what vocabulary they use.

Results are cached locally per PMID so subsequent runs with the same seeds make zero API calls.

**Depth** (`--citation-depth`): At depth 1 (default), only direct citations of seed papers are fetched. At depth 2+, the pipeline expands outward through the citation graph (citations of citations), capped by `--citation-max-frontier`.

**Direction** (`--citation-direction`): Can be `both` (default), `forward`, or `backward`.

### 8. PubMed Similar Articles (`--similar N`)

For each seed paper PMID, PubMed's "Similar Articles" feature is queried via the Entrez `elink` API. This returns papers that PubMed considers topically related based on its internal document similarity model. Up to N similar articles per seed are fetched and merged.

### 9. Evaluation

The combined result set (base query + all augmentations) is compared against the included studies list. Metrics computed:

| Metric | Description |
|--------|-------------|
| Recall (overall) | Found / total included studies |
| Recall (PubMed only) | Found / PubMed-indexed included studies |
| Precision | Found / total search results |
| NNR | Number needed to read (1/precision) |

If a human search strategy is available (`.docx` file), the same metrics are computed for it and displayed side-by-side for comparison.

## Information leakage

The search process has **no information leakage**. The included studies list is only used for evaluation (computing recall/precision after the search is complete). All search decisions are based on:

- The PROSPERO protocol (available before any search)
- Seed papers (a small subset of known relevant papers, available before searching)
- Citation graphs and PubMed similarity (external data sources, no ground truth)

The `count_found_studies` calls that appear during the pipeline are logging-only — they print progress messages like "Supplement recall: 8->10 (+2)" but never influence which results are added.

## Caching

The pipeline caches aggressively to avoid redundant API calls:

| Cache | Key | What's stored |
|-------|-----|---------------|
| `query_results_cache` | Exact query string | PMIDs, result count, DOI mappings |
| `pubmed_index_cache` | DOI or PMID | Whether the paper is indexed in PubMed |
| `citation_cache` | Seed PMID | Forward and backward citation PMID lists |
| `strategy_cache` | Strategy file path | Extracted human search query |

All caches are JSON files stored in the configured cache directory.
