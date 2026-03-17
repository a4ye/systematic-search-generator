# Usage Guide

This tool generates PubMed systematic review search queries from a PROSPERO protocol PDF, with optional seed papers and multiple augmentation strategies.

## Setup

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure Environment Variables

Create or edit `.env` in the project root:

```bash
# Required for LLM query generation
OPENAI_API_KEY=sk-...

# Required for PubMed API (higher rate limits)
PUBMED_API_KEY=your-ncbi-api-key

# Email for NCBI Entrez API (required by NCBI)
ENTREZ_EMAIL=your-email@example.com

# Optional: OpenAlex API (required for --citations)
OPENALEX_API_KEY=your-openalex-api-key

# Optional: contact email for OpenAlex requests
OPENALEX_EMAIL=your-email@example.com
```

## Basic Usage

```bash
# Generate a query from a PROSPERO PDF
uv run python -m src.generate_query protocol.pdf

# Extract the systematic review plan only (no query generation)
uv run python -m src.generate_query protocol.pdf --extract

# Specify output file prefix (generates PREFIX.md and PREFIX.ris)
uv run python -m src.generate_query protocol.pdf --output results/my_review

# Provide seed papers as PMIDs
uv run python -m src.generate_query protocol.pdf --seeds 12345,67890

# Full example with augmentation
uv run python -m src.generate_query protocol.pdf \
  --seeds 12345,67890 \
  --output results/my_review \
  -n 3 \
  --tfidf \
  --block-drop \
  --mesh-entry-terms \
  --citations \
  --two-pass \
  --similar 5
```

## Arguments

### Positional

| Argument | Description |
|----------|-------------|
| `prospero_pdf` | Path to the PROSPERO protocol PDF |

### Core Options

| Flag | Description |
|------|-------------|
| `--seeds PMIDS` | Comma-separated PMIDs of seed papers (e.g., `--seeds 12345,67890`). Metadata (title, abstract, MeSH, keywords) is fetched from PubMed and included in the LLM prompt. |
| `--output PREFIX` | Output file prefix. Generates `PREFIX.md` (report) and `PREFIX.ris` (results). Default: `output`. |
| `--extract` | Extract the systematic review plan only (no query generation). Prints the structured plan and exits. |
| `-n N` | Run query generation N times and merge results (union of PMIDs). LLM calls run in parallel. Default: 1. |
| `--double-prompt` | Repeat the query prompt twice in a single message for emphasis. |
| `--seed-fields CODES` | Control which seed paper fields to include: `t`=title, `a`=abstract, `m`=MeSH, `k`=keywords. Default: `tamk` (all). E.g., `--seed-fields tm` for title + MeSH only. |

### Augmentation Options

| Flag | Description |
|------|-------------|
| `--tfidf` | Add a TF-IDF term-mined supplemental query from seed papers. Requires `--seeds`. |
| `--tfidf-top N` | Number of TF-IDF terms to include (default: 8). |
| `--tfidf-max-results N` | Max PubMed results for the TF-IDF supplemental query (default: 20000). |
| `--block-drop` | Add block-drop supplemental queries by removing one top-level AND block at a time. |
| `--block-drop-max-results N` | Max PubMed results for block-drop queries (default: 20000). |
| `--block-drop-field MODE` | Field tightening for block-drop: `none`, `ti`, `majr`, `ti+majr` (default: `ti`). |
| `--two-pass` | Generate supplementary queries for seed papers missed by the primary query. |
| `--two-pass-max N` | Max number of supplementary passes (default: 3). |
| `--mesh-entry-terms` | Expand MeSH terms in the query with entry-term free-text variants. |
| `--mesh-entry-max N` | Max entry terms per MeSH heading (default: 6). |
| `--citations` | Augment results with forward/backward citations of seed papers via OpenAlex. |
| `--citation-depth N` | Citation expansion depth (default: 1). |
| `--citation-direction DIR` | Citation direction: `both`, `forward`, or `backward` (default: `both`). |
| `--citation-max-frontier N` | Cap works expanded per depth, 0 = no cap (default: 0). |
| `--similar N` | Fetch up to N PubMed "Similar Articles" per seed paper (0 = disabled). |
| `--similar-augment N` | Second-round similar articles per augmentation-hit PMID (0 = disabled). |
| `--similar-augment-sample N` | Max augmentation-hit PMIDs to sample for round 2 (default: 10). |

## Output

The tool produces two output files:

### Markdown Report (`PREFIX.md`)

Contains:
- Run settings (model, flags, seed PMIDs)
- Primary query (the merged Boolean query sent to PubMed)
- Individual LLM-generated queries (when `-n > 1`)
- Augmentation details:
  - Two-pass supplement queries and pass-by-pass PMID counts
  - Block-drop variant queries and result counts
  - TF-IDF supplemental query and terms
  - Citation expansion stats (depth, direction, PMIDs found)
  - Similar articles stats (per-seed counts, new/duplicate)
- Result summary with total PMID count

### RIS File (`PREFIX.ris`)

Contains one entry per PMID with DOI when available:

```
TY  - JOUR
ID  - 12345678
DO  - 10.1234/example
ER  -
```


## Rate Limits

The pipeline respects PubMed rate limits:
- Without API key: 3 requests/second
- With API key: 10 requests/second

If you encounter rate limit errors, ensure `PUBMED_API_KEY` is set in `.env`.
