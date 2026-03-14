 # Recall-Boosting Techniques (Beyond Prompting)

## Techniques Not Yet in the Pipeline
- **MeSH entry-term expansion (systematic)**  
  For each MeSH term, add all entry terms/synonyms as `[tiab]` variants. This is more complete than ad‑hoc synonym lists.

- **MeSH tree neighborhood expansion (bounded)**  
  Add immediate parents/children in the MeSH hierarchy (bounded depth), then filter by term frequency in included studies to avoid blow‑ups.

- **TF‑IDF term mining from included studies**  
  Extract discriminative terms from titles/abstracts of included studies (or seed papers) and add the top‑K terms as an extra OR block.

- **Tiered, bounded queries**  
  Run 2–3 narrower query variants (different concept slices), cap each at <20k, then union results to stay under 50k.

- **Adaptive term‑dropping with guardrails**  
  If a query is too narrow, drop the weakest concept block or terms stepwise until recall improves, while keeping results under the cap.

- **Field‑targeted fallback**  
  Use `[tiab]` for the main query, then run a small supplemental query using `[tw]` or `[all fields]` for a tight set of high‑signal terms.

- **Journal/title channel**  
  Add a supplemental query restricted to high‑yield journals or title‑only hits for specific terms as a high‑precision add‑on.
