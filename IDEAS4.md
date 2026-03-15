Here are the viable ideas, ranked by expected impact on PubMed-only recall, all leakage-free:

1. **Second-round similar articles on augmentation hits** — Your `--similar` currently runs only on seed PMIDs. After citations/two-pass add new PMIDs to the result set, run similar articles again on a small sample of those newly-added PMIDs (e.g., top 10 by relevance score). These are papers the *query* found, not included studies, so no leakage. Catches papers in adjacent vocabulary neighborhoods that the original seeds didn't reach.

2. **Citation depth 2 with frontier cap** — Go one more hop in the citation graph from seed papers. Cap the frontier (e.g., only follow the top 50 most-cited intermediate papers) to avoid explosion. Old/niche papers like the 1986 appendicitis paper in study 92 are more likely reachable at depth 2. Uses only seed papers as starting points.

3. **Relaxed block-drop variant ([tiab] → [tw])** — Instead of dropping a whole AND block, generate a variant where one block's free-text terms switch from `[tiab]` to `[tw]` (which also searches MeSH terms, keywords, and other fields). This catches papers where the concept appears in indexing but not in the title/abstract. Low risk of blowup since the AND structure is preserved. Complements your existing `--block-drop`.

4. **MeSH tree-parent expansion** — For each MeSH term in the generated query, look up its parent in the MeSH hierarchy and OR it in. You already parse MeSH XML. This catches papers indexed under sibling headings the LLM didn't think of. Gate it with a result-count check to avoid blowup.

5. **Pseudo-relevance feedback from initial result set** — Take the top N PMIDs from your initial search results (by PubMed's default relevance ranking), fetch their MeSH terms/keywords, identify terms that appear frequently in those results but aren't in the original query, and add them as an OR-expanded supplementary query. This is standard IR technique (Rocchio-style), uses only the search output, no included studies.

6. **Title-only TF-IDF variant** — Your `--tfidf` uses title+abstract from seed papers. A separate title-only pass would produce more specific terms (title words are higher signal). Generate a supplementary `(term1[ti] OR term2[ti] OR ...) AND main_concept` query with a result cap. Narrower than abstract-based TF-IDF but more targeted.

Ideas 1-3 are the most likely to recover specific misses you're seeing. Ideas 4-6 are more speculative but sound in principle.