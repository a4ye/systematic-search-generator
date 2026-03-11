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
