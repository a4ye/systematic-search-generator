# Automated Testing Pipeline for PubMed Search Query Generation

## Context

Currently, LLM-generated PubMed search queries are being tested manually against human-crafted strategies. This is
time-consuming and limits the ability to systematically evaluate different prompts across all 20+ systematic reviews in
the dataset. This pipeline automates the entire workflow: generating queries from PROSPERO PDFs, extracting human
strategies from .docx files, running both on PubMed, and comparing results.

## Key Challenges

1. **Inconsistent file naming**: Each study folder has different naming patterns for PROSPERO PDFs, Included Studies
   Excel files, and Search Strategy docs
2. **Human strategies in tables/images**: Search Strategy.docx files contain queries in tables or images that can't be
   simply text-parsed
3. **Rate limits**: PubMed Entrez API has rate limits (3 req/sec without API key). An API key is provided in .env (10
   req/sec), make sure to not exceed limits.

## Architecture

```
src/
├── compare_search.py          # Existing - reuse PubMedSearchResults, extract_included_studies
├── pipeline/
│   ├── runner.py              # Main orchestrator
│   └── config.py              # Configuration (API keys, paths)
├── discovery/
│   ├── study_finder.py        # Find all study directories
│   └── file_resolver.py       # Fuzzy match files by pattern
├── llm/
│   ├── openai_client.py       # OpenAI API wrapper
│   ├── query_generator.py     # Generate query from PROSPERO PDF
│   └── strategy_extractor.py  # Extract human query from .docx via vision
├── pubmed/
│   └── search_executor.py     # Execute query, fetch MEDLINE results
├── evaluation/
│   ├── metrics.py             # Calculate recall, precision, NNR
│   ├── comparator.py          # Compare LLM vs human
│   └── reporter.py            # Generate reports
└── cache/
    └── strategy_cache.py      # Cache extracted human strategies
```

## Implementation Plan

### Phase 1: File Discovery

**`src/discovery/file_resolver.py`**

- Fuzzy pattern matching for variable file names
- Patterns for PROSPERO: `*PROSPERO*.pdf`, `Protocol.pdf`, `CRD*.pdf`
- Patterns for Included Studies: `*[Ii]ncluded*[Ss]tud*.xlsx`
- Patterns for Search Strategy: `*[Ss]earch*[Ss]trateg*.docx`

**`src/discovery/study_finder.py`**

- Scan `data/` directory for study folders
- Return `StudyInfo` dataclass with paths to all files (or None if missing)

### Phase 2: OpenAI Integration

**`src/llm/openai_client.py`**

- Wrapper for OpenAI API with retry logic (use `tenacity`)
- Support for PDF file uploads (base64 encoding)
- Support for vision API (docx converted to images)

**`src/llm/query_generator.py`**

- Send PROSPERO PDF + balanced prompt to OpenAI
- Model: `gpt-5.4` (latest GPT model with file understanding)
- Validate output is valid PubMed syntax (balanced parentheses, valid operators)

**`src/llm/strategy_extractor.py`**

- Send .docx file directly to OpenAI API (file upload)
- Model: `gpt-4.5-preview` (same model, supports document understanding)
- Parse response to get PubMed query string
- Cache results keyed by file hash

**Prompt for query generation** (from devlog.md):

```
You are a medical librarian creating a PubMed search strategy.

TARGET PERFORMANCE:
- Total results: 400-1,000 papers (optimal sweet spot)
- Recall: 90-95% of relevant studies
- Balance comprehensiveness with precision
...
```

**Prompt for strategy extraction**:

```
Extract the PubMed/MEDLINE search query from this systematic review search strategy document.
The query may be in a table format with numbered lines - combine them into a single boolean query.
Output ONLY the final query string, nothing else.
If no PubMed/MEDLINE strategy exists, output "NOT_FOUND".
```

### Phase 3: PubMed Execution

**`src/pubmed/search_executor.py`**

- Use `Bio.Entrez.esearch()` to get PMIDs for a query
- Use `Bio.Entrez.efetch()` to download MEDLINE records
- Batch fetching (200 records at a time) with rate limiting
- Return parsed records using existing `PubMedSearchResults` class

### Phase 4: Evaluation

**`src/evaluation/metrics.py`**

- Reuse logic from `compare_search.py`
- Calculate: recall (overall), recall (PubMed-indexed only), precision, NNR, F1

**`src/evaluation/comparator.py`**

- Run both LLM and human queries
- Compare metrics side-by-side
- Determine "winner" based on recall-precision trade-off

**`src/evaluation/reporter.py`**

- Console output with tables (use `rich`)
- Markdown report for documentation
- CSV export for further analysis

### Phase 5: Caching

**`src/cache/strategy_cache.py`**

- JSON file: `.cache/human_strategies.json`
- Key: file path, Value: {query, file_hash, extracted_at, model}
- Invalidate if file hash changes

### Phase 6: Pipeline Runner

**`src/pipeline/runner.py`**

- Orchestrate full workflow
- Support two modes: single study or batch (all studies)
- Parallel processing of studies in batch mode (async)
- Error isolation (one study failing doesn't stop others)
- Progress reporting

**CLI interface**:

```bash
# Single study mode - test one systematic review
uv run python -m src.pipeline.runner --study 34               # Run study 34 (Lu 2022)
uv run python -m src.pipeline.runner --study 92               # Run study 92 (Pitesa 2025)

# Batch mode - test all systematic reviews
uv run python -m src.pipeline.runner --all                    # Run all studies in data/

# Multiple specific studies
uv run python -m src.pipeline.runner --studies 34,92,101      # Run specific studies

# Additional options (can combine with above)
uv run python -m src.pipeline.runner --study 34 --llm-only    # Skip human comparison
uv run python -m src.pipeline.runner --all --refresh-cache    # Re-extract human strategies
uv run python -m src.pipeline.runner --all --human-only       # Only evaluate human strategies
```

**Output modes**:

- Single study: Detailed console output with full metrics and missed studies
- Batch mode: Summary table + detailed markdown report saved to `results/`

## Dependencies to Add

```toml
dependencies = [
    "biopython>=1.86",
    "openpyxl>=3.1.0",
    "openai>=1.0.0",
    "python-docx>=1.0.0",
    "tenacity>=8.2.0",
    "rich>=13.0.0",
]
```

Note: pdf2image/pillow not needed since we send files directly to OpenAI API.

## Files to Modify/Create

| File                             | Action                                  |
|----------------------------------|-----------------------------------------|
| `pyproject.toml`                 | Add dependencies                        |
| `src/discovery/file_resolver.py` | Create                                  |
| `src/discovery/study_finder.py`  | Create                                  |
| `src/llm/openai_client.py`       | Create                                  |
| `src/llm/query_generator.py`     | Create                                  |
| `src/llm/strategy_extractor.py`  | Create                                  |
| `src/pubmed/search_executor.py`  | Create                                  |
| `src/evaluation/metrics.py`      | Create (extract from compare_search.py) |
| `src/evaluation/comparator.py`   | Create                                  |
| `src/evaluation/reporter.py`     | Create                                  |
| `src/cache/strategy_cache.py`    | Create                                  |
| `src/pipeline/runner.py`         | Create                                  |
| `src/pipeline/config.py`         | Create                                  |

## Verification

1. **Unit tests**: Test file discovery on actual data directory
2. **Integration test**: Run single study (34 - Lu 2022) end-to-end
3. **Comparison validation**: Verify metrics match manual calculations from devlog
4. **Cache test**: Run twice, confirm second run uses cache

```bash
# Test discovery
uv run python -c "from src.discovery.study_finder import StudyFinder; print(StudyFinder('data').discover_all())"

# Test single study
uv run python -m src.pipeline.runner --studies 34

# Verify against devlog results (Lu 2022 should show ~80% PubMed recall with balanced prompt)
```
