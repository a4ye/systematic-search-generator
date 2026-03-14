# Ideas for Improving Recall

## 1. Forward/backward citation searching (highest impact)

Completely sidesteps the vocabulary gap problem. For each seed paper:
- **Backward** (references): papers the seed paper cites
- **Forward** (cited-by): papers that cite the seed paper

Final result: `boolean_query_pmids ∪ citation_pmids`

### Implementation options

- **PubMed elink API**: `Entrez.elink(dbfrom="pubmed", id=pmid, linkname="pubmed_pubmed_citedin")` for forward, `pubmed_pubmed_refs` for backward
- **OpenAlex API**: free, richer citation data, no rate limit issues. `GET https://api.openalex.org/works/pmid:{pmid}` returns `referenced_works` and `cited_by_api_url`

### Why it helps

The main recall failures are papers that use different vocabulary (e.g., "abdominal surgery" instead of "colectomy", clinicopathological comparison studies instead of "signs and symptoms"). Citation links connect these papers regardless of terminology.

### Considerations

- Citation depth: 1 hop is probably sufficient; 2 hops would explode the result set
- Can be cached aggressively since citation data changes slowly
- Co-founder confirmed seed papers are always available as input

## 2. Two-pass query refinement

Run the initial query, check which seed papers it misses, then generate a targeted supplementary query for the gaps.

1. Generate query from protocol
2. Run query against PubMed
3. Check which seed papers are NOT in the results
4. Feed missed seed papers back to the LLM: "These known relevant papers were not captured by your query. Generate a supplementary query that would capture them."
5. Union the results

### Why it helps

Directly addresses vocabulary gaps by using concrete feedback rather than hoping the LLM anticipates all terminology variations upfront.

## 3. PubMed "Similar Articles"

PubMed's related articles algorithm (`Entrez.elink` with `linkname="pubmed_pubmed"`) returns papers with similar content regardless of search terms.

For each seed paper, fetch the top N similar articles and union with query results.

### Considerations

- Returns up to 500 similar articles per paper — can be noisy
- Quality of matches varies; may need filtering by relevance score

## 4. Relaxed 2-block fallback queries

When the LLM generates a 3-block query (e.g., CRC AND young-onset AND symptoms), also run a 2-block version dropping the most restrictive block, and union the results.

This was observed empirically: when n=5 produced a mix of 2-block and 3-block queries, the 2-block variants captured papers the 3-block ones missed.

### Implementation

- Could be prompt-driven: "Generate both a high-precision 3-block query and a high-sensitivity 2-block query"
- Or mechanical: parse the generated query, remove the smallest/most specific AND block, run both

## 5. Prompt engineering observations

### What worked
- Instruction to include broader parent terms (instruction 3) helped for vocabulary gaps like "colectomy" → "abdominal surgery"
- Seed papers in the prompt (instruction 11) helped guide term selection

### What didn't work
- Changing instruction 6 to allow broad terms like `diagnos*`, `risk*` caused the LLM to always generate 3-block queries with those terms, making results more restrictive overall (study 110 recall dropped from 86% to 64%)
- Changing instruction 10 to encourage age threshold phrases had a similar over-constraining effect

### Lesson
Prompt changes that add information to concept blocks can help, but prompt changes that encourage adding entire new concept blocks tend to hurt recall by over-filtering.
