# Scripts

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
