# Scripts

## extract_prospero_findings.py

Extracts structured JSON from a PROSPERO PDF to support search-strategy generation.

### Setup

Requires environment variable in `.env`:

```bash
OPENAI_API_KEY=your_openai_api_key
```

### Usage

```bash
# Print findings to terminal
uv run src/scripts/extract_prospero_findings.py /path/to/prospero.pdf

# Save findings to a JSON file
uv run src/scripts/extract_prospero_findings.py /path/to/prospero.pdf --output ./results/prospero_findings.json

# Use a specific model
uv run src/scripts/extract_prospero_findings.py /path/to/prospero.pdf --model gpt-5.4
```

### Output

Returns structured JSON with fields used for query construction:

- `review_title`
- `research_objective`
- `population` and `population_synonyms`
- `intervention_or_exposure` and `intervention_synonyms`
- `comparator` and `comparator_synonyms`
- `outcomes`
- `study_designs`
- `conditions_or_diseases`
- `procedures_or_settings`
- `keywords_from_protocol`
- `controlled_vocabulary_terms`
- `databases_mentioned`
- `notes_for_search_strategy`

## generate_pubmed_query.py

Generates a single-line PubMed query from extracted JSON, with optional one-step PDF extraction.

### Usage

```bash
# JSON -> query
uv run src/scripts/generate_pubmed_query.py --extracted-json ./results/prospero_findings.json

# PDF -> extract -> query
uv run src/scripts/generate_pubmed_query.py --pdf /path/to/prospero.pdf

# PDF -> extract -> save JSON + save query
uv run src/scripts/generate_pubmed_query.py \
  --pdf /path/to/prospero.pdf \
  --save-extracted ./results/prospero_findings.json \
  --output ./results/pubmed_query.txt
```

### Output

- Prints one single-line PubMed query to stdout by default.
- Optionally saves extracted JSON (`--save-extracted`) and/or query (`--output`).

## download_seed_papers.py

Downloads metadata for included studies from systematic reviews, preparing them as seed papers for LLM-based search strategy generation.

### Setup

Requires environment variables in `.env`:

```
ENTREZ_EMAIL=your.email@example.com
PUBMED_API_KEY=your_api_key  # Optional, increases rate limit 3x
```

### Usage

```bash
# Download all reviews
uv run src/scripts/download_seed_papers.py

# Download a single review
uv run src/scripts/download_seed_papers.py --review "34 - Lu 2022"

# Force re-download (ignores cache)
uv run src/scripts/download_seed_papers.py --force

# Custom output directory
uv run src/scripts/download_seed_papers.py --output ./my_seeds
```

### Output

Creates JSON files in `seed_papers/` with structure:

```json
{
  "review": "34 - Lu 2022",
  "source_file": "Included Studies.xlsx",
  "paper_count": 12,
  "papers": [
    {
      "pmid": "23406311",
      "doi": "10.1111/codi.12130",
      "title": "A randomized placebo controlled trial...",
      "abstract": "There is evidence that...",
      "authors": ["P Lidder", "S Thomas", ...],
      "journal": "Colorectal disease",
      "year": "2013",
      "mesh_terms": ["Dietary Carbohydrates", "Colorectal Neoplasms", ...],
      "keywords": ["colorectal surgery", ...]
    }
  ]
}
```

### How it works

1. Scans `data/` for systematic review directories
2. Finds included studies Excel files (handles various naming conventions)
3. For each study:
   - If PMID exists: fetches full metadata from PubMed
   - If only DOI: searches PubMed for matching PMID
   - Falls back to Excel data if PubMed lookup fails
4. Saves structured JSON per review

### Caching

- Already-downloaded reviews are skipped automatically
- Use `--force` to re-download
- Cached files are stored in `seed_papers/`

### Notes

- Some studies may have empty data if they're not indexed in PubMed (e.g., conference abstracts)
- API key is optional but recommended (increases rate limit from 3 to 10 requests/sec)
