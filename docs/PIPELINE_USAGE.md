# Automated Testing Pipeline Usage Guide

This pipeline automates the evaluation of LLM-generated PubMed search queries against human-crafted strategies from systematic reviews.

## Setup

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure Environment Variables

Create or edit `.env` in the project root:

```bash
# Required for LLM query generation and strategy extraction
OPENAI_API_KEY=sk-...

# Required for PubMed API (higher rate limits)
PUBMED_API_KEY=your-ncbi-api-key

# Email for NCBI Entrez API (required by NCBI)
ENTREZ_EMAIL=your-email@example.com

# Optional: OpenAlex API (required for higher rate limits)
OPENALEX_API_KEY=your-openalex-api-key

# Optional: contact email for OpenAlex requests
OPENALEX_EMAIL=your-email@example.com
```

## Commands

### List Available Studies

View all discovered studies and their completeness status:

```bash
uv run python -m src.pipeline.runner --list
```

Output shows:
- **Complete studies**: Have PROSPERO PDF, Search Strategy, and Included Studies
- **Incomplete studies**: Missing one or more required files

### Run Single Study

Test one systematic review with detailed output:

```bash
# Full comparison (LLM vs Human)
uv run python -m src.pipeline.runner --study 34

# LLM-generated query only
uv run python -m src.pipeline.runner --study 34 --llm-only

# Human strategy only
uv run python -m src.pipeline.runner --study 34 --human-only
```

### Run Multiple Studies

Test specific studies:

```bash
uv run python -m src.pipeline.runner --studies 34,92,101
```

### Run All Complete Studies

Batch process all studies that have required files:

```bash
uv run python -m src.pipeline.runner --all
```

### Compare Your Own Query

Test a custom PubMed query against a study's included papers:

```bash
# Evaluate your query against study 34
uv run python compare_query.py 34

# Also show the human strategy side-by-side
uv run python compare_query.py 34 --show-human
```

The script prompts you to paste a PubMed query in the terminal (enter a blank line when done), then runs it against PubMed and displays recall, precision, and NNR.

### Generate Query (Two-Step Prompt)

Generate a PubMed query from a PROSPERO PDF and evaluate it against the human strategy:

```bash
# Generate, evaluate, and compare against human strategy
uv run python generate_query.py 34

# Skip human comparison
uv run python generate_query.py 34 --no-human

# Extract the systematic review plan only (no query generation)
uv run python generate_query.py 34 --extract

# Run multiple studies at once (prints per-study tables + summary)
uv run python generate_query.py 34 35 36

# Generate N queries per study and merge PubMed results (union of PMIDs)
uv run python generate_query.py 34 -n 3

# Repeat the prompt twice in a single message for emphasis
uv run python generate_query.py 34 --double-prompt

# Include 3 random seed papers (from seed_papers/) in the prompt
uv run python generate_query.py 34 --seeds 3

# Augment results with forward/backward citations of seed papers via OpenAlex
uv run python generate_query.py 34 --seeds 3 --citations

# Combine options
uv run python generate_query.py 34 35 -n 3 --double-prompt --seeds 3 --citations --no-human
```

The script runs two LLM calls: first extracting the structured plan from the PDF, then generating a query from that plan. The model and prompts are configured at the top of `generate_query.py` (`MODEL`, `EXTRACT_PROMPT`, `QUERY_PROMPT`).

| Flag | Description |
|------|-------------|
| `-n N` | Run query generation N times per study and merge results (union of PMIDs). LLM calls run in parallel. |
| `--double-prompt` | Repeat the full query prompt twice in a single message for emphasis. |
| `--seeds N` | Include N random seed papers (title, abstract, MeSH, keywords) from `seed_papers/` in the prompt. Papers with missing data are skipped. Default 0 (disabled). |
| `--seed-fields CODES` | Control which seed paper fields to include: `t`=title, `a`=abstract, `m`=MeSH, `k`=keywords. Default `tamk` (all). E.g. `--seed-fields tm` for title + MeSH only. |
| `--tfidf` | Add a TF-IDF term-mined supplemental query from seed papers (requires `--seeds`). |
| `--tfidf-top N` | Number of TF-IDF terms to include (default: 8). |
| `--tfidf-max-results N` | Maximum PubMed results allowed for the TF-IDF supplemental query (default: 20000). |
| `--citations` | Augment query results with forward/backward citations of seed papers via the OpenAlex API. Requires `--seeds`. Unions citation PMIDs with Boolean query PMIDs before evaluation. |
| `--citation-depth N` | Citation expansion depth (1 = direct citations only). |
| `--citation-direction {both,forward,backward}` | Citation direction to follow (default: both). |
| `--citation-max-frontier N` | Cap number of works expanded at each depth (0 = no cap). |
| `--two-pass` | Generate a supplementary query for missed seed papers and merge results. |
| `--two-pass-max N` | Maximum number of supplementary passes to run (default: 3). |
| `--mesh-entry-terms` | Expand MeSH terms with entry-term free-text variants. |
| `--mesh-entry-max N` | Maximum number of entry terms per MeSH heading (default: 6). |
| `--similar N` | Fetch up to N PubMed "Similar Articles" per seed paper and merge results (0 = disabled). |
| `--show-missed` | Append a "Missed Papers" section to the results file listing PubMed-indexed papers not captured by the query, with title, abstract, MeSH terms, and keywords (enriched from `seed_papers/` cache). |
| `--save-prompt` | Append the full composed LLM prompt to the results file. |
| `--no-human` | Skip human strategy comparison. |
| `--extract` | Extract the systematic review plan only (no query generation). |

When multiple studies are provided, a summary table is printed at the end with aggregate recall, precision, NNR, and human baseline columns.

### Additional Options

| Flag | Description |
|------|-------------|
| `--llm-only` | Skip human strategy evaluation |
| `--human-only` | Skip LLM query generation |
| `--refresh-cache` | Force re-extraction of human strategies (ignore cache) |
| `--output PATH` | Custom output directory for reports |

## Output

### Single Study Mode

Displays a detailed comparison table:

```
Study: 34 - Lu 2022
────────────────────────────────────────────────────────────
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Metric           ┃   LLM ┃ Human ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ Results          │   410 │  3656 │
│ Recall (overall) │ 75.0% │ 83.3% │
│ Recall (PubMed)  │ 90.0% │100.0% │
│ Precision        │  2.2% │  0.3% │
│ NNR              │  45.6 │ 304.7 │
│ Found / Total    │  9/12 │ 10/12 │
└──────────────────┴───────┴───────┘
Winner: LLM
```

### Batch Mode

Generates:
- Console summary table
- `results/comparison_report.md` - Detailed markdown report
- `results/comparison_results.csv` - CSV for further analysis

## Metrics Explained

| Metric | Description |
|--------|-------------|
| **Results** | Total papers returned by the search query |
| **Recall (overall)** | % of included studies found by the search |
| **Recall (PubMed)** | % of PubMed-indexed included studies found |
| **Precision** | % of search results that are included studies |
| **NNR** | Number Needed to Read (results per included study found) |
| **F1 Score** | Harmonic mean of precision and recall |

## Caching

Human search strategies extracted from `.docx` files are cached in `.cache/human_strategies.json` to avoid redundant API calls. The cache is automatically invalidated if the source file changes.

To force re-extraction:

```bash
uv run python -m src.pipeline.runner --study 34 --refresh-cache
```

## Data Directory Structure

The pipeline expects studies in `data/` with this naming pattern:

```
data/
├── 34 - Lu 2022/
│   ├── PROSPERO.pdf              # or *PROSPERO*.pdf, Protocol.pdf
│   ├── Search Strategy.docx      # or *Search*Strateg*.docx
│   └── Included Studies.xlsx     # or *Included*Stud*.xlsx
├── 92 - Pitesa 2025/
│   └── ...
```

File names are matched using fuzzy patterns, so variations like `Lu 2022 PROSPERO.pdf` or `Included Studies - Lu 2022.xlsx` work automatically.

## Troubleshooting

### "OPENAI_API_KEY is not set"

Add your OpenAI API key to `.env`:
```bash
OPENAI_API_KEY=sk-proj-...
```

### "Missing PROSPERO PDF"

The study directory doesn't contain a file matching `*PROSPERO*.pdf`, `*Protocol*.pdf`, or `CRD*.pdf`.

### Rate Limiting

The pipeline respects PubMed rate limits:
- Without API key: 3 requests/second
- With API key: 10 requests/second

If you encounter rate limit errors, ensure `PUBMED_API_KEY` is set in `.env`.
