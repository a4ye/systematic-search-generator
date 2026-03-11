"""Prompt templates for LLM interactions."""

BALANCED_QUERY_PROMPT = """You are a medical librarian creating a PubMed search strategy.

TARGET PERFORMANCE:
- Total results: 400-1,000 papers (optimal sweet spot)
- Recall: 90-95% of relevant studies
- Balance comprehensiveness with precision

RESEARCH QUESTION:
Attached as a PDF.

INSTRUCTIONS:

1. Extract PICO Elements

2. Generate Focused BUT Complete Term Lists

   For EACH element, include:
   - Primary MeSH terms (1-3)
   - Key medical synonyms (4-8)
   - Important spelling variants (2-4)
   - Related concepts (2-4)

   Typical range: 8-15 terms per facet

   INCLUDE essential variations but EXCLUDE overly broad terms:
   ✓ GOOD: "colorectal surgery"[tiab], "colectomy"[tiab], "colon resection"[tiab]
   ✗ TOO BROAD: "surgery"[tiab] alone (captures all surgery types)

3. Quality Checks
   - Have I included the main ways experts describe this concept?
   - Am I avoiding single terms that would retrieve 10,000+ papers?
   - Is each term medically relevant to the specific research question?

4. Build Query
   (Population terms) AND (Intervention terms)

EXAMPLE (GOOD BALANCE):
Research: Preoperative carbohydrate in colorectal surgery

Population (8 terms):
"Colectomy"[Mesh] OR "Colorectal Neoplasms"[Mesh] OR colectom*[tiab] OR hemicolectom*[tiab] OR "colorectal surgery"[tiab] OR "colon surgery"[tiab] OR "bowel resection"[tiab] OR "abdominal surgery"[tiab]

Intervention (9 terms):
"Carbohydrate Loading"[Mesh] OR "Dietary Carbohydrates"[Mesh] OR "preoperative carbohydrate"[tiab] OR "pre-operative carbohydrate"[tiab] OR "carbohydrate loading"[tiab] OR "oral carbohydrate"[tiab] OR maltodextrin[tiab] OR "CHO loading"[tiab] OR "carbohydrate drink"[tiab]

Result: ~400 results, 90% recall ✓

OUTPUT: Single-line PubMed query. Output ONLY the query string, nothing else."""


STRATEGY_EXTRACTION_PROMPT = """Extract the PubMed or MEDLINE search query from this systematic review search strategy document and convert it to PubMed syntax.

INSTRUCTIONS:
1. Look for a section labeled "PubMed", "MEDLINE", or "Ovid MEDLINE"
2. The search strategy may be in a table format with numbered lines - combine them into a single boolean query
3. Convert any line-by-line format into a proper boolean query:
   - Lines combined with AND should use AND between them
   - Lines combined with OR should use OR between them
4. If the strategy uses line numbers (e.g., "1 AND 2 AND 3"), resolve them to the actual terms

CRITICAL: Convert Ovid MEDLINE syntax to PubMed syntax:
- "exp Term/" → "Term"[Mesh]
- "term.mp." → term[tiab]
- "term.ti,ab." → term[tiab]
- "term.tw." → term[tw]
- "term.pt." → term[pt]
- "$" or "*" truncation → use * for truncation
- "adj2", "adj3" etc → remove (PubMed doesn't support adjacency)
- "limit to humans" or "NOT animals/" → add NOT (animals[Mesh] NOT humans[Mesh])

OUTPUT REQUIREMENTS:
- Output ONLY the final PubMed-compatible search query string
- The query must use PubMed syntax: [Mesh], [tiab], [tw], [pt], etc.
- The query should be on a single line
- Do not include explanations or comments
- If no PubMed/MEDLINE strategy is found, output exactly: NOT_FOUND

EXAMPLE INPUT (Ovid format):
1. exp Appendicitis/
2. appendectomy.mp.
3. 1 OR 2
4. exp Diet/
5. 3 AND 4

EXAMPLE OUTPUT:
("Appendicitis"[Mesh] OR appendectomy[tiab]) AND "Diet"[Mesh]"""
