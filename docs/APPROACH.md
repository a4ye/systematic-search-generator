# How the Pipeline Works

This document describes the end-to-end approach used by `generate_query.py` to automatically generate PubMed search strategies for systematic reviews.

## Overview

The pipeline takes a PROSPERO protocol PDF and produces a PubMed Boolean query. Several augmentation layers can be stacked on top of the base query to improve recall. The final result set (all unique PMIDs) is exported as a RIS file for import into reference managers.

```
PROSPERO PDF + seed PMIDs (optional)
    │
    ▼
[1] Extract plan (LLM)
    │
    ▼
[2] Generate Boolean query (LLM, optionally N times)
    │  ├── seed paper metadata injected into prompt
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
[6] Block-drop supplement (no LLM)
    │
    ▼
[7] TF-IDF term mining (no LLM)
    │
    ▼
[8] Citation searching (OpenAlex API)
    │
    ▼
[9] PubMed Similar Articles (Entrez API)
    │
    ▼
[10] Write markdown report + RIS file
```

All augmentation steps (5-9) union their results into a single combined result set.

## Step-by-step

### 1. Plan extraction (`--extract`)

The PROSPERO protocol PDF is sent to the LLM (GPT-5.3) with an extraction prompt that pulls out the structured review plan: title, condition, PICO elements (excluding outcomes). The LLM is instructed to copy text verbatim from the document.

### 2. Query generation (`-n`, `--seeds`, `--seed-fields`, `--double-prompt`)

The extracted plan is combined with a query generation prompt containing 11 instructions for building a PubMed Boolean query optimized for sensitivity. Key instructions include:

- Identify 2-3 core concept blocks (condition, phenomenon, population modifier)
- Combine MeSH terms and free-text synonyms with OR within blocks
- Avoid overly generic terms that explode result counts
- Use vocabulary from the literature, not protocol wording

**Seed papers** (`--seeds PMID1,PMID2`): Seed paper metadata (title, abstract, MeSH terms, keywords) is fetched from PubMed via the Entrez API and appended to the prompt. The LLM is told to use their MeSH terms, keywords, and vocabulary to inform term selection. Fields included are controlled by `--seed-fields` (t=title, a=abstract, m=MeSH, k=keywords).

**Query ensembling** (`-n N`): The query generation is run N times in parallel. Each run produces a slightly different Boolean query due to LLM sampling. The unique queries are OR-merged into a single union query before execution. This increases vocabulary coverage since different runs emphasize different synonyms.

### 3. MeSH entry-term expansion (`--mesh-entry-terms`)

After the LLM generates the query, MeSH headings in the query (e.g., `"Colorectal Neoplasms"[Mesh]`) are detected and expanded with entry-term synonyms from the MeSH database. For example, `"Colorectal Neoplasms"[Mesh]` might get `"Colorectal Tumor"[tiab]` and `"Colorectal Cancer"[tiab]` appended as OR terms.

This is a deterministic, offline step that uses the local MeSH XML database with no API calls. It catches free-text variants that the LLM may have missed.

### 4. PubMed execution

The final query is executed against PubMed via the NCBI Entrez API.

### 5. Two-pass supplement (`--two-pass`, `--two-pass-max`)

After the initial query is executed, the pipeline checks which seed papers were captured by the results (matching on PMID and DOI). If any seed papers are missed:

1. The missed seed papers are formatted and sent to the LLM along with the original query
2. The LLM generates a *supplementary* query targeting the vocabulary gap
3. The supplement query is executed on PubMed and results are merged (union)
4. This repeats up to `--two-pass-max` times or until all seed papers are captured

This is a closed-loop repair: the system only checks whether its own query retrieves papers it was already shown (the seeds).

### 6. Block-drop supplement (`--block-drop`, `--block-drop-max-results`, `--block-drop-field`)

The pipeline generates supplemental queries by dropping one top-level AND block from the final query (e.g., dropping the population block). Each variant is optionally tightened by field (`ti`, `majr`, or both), capped by `--block-drop-max-results`, and then merged into the main result set if it stays under the cap.

This expands recall for topics where a single block is overly restrictive, while the field tightening and max-results cap help control precision loss.

### 7. TF-IDF term mining (`--tfidf`, `--tfidf-top`)

Seed paper titles and abstracts are tokenized and scored with TF-IDF to identify distinctive terms that characterize the topic. The top-ranked terms (after filtering stopwords and overly common biomedical vocabulary) are used to build a supplemental PubMed query.

The pipeline iteratively tries the top N terms, narrowing down if the result count exceeds `--tfidf-max-results`, and falls back to title-only field restriction if needed. Results are merged into the main result set.

### 8. Citation searching (`--citations`, `--citation-depth`, `--citation-direction`)

For each seed paper with a PMID, the pipeline queries the OpenAlex API to retrieve:

- **Forward citations**: papers that cite the seed paper
- **Backward citations**: papers referenced by the seed paper

The PMIDs from these citations are added to the result set. This is purely graph-based traversal that follows the citation network from known relevant papers regardless of what vocabulary they use.

**Depth** (`--citation-depth`): At depth 1 (default), only direct citations of seed papers are fetched. At depth 2+, the pipeline expands outward through the citation graph (citations of citations), capped by `--citation-max-frontier`.

**Direction** (`--citation-direction`): Can be `both` (default), `forward`, or `backward`.

### 9. PubMed Similar Articles (`--similar N`)

For each seed paper PMID, PubMed's "Similar Articles" feature is queried via the Entrez `elink` API. This returns papers that PubMed considers topically related based on its internal document similarity model. Up to N similar articles per seed are fetched and merged.

A second round (`--similar-augment`) can fetch similar articles for PMIDs added by other augmentation steps (two-pass, block-drop, TF-IDF, citations, round-1 similar articles), sampling up to `--similar-augment-sample` PMIDs from the augmentation pool.

### 10. Output

The pipeline writes two files:

- **Markdown report** (`PREFIX.md`): Contains run settings, all generated queries, augmentation details and statistics, and total result count.
- **RIS file** (`PREFIX.ris`): Contains one entry per PMID with DOI when available, importable into reference managers.
