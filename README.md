# Automated PubMed Query Generation for Systematic Reviews

This tool automatically generates PubMed Boolean search queries for systematic reviews. Given a PROSPERO protocol PDF and optional seed papers, it produces a high-recall search query using LLM-based generation combined with multiple augmentation strategies. Results are exported as a RIS file. This approach reduces errors by 69%, making 3.2x fewer mistakes than human-generated queries on the benchmark set of 11 reviews.

## Installation

```bash
uv sync
```

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=sk-...
PUBMED_API_KEY=your-ncbi-api-key
ENTREZ_EMAIL=your-email@example.com

# Optional (required for --citations)
OPENALEX_API_KEY=your-openalex-api-key
OPENALEX_EMAIL=your-email@example.com
```

## Usage

### Generate a query

```bash
# Basic: generate from a PROSPERO PDF
uv run python -m src.generate_query protocol.pdf

# With seed papers and output prefix
uv run python -m src.generate_query protocol.pdf \
  --seeds 12345678,23456789 \
  --output results/my_review

# Full augmentation
uv run python -m src.generate_query protocol.pdf \
  --seeds 12345678,23456789 \
  --output results/my_review \
  -n 5 \
  --seed-fields tm \
  --citations --citation-depth 1 \
  --two-pass --two-pass-max 10 \
  --similar 100 --similar-augment 100 --similar-augment-sample 20 \
  --mesh-entry-terms --mesh-entry-max 8 \
  --tfidf --tfidf-top 8 --tfidf-max-results 30000 \
  --block-drop
```

This produces two files:
- `results/my_review.md`: detailed report with all queries executed, augmentation stats, and result counts
- `results/my_review.ris`: RIS file with all result PMIDs and DOIs

## How It Works

The pipeline runs in two LLM calls followed by optional augmentation steps:

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
[3] MeSH entry-term expansion (offline)
    │
    ▼
[4] Execute on PubMed → base result set
    │
    ▼
[5-9] Augmentation (all optional, results unioned)
    │  ├── Two-pass supplement (LLM)
    │  ├── Block-drop supplement
    │  ├── TF-IDF term mining
    │  ├── Citation expansion (OpenAlex)
    │  └── PubMed Similar Articles
    │
    ▼
[10] Write markdown report + RIS file
```

**Step 1: Plan extraction.** The PROSPERO PDF is sent to the LLM (GPT-5.3-chat) which extracts a structured plan: title, condition, and PICO elements (excluding outcomes), copied verbatim from the document.

**Step 2: Query generation.** The plan is combined with a prompt instructing the LLM to build a PubMed Boolean query optimized for sensitivity. Seed paper metadata (title, abstract, MeSH terms, keywords) is fetched from PubMed by PMID and included in the prompt so the LLM can use real indexing vocabulary. With `-n N`, N queries are generated in parallel and OR-merged for broader vocabulary coverage.

**Step 3: MeSH entry-term expansion.** MeSH headings in the query are expanded with free-text entry-term synonyms from the local MeSH database. This is deterministic and offline.

**Step 4: PubMed execution.** The query is executed via the NCBI Entrez API.

**Steps 5-9: Augmentation.** Each augmentation strategy adds PMIDs to the result set independently:

- **Two-pass** (`--two-pass`): checks which seed papers the query missed, asks the LLM to generate a supplementary query targeting the gap, repeats up to `--two-pass-max` times
- **Block-drop** (`--block-drop`): generates variants by dropping one AND block at a time, with field tightening and result count caps to control precision loss
- **TF-IDF** (`--tfidf`): mines distinctive terms from seed paper text using TF-IDF and builds a supplemental query from the top-ranked terms
- **Citations** (`--citations`): fetches forward and backward citations of seed papers via the OpenAlex API
- **Similar Articles** (`--similar N`): fetches PubMed's "Similar Articles" for each seed paper via the Entrez elink API

## Design Decisions


**Two-step prompting.** Plan extraction and query generation are separate LLM calls. The extraction step uses a specific prompt with strict guidelines that instruct the LLM to copy text verbatim from the PROSPERO document, with no paraphrasing, no interpretation, and no making up information. This ensures the extracted plan is consistent and faithful to the source material, rather than letting the LLM decide what to include. The query generation step then works from this clean, structured plan instead of raw PDF text.

**Query ensembling.** Running the LLM N times (`-n N`) and merging results increases recall because different runs emphasize different synonyms and MeSH terms due to sampling variance. Some queries may miss papers or terms that other queries capture. Taking the union averages out these gaps and produces more consistent results. This is similar in concept to random forests, where combining many weak models yields a stronger one.

**MeSH entry-term expansion.** LLMs do not have reliable knowledge of MeSH vocabulary. They may use a MeSH heading like `"Colorectal Neoplasms"[Mesh]` but miss free-text synonyms that PubMed recognizes. The MeSH expansion step fills this gap by looking up each MeSH heading in the local MeSH database and appending its entry-term variants (e.g., `"Colorectal Tumor"[tiab]`, `"Colorectal Cancer"[tiab]`) as additional OR terms.

**Multi-layered augmentation.** Each augmentation strategy targets a different failure mode of the base query: block-drop boosts recall in case the LLM made the query too restrictive by removing one AND block at a time; TF-IDF term mining finds relevant terms directly from seed paper text that the LLM may have overlooked; citation expansion via OpenAlex and PubMed Similar Articles capture studies through graph-based relationships that no Boolean query would find, regardless of vocabulary.

**Redundancy for consistency.** LLM outputs are stochastic. The same prompt can produce different queries on each run, with different synonym choices, different MeSH terms, and different structural decisions. A single run may miss important vocabulary that another run would catch. The pipeline addresses this at multiple levels: query ensembling runs the LLM N times and takes the union, augmentation strategies overlap in what they capture, and deterministic steps like MeSH expansion guarantee coverage that does not depend on LLM sampling. The cost is a larger result set, but for systematic reviews, high recall is more important than precision.

**No information leakage.** All search decisions are based on the PROSPERO protocol and seed papers, both of which are available before any search is conducted. The included studies list is never used during query generation.

## Benchmarks

Parameters used:

```bash
uv run python -m src.generate_query protocol.pdf \
  -n 5 \
  --seeds <5 random seeds per review> \
  --seed-fields tm \
  --citations --citation-depth 1 \
  --two-pass --two-pass-max 10 \
  --similar 100 \
  --mesh-entry-terms --mesh-entry-max 8 \
  --tfidf --tfidf-top 8 --tfidf-max-results 30000 \
  --block-drop \
  --similar-augment 100 --similar-augment-sample 20
```

From testing, these parameters were found to yield the best recall results while keeping result counts manageable. There probably exists a better parameter configuration that would yield even higher recall, but finding it would be quite time consuming. It is recommended to use the above parameters for general use.

Results across 11 systematic reviews (studies 34, 43, 76, 88, 92, 101, 110, 118, 131, 143), with 5 randomly selected seed papers per review:

|  | Mean PubMed Recall | Mean Results Returned |
|--|-------------------:|----------------------:|
| **LLM-generated query** | **97.8%** | 17,621 |
| Human query | 92.9% | 1,805 |

The LLM-generated queries average a 2.2% miss rate compared to the human average of 7.1%, a 69% reduction in errors. Put differently, human queries make 3.2x more mistakes than the LLM-generated queries on this benchmark set.

Recall is the fraction of included papers from the final published review that appear in the query results, counting only PubMed-indexed papers. Only PubMed is used because other databases (Embase, etc.) require paid subscriptions or institutional access. All of the human queries in the testing data were converted to PubMed queries in order to do the comparisons.

The 11 reviews were chosen to include as much of the testing data as possible. Some of the reviews had missing PROSPERO plans, so they could not be used. A few of the other reviews had human queries that yielded terrible results (<20% recall), so they were excluded to avoid skewing the human mean recall.

Some included studies files had formatting errors in DOIs and/or PMIDs. The evaluation code normalizes these before matching.

## Documentation

- [Usage Guide](docs/PIPELINE_USAGE.md): full CLI reference with all flags
- [How the Pipeline Works](docs/APPROACH.md): detailed step-by-step explanation of each pipeline stage
