# Ideas to Boost Recall Without Changing Random Seeds

These ideas avoid information leakage and do not require non-random seed selection.

1. Add non-PubMed retrieval (Embase, Scopus, Web of Science, Europe PMC, OpenAlex/Crossref) and union results to fix cases where included studies are not indexed in PubMed.
2. Add block-drop supplemental queries (e.g., `Condition AND Age`, `Condition AND Symptoms`) with strict result caps and tighter fields like `[ti]` or `[majr]` to prevent precision collapse.
3. Use pseudo-relevance feedback from the initial PubMed result set (not from included studies) with aggressive filtering and hard result caps to limit topic drift.
4. Expand beyond MeSH entry terms using Supplementary Concept Records and UMLS synonyms, gated by co-occurrence with core concept terms and a max-results threshold.
5. Run PubMed Similar Articles not only on seeds but also on a small, high-confidence sample of initial hits, with a tight per-paper cap.
