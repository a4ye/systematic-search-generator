#!/usr/bin/env python3
"""
Extract key search-strategy findings from a PROSPERO PDF using OpenAI.

Usage:
    uv run src/scripts/extract_prospero_findings.py /path/to/prospero.pdf
    uv run src/scripts/extract_prospero_findings.py /path/to/prospero.pdf --output findings.md
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make local `src` package importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.openai_client import OpenAIClient

DEFAULT_MODEL = "gpt-5.4"

PROSPERO_FINDINGS_PROMPT = """You are an expert systematic review methodologist and biomedical information specialist trained in literature search strategy development.

Your task is to extract the key research and search concepts from a systematic review protocol so they can be used to generate high-recall database search queries (e.g., PubMed, MEDLINE, Embase, Cochrane).

Input:
A systematic review protocol, review plan, grant proposal, thesis proposal, or registration record (e.g., PROSPERO).

Goal:
Identify all important terminology that should be used to construct a literature search strategy.

Instructions

Carefully read the entire document.

Extract the core research question elements using the PICOS framework whenever possible:

Population / condition
Intervention or exposure
Comparator (if present)
Outcomes (if present)
Study designs

Also extract additional search-relevant terminology, even if it appears only once in the document.

Include:

synonyms explicitly mentioned

abbreviations

keywords

named interventions, drugs, procedures, technologies, or exposures

diseases or conditions

surgical or procedural settings

controlled vocabulary terms (e.g., MeSH) if listed

terminology that commonly appears in literature describing the same concept

If a protocol contains multiple terms describing the same concept, include all of them.

Normalize phrases into concise search-friendly terms, but also preserve the original wording used in the protocol.

You may infer closely related synonyms when strongly implied by the terminology in the document, but do not invent unrelated concepts or hallucinate domain knowledge.

Concept Identification

Determine which concepts should form the core search blocks of a database query.

Usually this will include:

Population / condition
Intervention or exposure

Sometimes it may also include:

Procedure / setting
Study design

Avoid treating outcomes or comparators as core search concepts unless they define the research topic.

Information to Ignore

Do not extract administrative or logistical information such as:

authors
affiliations
funding sources
timeline details
contact information
submission metadata

Extraction Rules

If a category is not present in the document, return an empty array.

Keep extracted phrases:

concise

search-friendly

suitable for use in database queries

Avoid full sentences.

Output Format

Return only valid JSON in the following format.

Do not include explanations or text outside the JSON.

{
"review_title": "",
"research_objective": "",

"core_search_concepts": [],

"population": [],
"population_synonyms": [],
"population_context": [],

"intervention_or_exposure": [],
"intervention_synonyms": [],
"exposure_modifiers": [],

"comparator": [],
"comparator_synonyms": [],

"outcomes": [],
"outcomes_required_for_topic_definition": false,

"study_designs": [],

"conditions_or_diseases": [],
"procedures_or_settings": [],

"keywords_from_protocol": [],
"controlled_vocabulary_terms": [],

"raw_terms_from_protocol": [],

"databases_mentioned": [],

"notes_for_search_strategy": ""
}

Output Rules

Return only JSON.

Do not include markdown.

Do not include code blocks.

Do not include explanations.

Do not include text before or after the JSON.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract key findings from a PROSPERO PDF for search-strategy design."
    )
    parser.add_argument("pdf", type=Path, help="Path to PROSPERO PDF")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Optional max tokens for the LLM response",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path (Markdown)",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    if not args.pdf.exists():
        print(f"Error: File not found: {args.pdf}", file=sys.stderr)
        return 1
    if args.pdf.suffix.lower() != ".pdf":
        print("Error: Input file must be a PDF.", file=sys.stderr)
        return 1

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    client = OpenAIClient(api_key=api_key, model=args.model)

    try:
        response = client.generate_with_file(
            prompt=PROSPERO_FINDINGS_PROMPT,
            file_path=args.pdf,
            max_tokens=args.max_tokens,
        )
    except Exception as exc:
        print(f"Error calling OpenAI API: {exc}", file=sys.stderr)
        return 1

    output = response.content.strip()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote findings to: {args.output}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
