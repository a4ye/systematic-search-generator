# Iteration Log

## 2026-03-12 Baseline

Command:

`basic-benchmark.sh` (studies `34`, `92`, `110`)

Observed baseline issues:

- LLM generation worked on `34` and `92`, but `110` failed during PubMed fetch with a transient network error (`Remote end closed connection without response`), resulting in `LLM = N/A` for that study.
- `110` is the main quality gap: when run separately (`--study 110 --llm-only`) it produced:
  - `2433` results
  - recall (PubMed-only): `71.2%` (`52/73`)
  - human recall (PubMed-only) reference: `98.6%` (`72/73`)
- Main failure mode appears to be unstable composition for early-onset symptom/presentation reviews.

## 2026-03-12 Change 1 (Reliability)

Files:

- `src/pubmed/search_executor.py`

What changed:

- Added retry/backoff wrapper for Entrez calls (`esearch`, `esummary`, `efetch`) used in count/search/fetch/validation paths.
- Retries transient network failures (`URLError`, `RemoteDisconnected`, `IncompleteRead`, timeouts, etc.).
- Keeps fast-fail behavior for query syntax style errors (`HTTP 400/404`).

Reason:

- Prevent benchmark runs from failing due transient network drops, especially on larger result sets.

## 2026-03-12 Change 2 (Query Quality for EOCRC Symptom Reviews)

Files:

- `src/llm/query_generator.py`

What changed:

- Added detector for early-onset symptom/presentation review patterns in extracted JSON.
- Added deterministic `symptom_rule_v1` query composer for those cases:
  - explicit 3-block structure: `(age) AND (disease) AND (symptom/presentation)`
  - consistent inclusion of high-recall diagnosis/presentation terms
  - avoids standalone demographic MeSH in OR with disease
- Wired `generate_query` to use `symptom_rule_v1` when the pattern is detected; otherwise keeps existing LLM compose/refine flow.

Reason:

- Study `110` repeatedly underperformed due LLM drift in symptom/presentation block construction.
- Deterministic composition should improve recall stability for this review type.

## 2026-03-12 Change 3 (Generalized, Seed-Aware Structured Composer)

Files:

- `src/llm/query_generator.py`

What changed:

- Added deterministic seed sampling when `rng_seed` is not provided (stable hash of study id/name).
- Added a structured, seed-aware query composer used for general reviews (`structured_seed_v1`):
  - Scores candidate terms by source (controlled vocabulary, core concepts, exact phrases, proxy terms, seed keywords/MeSH).
  - Filters generic MeSH and boilerplate free-text terms.
  - Limits terms per block and expands free-text with truncation/spelling variants.
- LLM composition is now a fallback when the structured composer cannot build a query.

Reason:

- Reduce run-to-run variability from random seed selection.
- Improve consistency and generalizability across review types by relying on deterministic rules rather than LLM drift.

Mistakes / Lessons:

- Adding broad MeSH (e.g., `Digestive System Surgical Procedures`, `Colon`) can explode result counts without improving recall; generic MeSH now filtered unless explicitly signaled in the review text.

## 2026-03-12 Change 4 (Diet Recall Broadening + Appendiceal Coverage)

Files:

- `src/llm/query_generator.py`

What changed:

- Diet composer now:
  - Adds `Appendiceal Diseases`/`Appendix` MeSH and `appendiceal` text when appendicitis is the target condition.
  - Prioritizes `fiber`/`fibre` (broad text words) to match diet studies that use unqualified fibre terms.
  - Uses `[tw]` for core diet/fiber terms to slightly broaden matching beyond title/abstract.
  - Expands diet seed usage to 5 papers (still limited) for high-heterogeneity lifestyle reviews.
- Controlled vocabulary cleanup removes generic `/surgery` disease headings when more specific terms exist.

Reason:

- Diet/appendicitis reviews are heterogeneous; broader diet/fiber matching improves recall without relying on included-studies feedback.

Mistakes / Lessons:

- Overly broad subheading terms (e.g., `Colonic Diseases/surgery`) caused large result inflation; additional cleanup rules added.
