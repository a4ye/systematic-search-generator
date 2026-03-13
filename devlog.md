# Development Log: LLM-Generated PubMed Search Queries

## Goal

Generate PubMed search queries using LLMs that achieve high recall (90%+) while maintaining reasonable precision.
Compare against human-crafted search strategies.

## Methodology

- Input: PROSPERO systematic review protocol (PDF)
- Output: PubMed boolean search query
- Evaluation: `compare_search.py` compares search results against included studies

```bash
uv run python src/compare_search.py pubmed-queries/query.txt "data/34 - Lu 2022/Included Studies.xlsx"
```

---

## Experiment 1: Lu 2022 (Preoperative carbohydrate in colorectal surgery)

### Iteration 1: Naive Prompt

**Prompt:**

```
Generate a PubMed search query for this systematic review
```

| Metric  | Value        |
|---------|--------------|
| Results | 16           |
| Recall  | 33.3% (4/12) |

**Analysis:** Query too narrow. Missing synonyms, limited MeSH coverage, study design filter too restrictive.

### Iteration 2: Structured PICO Prompt

**Prompt:**

```
You are an expert medical librarian. Create a PubMed search strategy.

Step 1: Analyze the research question
The PROSPERO PDF is attached to this prompt.

Step 2: Extract PICO elements
- Population:
- Intervention:
- Comparison:
- Outcome:

Step 3: For EACH element, generate:
- Primary term
- 5-10 synonyms
- Abbreviations/acronyms
- Plural/singular variants
- British/American spelling

Step 4: Identify MeSH terms for each concept

Step 5: Build faceted query:
(population terms) AND (intervention terms) [AND (outcome terms)]

Output your final query in PubMed syntax.
```

| Metric                  | Value        |
|-------------------------|--------------|
| Results                 | 168          |
| Recall (overall)        | 58.3% (7/12) |
| Recall (PubMed-indexed) | 70.0% (7/10) |
| Precision               | 4.2%         |

**Analysis:** Better recall, but still missing studies. Added script feature to show metadata for missed studies to
identify patterns.

### Iteration 3: Comprehensive High-Recall Prompt

**Prompt:**

```
You are an expert medical librarian creating a comprehensive PubMed search strategy for a systematic review. Your goal is HIGH RECALL (capture 90%+ of relevant studies) while maintaining reasonable precision.

CONTEXT:
The attached PROSPERO document describes a systematic review protocol.

TASK:
Create a faceted boolean search query using PubMed syntax.

STEP 1: Extract PICO Elements
Carefully read the PROSPERO and identify:
- Population: Who are the patients/subjects?
- Intervention: What is being tested/given?
- Comparison: What is it compared to? (if applicable)
- Outcome: What are the measured results?

STEP 2: Generate COMPREHENSIVE Term Lists
For EACH PICO element, brainstorm exhaustively:

a) Primary medical terms (be specific)
b) Synonyms and related concepts (think broadly - what else might authors call this?)
c) Abbreviations and acronyms (both spelled out and abbreviated)
d) Variant spellings:
   - British vs American (e.g., "anaesthesia" vs "anesthesia")
   - Hyphenated vs non-hyphenated (e.g., "pre-operative" vs "preoperative")
   - Spacing variants (e.g., "health care" vs "healthcare")
e) Plural and singular forms
f) Related procedures or conditions
g) Lay terms that might appear in titles/abstracts

CRITICAL: Be MORE comprehensive, not less. Missing a key synonym can exclude important studies.

STEP 3: Identify MeSH Terms
For each major concept, identify relevant MeSH (Medical Subject Headings):
- Use the official MeSH browser if needed
- Include both specific and broader MeSH terms
- Consider MeSH subheadings where appropriate
- Example: For surgery, include both "Colectomy"[Mesh] AND broader "Digestive System Surgical Procedures"[Mesh]

STEP 4: Add Wildcards and Field Tags
- Use asterisk (*) for truncation: "colectom*" catches "colectomy", "colectomies"
- Use [tiab] for title/abstract searches: "preoperative"[tiab]
- Use [Mesh] for MeSH terms: "Colectomy"[Mesh]
- Use quotes for phrases: "oral carbohydrate"[tiab]

STEP 5: Build Faceted Query
Structure: (Population) AND (Intervention) [AND (Outcome if specific)]

For EACH facet, combine terms with OR:
- Include BOTH MeSH terms AND text words (belt-and-suspenders approach)
- MeSH catches well-indexed papers; text words catch recent/pre-indexed papers
- Be generous with ORs within each facet to maximize recall

Format as single line, example structure:
("Term1"[Mesh] OR "Term2"[Mesh] OR term1*[tiab] OR "term variant"[tiab] OR synonym*[tiab]) AND ("Intervention1"[Mesh] OR intervention*[tiab] OR "alt name"[tiab])

QUALITY CHECKS:
Before finalizing, ask yourself:
1. Have I included obvious synonyms a clinician might use?
2. Have I covered both formal medical terms AND common variations?
3. Am I being comprehensive enough to catch 90%+ of relevant studies?
4. Have I included broader terms (e.g., "abdominal surgery" not just "colorectal surgery")?
5. Are my wildcards positioned correctly?

OUTPUT FORMAT:
Provide your query as a single-line PubMed-compatible search string, properly formatted with field tags and boolean operators.
```

| Metric                  | Value        |
|-------------------------|--------------|
| Results                 | 410          |
| Recall (overall)        | 75.0% (9/12) |
| Recall (PubMed-indexed) | 90.0% (9/10) |
| Precision               | 2.2%         |
| NNR                     | 45.6         |

**Analysis:** Significant improvement. Human strategies for this review returned 4000+ results, so 410 is efficient.

---

## Experiment 2: Model Comparison (Claude vs ChatGPT)

Using the comprehensive prompt (Iteration 3) on Claude produced a much longer query with excessive term variations.

| Model   | Results | Notes               |
|---------|---------|---------------------|
| ChatGPT | 410     | Balanced output     |
| Claude  | 18,692  | Excessively verbose |

**Conclusion:** Claude's tendency toward comprehensive output hurts precision. Requires explicit constraints.

### Constrained Claude Prompt

**Prompt:**

```
You are a medical librarian creating a PubMed search.

HARD REQUIREMENTS:
- Target total results: 500-1,000 papers
- Each PICO facet: 6-10 terms maximum (count them!)
- Recall target: 90-95% (not 100%)
- Avoid overly general terms that retrieve 10,000+ papers alone

STEP 1: Extract PICO
[your existing PICO extraction]

STEP 2: Generate Term Lists
For EACH element, generate EXACTLY 6-10 terms:
- 1-2 MeSH terms
- 3-5 key synonyms
- 1-2 spelling variants
- 1-2 related concepts

STOP at 10 terms. More is not better if they're too general.

FORBIDDEN TERMS (too broad):
- "surgery"[tiab] alone (use specific surgery types)
- "diet"[tiab] alone (use specific diet types)
- "treatment"[tiab] alone (use specific treatments)

GOOD EXAMPLE (Appendicitis population):
1. "Appendicitis"[Mesh]
2. Appendicitis[tiab]
3. "Appendectomy"[Mesh]
4. Appendectom*[tiab]
5. Appendicectomy[tiab]
6. Appendicectom*[tiab]
TOTAL: 6 terms ✓ STOP HERE

BAD EXAMPLE (too many/too broad):
1. "Surgery"[Mesh]  ← TOO BROAD
2. surgery[tiab]  ← TOO BROAD
3. "Appendicitis"[Mesh]
4. Appendicitis[tiab]
5. "Appendectomy"[Mesh]
... [continues for 15 terms] ← TOO MANY

STEP 3: Build Query
Format: (Population terms 1-10) AND (Intervention terms 1-10)

OUTPUT:
Single-line PubMed query. NO MORE than 10 terms per facet.
```

| Metric                  | Value |
|-------------------------|-------|
| Results                 | 54    |
| Recall (PubMed-indexed) | 50.0% |
| Precision               | 9.3%  |

**Analysis:** Over-constrained. High precision but unacceptable recall.

### Balanced Claude Prompt

**Prompt:**

```
You are a medical librarian creating a PubMed search strategy.

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

OUTPUT: Single-line PubMed query
```

| Metric                  | Value |
|-------------------------|-------|
| Results                 | 190   |
| Recall (overall)        | 66.7% |
| Recall (PubMed-indexed) | 80.0% |
| Precision               | 4.2%  |

---

## Experiment 3: Pitesa 2025 (Appendicitis and dietary fiber)

Testing generalizability on a different systematic review using the balanced prompt.

### LLM-Generated Query

| Metric                  | Value         |
|-------------------------|---------------|
| Results                 | 613           |
| Recall (overall)        | 77.8% (14/18) |
| Recall (PubMed-indexed) | 87.5% (14/16) |
| Precision               | 2.3%          |
| NNR                     | 43.8          |

### Human Strategy Comparison

| Strategy | Results | Recall (PubMed) | Precision | NNR  |
|----------|---------|-----------------|-----------|------|
| Human    | 277     | 81.2% (13/16)   | 4.7%      | 21.3 |
| LLM      | 613     | 87.5% (14/16)   | 2.3%      | 43.8 |

**Analysis:** LLM achieves higher recall (+6.3%) but lower precision. Returns ~2x more results.

---

## Key Findings

1. **Prompt structure matters:** PICO extraction + MeSH terms + synonym generation significantly improves recall over
   naive prompts
2. **Model choice matters:** Claude's verbosity hurts precision without explicit constraints; ChatGPT produces more
   balanced queries by default
3. **Recall-precision trade-off:** Achieving 90% recall requires accepting lower precision (more screening burden)
4. **Competitive with humans:** LLM queries can match or exceed human recall while returning fewer total results than
   many human strategies

I will now built an automated testing pipeline to systematically evaluate different prompt strategies and models across
a larger set of systematic reviews. I am currently doing it manually to understand the nuances, but it is too
time-consuming to do at scale.

I made a script to download infomration included studies from all of the training data in order to use them as seed
papers. A
select random number of seed papers will be used in the workflow.

════════════════════════════════════════════════════════════
AGGREGATE COMPARISON (10 studies)
════════════════════════════════════════════════════════════
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Metric ┃ LLM ┃ Human ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ Mean Recall (PubMed) │ 83.6% │ 92.2% │
│ Mean Precision │ 2.26% │ 8.01% │
└──────────────────────┴───────┴───────┘

Results did not improve by much, and there is still decent amount of variance. Will run again since seed papers are
selected randomly.

Instead of one shotting the query, I will now try a multi step process where first:
1. the llm generates pico from the prospero
2. it does mesh expansion
3. and then refines the query using  the seed papers

more ideas:
- vector embeddinds / semantics of terms
- maybe find most similar terms to the seed papers and make sure they are included in the query
- may need to manually populate a vector db

- cache human pubmed queries *IMPORTANT* TODO

- look at actual content and determine if it matches the prospero
- -> if not determine why and improve the query iteratively
- perhaps it might be possible to do it using only the title, abstraact and not the full text of the paper, which would be more realistic and also more scalable
- prompting techniques such as adding info in the beginning and end of the prompt, or using a chain of thought prompting to make the llm reason step by step
- citation expansion
- use pubmed api to find papers similar to the seed papers (it is already built into the api) and use as additional seed papers, or to make sure they are included in the query
- using hedges (medical libarians use them)

- new idea: multiple narrow queries and then merge the results, instead of one broad query, which might improve precision while maintaining recall


## Next Steps

- Use seed papers to better mimic the human search development workflow
- Multi-prompt iterative approach with algorithmic refinement
- Add support for non-PubMed databases (Embase, Cochrane)
