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

## 2026-03-12 Change 5 (Generalizable Structured Builder + MeSH Expansion)

Files:

- `src/llm/query_generator.py`
- `src/cache/mesh_expansion_cache.py`

What changed:

- Structured builder now optionally expands top-scoring text concepts to MeSH using NCBI E-utilities (with persistent cache).
- Added stronger filtering for always-broad MeSH (e.g., `Signs and Symptoms`) and dropped demographic MeSH unless age is clearly signaled.
- Population block now nests age qualifiers with disease terms when age-limited reviews are detected, avoiding standalone demographic MeSH.
- Removed diet/nutrition special-case composers from the main path in favor of a single generalizable builder (symptom rule retained).

Reason:

- Reduce overfitting to specific studies and improve generalization across medical topics.
- Use consistent, seed-aware rules plus controlled MeSH expansion to improve recall without bloating queries.

Mistakes / Lessons:

- Special-case builders for a single topic tend to overfit and harm generalizability; favor generic scoring + expansion instead.

## 2026-03-12 Change 6 (Seed-Aware Refinement + Diet Filtering)

Files:

- `src/llm/query_generator.py`
- `src/pipeline/query_builder.py`

What changed:

- Added broader, general-purpose lexical expansions (e.g., `surg*`, `resect*`, `carbohydrat*`, `preoperat*`) for multi-word terms.
- Introduced controlled diet exposure boosts (diet/fiber/plant-based variants) and carbohydrate-specific boosts.
- Added title-based phrase extraction (short bigrams) to pull high-signal phrases from seed titles.
- Re-enabled LLM refinement but filtered added terms by exposure-core tokens (general case) and diet token whitelist (diet reviews) to prevent drift to irrelevant concepts.
- Seed keyword enrichment now ignores overlaps only on weak tokens (e.g., surgery/procedure) to reduce noise.

Reason:

- Recover recall for heterogeneous diet and perioperative nutrition reviews while keeping precision from collapsing due to overly broad added terms.
- Ensure refined queries only add terms that align with extracted core concepts or diet-related language.

Mistakes / Lessons:

- Unfiltered refinement can add unrelated terms (e.g., infection, ERAS, broad MeSH) and explode result counts; post-filtering is required.

## 2026-03-12 Change 7 (Generalizable Spelling/Variant Expansion)

Files:

- `src/mesh/mesh_db.py`
- `src/mesh/__init__.py`
- `src/llm/query_generator.py`
- `src/pipeline/query_builder.py`
- `tests/test_query_builder.py`

What changed:

- Added a local MeSH descriptor DB loader that downloads and caches the official MeSH XML and exposes entry-term (synonym) lookups.
- Structured builder now adds a small number of MeSH entry-term synonyms as free-text terms for selected MeSH headings, improving recall without topic-specific hardcoding.
- Removed the hand-coded British ``-icectomy`` spelling variant from truncation rules; spelling variants now come from MeSH entry terms or the LLM extraction.

Reason:

- Replace the previous ad-hoc spelling/wildcard mapping with a generalizable, domain-wide synonym source that applies across all review topics.

Mistakes / Lessons:

- Hand-coded spelling variants quickly drift toward overfitting; prefer curated, domain-wide vocabularies (MeSH entry terms) for robust coverage.

## 2026-03-12 Change 8 (LLM-First Querying + Token-Guided Filtering)

Files:

- `src/llm/query_generator.py`
- `src/llm/openai_client.py`

What changed:

- Switched to LLM-first query composition (structured builder is now fallback).
- Added token-guided filtering of LLM queries to remove off-topic terms while keeping core concept coverage.
- Added conservative wildcard pruning for overly short stems (unless they match core tokens).
- Set LLM temperature to `0` for determinism and reduced run-to-run variability.
- Added modifier wildcarding for exposure phrases (e.g., preoperat* carbohydrate) and plural normalization in token matching.

Reason:

- The deterministic builder plateaued below human recall. LLM-first plus token filtering improved recall to human-level while keeping precision within a reasonable margin.
- Determinism reduces noise across runs and makes benchmarking reliable.

Mistakes / Lessons:

- Raw LLM output can introduce unrelated terms; filtering against core tokens is necessary.
- Overly aggressive filtering (or removing weak tokens entirely) can undercut recall; the filter must preserve core-concept stems.
- Token-based MeSH lookup by single tokens produced irrelevant headings; avoid naive substring-based expansion.
