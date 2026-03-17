"""Prompt templates for LLM interactions."""

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
