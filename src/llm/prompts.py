"""Prompt templates for LLM interactions."""

import json
import re
from dataclasses import dataclass, field


@dataclass
class PICOElement:
    """A single PICO element with main concept and synonyms."""

    main: str
    synonyms: list[str] = field(default_factory=list)


@dataclass
class PICOExtraction:
    """Extracted PICO elements from a protocol."""

    population: PICOElement
    intervention: PICOElement
    comparator: PICOElement | None = None
    outcome: PICOElement | None = None


PICO_EXTRACTION_PROMPT = """You are an expert biomedical information specialist and systematic review librarian.

Your task is to extract the most retrieval-critical search concepts from a systematic review protocol for later conversion into a PubMed query.

Input:
A systematic review protocol or registration record.

Read the document carefully.

Extraction goal

Identify the strongest retrieval terms — the ones a medical librarian would actually put in a PubMed search strategy. Be selective: a good search has ~5-10 terms per concept block, not 30.

What to extract

core_concepts (2-4 terms per axis)

The minimum main concepts needed for retrieval:
- population / condition
- intervention / exposure

List only the 2-4 most specific, defining terms for each axis.

exact_phrases (3-6 per axis)

Exact search-relevant phrases from the protocol that could appear in titles or abstracts. Only phrases that are specific to the topic.

proxy_terms (1-4 per axis)

Only the strongest broader proxy terms:
- One level broader (e.g., "colorectal surgery" for colectomy, "appendectomy" for appendicitis)
- Do NOT go multiple levels up (e.g., do NOT include "abdominal surgery", "digestive system diseases", "intestinal surgery" for colectomy)
- For symptom/presentation reviews: include "diagnos*", "detect*" as proxies

spelling_variants (only when relevant)

British/American spelling variants of key terms:
- appendectomy / appendicectomy
- anemia / anaemia
- fiber / fibre
- tumor / tumour

controlled_vocabulary_terms (3-6 per axis)

MeSH terms for PubMed. Include:
- The most specific MeSH heading (e.g., "Colectomy")
- One broader parent MeSH if it plausibly indexes target studies (e.g., "Colorectal Surgery")
- For diet reviews: include "Diet" plus 2-3 most relevant sub-type MeSH (e.g., "Diet, Western", "Dietary Fiber")

Do NOT include very broad MeSH like "Digestive System Diseases", "Food", "Eating", "Risk Factors", "Surveys and Questionnaires", "Biomarkers", "Life Style" unless they are THE central topic.

strategy_terms (0-8 per axis)

If the protocol explicitly lists search terms or a draft search strategy, extract those terms and map them to the correct axis.
Only include terms that are clearly intended as search keywords or MeSH headings.
Do NOT include outcomes, study designs, or database names. Leave empty if no strategy is provided.

optional_terms

Terms from the protocol that should NOT be in the main PubMed query: outcomes, severity, biomarkers, questionnaires, study designs, microbiome terms.

Do NOT include very broad MeSH like "Digestive System Diseases", "Food", "Eating", "Risk Factors", "Surveys and Questionnaires", "Biomarkers", "Life Style" unless they are THE central topic.

NEVER include these demographic MeSH as standalone controlled_vocabulary_terms:
"Adult", "Young Adult", "Adolescent", "Child", "Aged", "Middle Aged", "Infant"
These match millions of papers and must only be used AND'd with a disease term in the query itself.

NEVER include "Signs and Symptoms" as a MeSH term — it is too broad (matches >1M papers). Use "Diagnosis" or specific symptom MeSH instead.

Rules

Keep all lists SHORT — a good PubMed query has ~5-10 terms per concept block total
Do not include broad semantic relatives (food, nutrition, eating, lifestyle) unless they are a core concept
Do not include study designs, outcomes, or assessment tools
Include British/American spelling variants when they exist

wildcard_terms (0-4 per axis)

Provide wildcard stems only when there is a strong morphological family.
Examples: colectom*, resect*, operat*.
Do NOT create overly broad stems (avoid 2-3 letter stems).
Wildcard terms must be single tokens ending with * (no spaces).

Output format

Return only valid JSON:

{
"review_title": "",
"research_objective": "",
"core_concepts": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"exact_phrases": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"proxy_terms": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"spelling_variants": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"wildcard_terms": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"controlled_vocabulary_terms": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"strategy_terms": {
"population_or_condition": [],
"intervention_or_exposure": []
},
"optional_terms": [],
"notes_for_query_builder": ""
}

Rules:

JSON only

no markdown

no explanations
"""


QUERY_PROMPT_TEMPLATE = """You are an expert biomedical information specialist and systematic review librarian.

Your task is to convert structured search concepts into a human-like PubMed search query.

Input:
Structured JSON extracted from a systematic review protocol.

{extracted_review_json}

Goal:
Produce a PubMed query that resembles a compact human strategy, prioritizing:

exact concept matching

MeSH terms

lexical variants

a few strong proxy terms

Do not try to be semantically comprehensive.

Allowed inputs

Use only:

core_concepts

exact_phrases

proxy_terms

controlled_vocabulary_terms

Do not use:

optional_terms

notes_for_query_builder as direct terms

Query construction rules
1. Build exactly two main blocks

population / condition

intervention / exposure

2. Prioritize term types in this order

MeSH terms

exact core concepts

exact protocol phrases

a very small number of strong proxy terms

3. Prefer lexical variants, not semantic relatives

Good:

colectom*[tiab]

appendectom*[tiab]

oral carbohydrate[tiab]

Bad unless explicitly listed and clearly central:

nutrition[tiab]

food[tiab]

drinking[MeSH]

enhanced recovery[tiab]

acute abdomen[tiab]

4. Do not add conceptually related broad terms unless they are likely standard human search terms

Examples of broad but acceptable terms when clearly relevant:

"Preoperative Care"[MeSH]

"Dietary Carbohydrates"[MeSH]

"Colorectal Surgery"[MeSH]

"Appendectomy"[MeSH]

5. Do not add weak broad terms

Avoid terms like:

food

nutrition

nutrients

eating

drinking

smoking

alcohol
unless they are explicit core concepts of the review.

6. Use field tags

MeSH terms: [MeSH]

free text: [tiab]

Do not output bare words without field tags.

7. Use truncation selectively

Use truncation only for strong lexical stems, such as:

colectom*

appendectom*

preoperat* carbohydrate

8. Do not add

outcomes

severity terms unless central

questionnaires

biomarkers

microbiome terms

date limits

language limits

publication type exclusions

You may add:
NOT (animals[MeSH] NOT humans[MeSH])

Final pruning rule

Before outputting the query, remove any term that is:

broader than the target concept and not a standard human search term

semantically related but not a lexical or indexing variant

likely to add substantial noise without obvious recall benefit

Output rules

Return exactly one single-line PubMed query.

No explanations.
No markdown.
No labels.
No JSON.
No code blocks.
No surrounding quotes.
No commentary."""


MESH_AUGMENT_PROMPT = """You are an expert biomedical librarian.

Your task is to propose a SMALL number of additional MeSH headings that are
one level broader or narrower than the core concepts, to improve recall.

Inputs:
Extracted concepts JSON from a protocol and a list of seed-paper MeSH terms.

Rules:
- Add at most 3 MeSH terms per axis.
- Only include terms that are clearly relevant to the core concepts.
- Do NOT include very broad terms (e.g., Humans, Adult, Risk Factors, Surveys and Questionnaires).
- If no additions are appropriate, return empty lists.

Extracted JSON:
{extracted_json}

Seed-paper MeSH terms:
{seed_mesh}

Return only valid JSON with this shape:
{{
  "population_or_condition": [],
  "intervention_or_exposure": []
}}
"""


def build_query_from_extracted_json_prompt(extracted_json: dict) -> str:
    """Build a query generation prompt from extracted protocol JSON."""
    payload = json.dumps(extracted_json, ensure_ascii=False, indent=2)
    return QUERY_PROMPT_TEMPLATE.replace("{extracted_review_json}", payload)


def parse_pico_response(response: str) -> PICOExtraction:
    """Parse LLM response into structured PICO extraction."""
    text = response.strip()

    # Prefer JSON parsing for the current extraction prompt output format.
    parsed: dict | None = None
    json_text = text
    if json_text.startswith("```"):
        json_text = re.sub(r"^```(?:json)?\s*", "", json_text)
        json_text = re.sub(r"\s*```$", "", json_text)
    try:
        maybe_dict = json.loads(json_text)
        if isinstance(maybe_dict, dict):
            parsed = maybe_dict
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None:
        def get_list(key: str) -> list[str]:
            value = parsed.get(key, [])
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        def merge_unique(*items: list[str]) -> list[str]:
            seen = set()
            merged = []
            for group in items:
                for item in group:
                    key = item.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(item)
            return merged

        population_terms = get_list("population")
        population_synonyms = merge_unique(
            population_terms[1:],
            get_list("population_synonyms"),
            get_list("conditions_or_diseases"),
        )

        intervention_terms = get_list("intervention_or_exposure")
        intervention_synonyms = merge_unique(
            intervention_terms[1:],
            get_list("intervention_synonyms"),
            get_list("procedures_or_settings"),
        )

        comparator_terms = get_list("comparator")
        comparator_synonyms = merge_unique(
            comparator_terms[1:],
            get_list("comparator_synonyms"),
        )

        outcome_terms = get_list("outcomes")
        outcome_synonyms = outcome_terms[1:] if len(outcome_terms) > 1 else []

        population = PICOElement(
            main=population_terms[0] if population_terms else "",
            synonyms=population_synonyms,
        )
        intervention = PICOElement(
            main=intervention_terms[0] if intervention_terms else "",
            synonyms=intervention_synonyms,
        )

        comparator = None
        if comparator_terms and comparator_terms[0].lower() not in ("not applicable", "n/a", "none", ""):
            comparator = PICOElement(main=comparator_terms[0], synonyms=comparator_synonyms)

        outcome = None
        if outcome_terms and outcome_terms[0].lower() not in ("not applicable", "n/a", "none", ""):
            outcome = PICOElement(main=outcome_terms[0], synonyms=outcome_synonyms)

        return PICOExtraction(
            population=population,
            intervention=intervention,
            comparator=comparator,
            outcome=outcome,
        )

    lines = text.split("\n")

    elements = {}
    for line in lines:
        line = line.strip()
        if not line or "|" not in line:
            continue

        # Parse "Element: main | syn1, syn2, syn3"
        if ":" not in line:
            continue

        element_name, rest = line.split(":", 1)
        element_name = element_name.strip().lower()

        if "|" in rest:
            main_part, synonyms_part = rest.split("|", 1)
            main = main_part.strip()
            synonyms = [s.strip() for s in synonyms_part.split(",") if s.strip()]
        else:
            main = rest.strip()
            synonyms = []

        # Normalize element names
        if element_name in ("population", "population/condition", "condition"):
            elements["population"] = PICOElement(main=main, synonyms=synonyms)
        elif element_name in ("intervention", "intervention/exposure", "exposure"):
            elements["intervention"] = PICOElement(main=main, synonyms=synonyms)
        elif element_name in ("comparator", "comparison", "control"):
            if main.lower() not in ("not applicable", "n/a", "none", ""):
                elements["comparator"] = PICOElement(main=main, synonyms=synonyms)
        elif element_name in ("outcome", "outcomes"):
            if main.lower() not in ("not applicable", "n/a", "none", ""):
                elements["outcome"] = PICOElement(main=main, synonyms=synonyms)

    # Ensure required elements exist
    if "population" not in elements:
        elements["population"] = PICOElement(main="", synonyms=[])
    if "intervention" not in elements:
        elements["intervention"] = PICOElement(main="", synonyms=[])

    return PICOExtraction(
        population=elements["population"],
        intervention=elements["intervention"],
        comparator=elements.get("comparator"),
        outcome=elements.get("outcome"),
    )


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
