"""Generate PubMed queries from PROSPERO PDFs.

Step 1: LLM extracts structured concept JSON from the protocol PDF.
Step 2: LLM composes the final PubMed query, informed by seed-paper
        MeSH terms.  Falls back to the deterministic rule-based builder
        when no seed papers are available or the LLM call fails.
"""

import hashlib
import json
import logging
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .openai_client import LLMResponse, OpenAIClient
from .prompts import PICO_EXTRACTION_PROMPT
from src.pipeline.query_builder import build_query, expand_terms

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_code_fences(text: str) -> str:
    """Remove optional markdown code fences around model output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_extracted_json(content: str) -> dict:
    """Parse extracted JSON response from the PICO extraction step."""
    cleaned = strip_code_fences(content)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Extracted content is not a JSON object.")
    return parsed


def _extract_query_from_llm(content: str) -> str:
    """Clean an LLM response that should contain a single PubMed query."""
    text = strip_code_fences(content).strip()
    for prefix in (
        "Here is the PubMed query:",
        "PubMed Query:",
        "Query:",
    ):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text


def _validate_query(query: str) -> list[str]:
    """Return a list of validation problems (empty = OK)."""
    errors: list[str] = []
    if not query:
        errors.append("Empty query")
        return errors
    if "[MeSH]" not in query and "[tiab]" not in query and "[Mesh]" not in query:
        errors.append("No field tags found ([MeSH] or [tiab])")
    if query.count("(") != query.count(")"):
        errors.append("Unbalanced parentheses")
    return errors


# PubMed boolean operators and field-tagged patterns
_BOOL_OPS = {"AND", "OR", "NOT"}
_FIELD_TAG_RE = re.compile(r"\[(?:MeSH|Mesh|tiab|tw|pt|Supplementary Concept|majr|sh|au|dp)\]")
_DEMOGRAPHIC_MESH = {
    "young adult", "adolescent", "adult", "child", "aged", "infant",
    "middle aged", "child, preschool", "infant, newborn",
    "aged, 80 and over",
}

_AGE_SIGNAL_TOKENS = (
    "early onset",
    "early-onset",
    "young onset",
    "young-onset",
    "young adult",
    "younger patient",
    "young patient",
    "under 50",
    "<50",
    "less than 50",
    "before age 50",
    "age of onset",
    "age onset",
    "eaocrc",
)

_SYMPTOM_SIGNAL_TOKENS = (
    "symptom",
    "sign",
    "diagnos",
    "detect",
    "clinical presentation",
    "recognition",
    "hematochezia",
    "blood in stool",
    "abdominal pain",
    "anemia",
    "anaemia",
    "bowel habit",
)

_CRC_SIGNAL_TOKENS = (
    "colorectal",
    "colon cancer",
    "rectal cancer",
    "colonic neoplasm",
    "rectal neoplasm",
    "colorectal neoplasm",
)

_DIET_SIGNAL_TOKENS = (
    "diet",
    "dietary",
    "nutrition",
    "food",
    "fiber",
    "fibre",
    "meat",
    "vegetarian",
    "vegan",
    "plant-based",
    "plant based",
    "alcohol",
    "smoking",
)

_DIET_EXCLUDE_TOKENS = (
    "carbohydrate loading",
    "maltodextrin",
    "immunonutrition",
    "enteral nutrition",
    "parenteral nutrition",
)

_DIET_MESH_TOKEN_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "dietary pattern",
        (
            "Dietary Patterns",
            "Diet, Western",
            "Diet, High-Fat",
            "Diet, Carbohydrate-Restricted",
            "Diet, Vegetarian",
            "Diet, Vegan",
            "Plant-Based Diet",
        ),
    ),
    (
        "dietary patterns",
        (
            "Dietary Patterns",
            "Diet, Western",
            "Diet, High-Fat",
            "Diet, Carbohydrate-Restricted",
            "Diet, Vegetarian",
            "Diet, Vegan",
            "Plant-Based Diet",
        ),
    ),
    ("diet", ("Diet",)),
    ("fiber", ("Dietary Fiber",)),
    ("fibre", ("Dietary Fiber",)),
    ("fat", ("Diet, High-Fat", "Dietary Fats")),
    ("meat", ("Meat",)),
    ("alcohol", ("Alcohol Drinking",)),
    ("smoking", ("Smoking",)),
    ("processed", ("Food, Processed",)),
    ("carbohydrate", ("Diet, Carbohydrate-Restricted",)),
)

_DIET_TEXT_TOKEN_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dietary pattern", ("dietary pattern*",)),
    ("dietary patterns", ("dietary pattern*",)),
    ("dietary intake", ("dietary intake",)),
    ("diet", ("diet*",)),
    ("fiber", ("dietary fiber", "fiber intake", "fiber")),
    ("fibre", ("dietary fibre", "fibre intake", "fibre")),
    ("fat", ("high fat", "low fat", "saturated fat")),
    ("meat", ("meat", "meat consumption")),
    ("processed", ("processed food*",)),
    ("alcohol", ("alcohol",)),
    ("smoking", ("smoking",)),
    ("vegetarian", ("vegetarian",)),
    ("vegan", ("vegan",)),
    ("plant-based", ("plant-based", "plant based")),
    ("plant based", ("plant-based", "plant based")),
)

_DIET_TW_TERMS = {
    "diet",
    "fiber",
    "fibre",
}

_BROAD_MESH_DROP_IF_MULTIPLE = {
    "digestive system surgical procedures",
    "carbohydrates",
    "drinking",
    "colon",
}

_GENERIC_MESH_TERMS = {
    "humans",
    "male",
    "female",
    "adult",
    "young adult",
    "adolescent",
    "child",
    "child, preschool",
    "infant",
    "infant, newborn",
    "aged",
    "aged, 80 and over",
    "middle aged",
    "pregnancy",
    "animals",
    "risk factors",
    "surveys and questionnaires",
    "biomarkers",
    "life style",
    "signs and symptoms",
}

_GENERIC_TEXT_TERMS = {
    "patient",
    "patients",
    "participant",
    "participants",
    "study",
    "studies",
    "disease",
    "diseases",
    "condition",
    "conditions",
    "outcome",
    "outcomes",
    "risk",
    "factor",
    "factors",
    "treatment",
    "therapy",
    "intervention",
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "of",
    "for",
    "in",
    "on",
    "with",
    "without",
    "to",
    "from",
    "by",
    "as",
    "at",
    "via",
    "into",
    "over",
    "under",
    "between",
    "among",
}

_NUTRITION_SIGNAL_TOKENS = (
    "carbohydrate loading",
    "carbohydrate load",
    "preoperative carbohydrate",
    "pre-operative carbohydrate",
    "oral carbohydrate",
    "carbohydrate drink",
    "maltodextrin",
)

_NUTRITION_MESH_ALLOWLIST = {
    "diet, carbohydrate loading",
    "dietary carbohydrates",
    "maltodextrin",
    "preoperative care",
}


def _tag_bare_terms(query: str) -> str:
    """Add [tiab] to free-text terms that have no field tag.

    This is a safety net for when the LLM forgets [tiab] on bare terms.
    Bare terms in PubMed search ALL fields and return far more results.
    """
    # Split on OR/AND/NOT while preserving them
    # We process token-by-token within each OR-group
    parts = re.split(r'(\b(?:AND|OR|NOT)\b)', query)
    result = []
    for part in parts:
        stripped = part.strip()
        if stripped in _BOOL_OPS or not stripped:
            result.append(part)
            continue
        # Skip if already has a field tag
        if _FIELD_TAG_RE.search(stripped):
            result.append(part)
            continue
        # Skip if it's just parentheses / whitespace
        content = stripped.strip("() ")
        if not content:
            result.append(part)
            continue
        # Skip if it contains nested boolean (sub-expression)
        if " AND " in content or " OR " in content:
            result.append(part)
            continue
        # This is a bare term — add [tiab]
        # Preserve leading/trailing parens and whitespace
        leading = ""
        trailing = ""
        temp = part
        while temp and temp[0] in " (":
            leading += temp[0]
            temp = temp[1:]
        while temp and temp[-1] in " )":
            trailing = temp[-1] + trailing
            temp = temp[:-1]
        if temp.strip():
            logger.debug("Tagging bare term with [tiab]: %r", temp.strip())
            result.append(f"{leading}{temp}[tiab]{trailing}")
        else:
            result.append(part)
    return "".join(result)


def _get_nested_list(data: dict, *keys: str) -> list[str]:
    """Read a list of strings from nested dict keys."""
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key)
    if isinstance(cur, list):
        return [str(v).strip() for v in cur if str(v).strip()]
    if isinstance(cur, str) and cur.strip():
        return [cur.strip()]
    return []


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _normalize_term(term: str) -> str:
    term = " ".join(term.strip().split())
    if len(term) >= 2 and term[0] == '"' and term[-1] == '"':
        term = term[1:-1].strip()
    return term


def _format_mesh(term: str) -> str:
    cleaned = _normalize_term(term)
    if not cleaned:
        return ""
    return f'"{cleaned}"[MeSH]'


def _format_tiab(term: str) -> str:
    cleaned = _normalize_term(term)
    if not cleaned:
        return ""
    # Preserve explicit wildcard forms unquoted.
    if "*" in cleaned:
        return f"{cleaned}[tiab]"
    if " " in cleaned:
        return f'"{cleaned}"[tiab]'
    return f"{cleaned}[tiab]"


def _format_tw(term: str) -> str:
    cleaned = _normalize_term(term)
    if not cleaned:
        return ""
    if "*" in cleaned:
        return f"{cleaned}[tw]"
    if " " in cleaned:
        return f'"{cleaned}"[tw]'
    return f"{cleaned}[tw]"


def _looks_like_age_term(term: str) -> bool:
    lower = _normalize_term(term).lower()
    return any(tok in lower for tok in _AGE_SIGNAL_TOKENS)


def _looks_like_symptom_review(extracted_json: dict) -> bool:
    pop_terms = (
        _get_nested_list(extracted_json, "core_concepts", "population_or_condition")
        + _get_nested_list(extracted_json, "exact_phrases", "population_or_condition")
        + _get_nested_list(extracted_json, "proxy_terms", "population_or_condition")
    )
    int_terms = (
        _get_nested_list(extracted_json, "core_concepts", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "exact_phrases", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "proxy_terms", "intervention_or_exposure")
    )
    pop_blob = " | ".join(pop_terms).lower()
    int_blob = " | ".join(int_terms).lower()
    has_crc = any(tok in pop_blob for tok in _CRC_SIGNAL_TOKENS)
    has_age = any(tok in pop_blob for tok in _AGE_SIGNAL_TOKENS)
    has_symptom = any(tok in int_blob for tok in _SYMPTOM_SIGNAL_TOKENS)
    return has_crc and has_age and has_symptom


def _looks_like_diet_review(extracted_json: dict) -> bool:
    int_terms = (
        _get_nested_list(extracted_json, "core_concepts", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "exact_phrases", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "proxy_terms", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "controlled_vocabulary_terms", "intervention_or_exposure")
    )
    int_blob = " | ".join(int_terms).lower()
    has_diet = any(tok in int_blob for tok in _DIET_SIGNAL_TOKENS)
    has_excluded = any(tok in int_blob for tok in _DIET_EXCLUDE_TOKENS)
    return has_diet and not has_excluded


def _looks_like_nutrition_intervention(extracted_json: dict) -> bool:
    int_terms = (
        _get_nested_list(extracted_json, "core_concepts", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "exact_phrases", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "proxy_terms", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "controlled_vocabulary_terms", "intervention_or_exposure")
    )
    int_blob = " | ".join(int_terms).lower()
    return any(tok in int_blob for tok in _NUTRITION_SIGNAL_TOKENS)


def _seed_mesh_terms(seed_data: dict | None) -> list[str]:
    if not seed_data:
        return []
    counter: Counter = Counter()
    for paper in seed_data.get("papers", []):
        counter.update(t for t in paper.get("mesh_terms", []) if t)
    return [term for term, _ in counter.most_common()]


def _seed_keyword_terms(seed_data: dict | None) -> list[str]:
    if not seed_data:
        return []
    keywords: list[str] = []
    for paper in seed_data.get("papers", []):
        for kw in paper.get("keywords", []):
            kw = str(kw).strip()
            if kw:
                keywords.append(kw)
    return _dedupe_keep_order(keywords)


def _build_diet_review_query(extracted_json: dict, seed_data: dict | None) -> str:
    """Build a robust 2-block query for diet/exposure reviews."""
    pop_mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", "population_or_condition")
    pop_text_raw = (
        _get_nested_list(extracted_json, "core_concepts", "population_or_condition")
        + _get_nested_list(extracted_json, "exact_phrases", "population_or_condition")
        + _get_nested_list(extracted_json, "proxy_terms", "population_or_condition")
    )

    pop_blob = " | ".join(pop_mesh_raw + pop_text_raw).lower()
    if "appendicitis" in pop_blob:
        for term in ("Appendiceal Diseases", "Appendix"):
            if term.lower() not in pop_blob:
                pop_mesh_raw.append(term)
        if "appendiceal" not in pop_blob:
            pop_text_raw.append("appendiceal")

    exp_mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", "intervention_or_exposure")
    exp_text_raw = (
        _get_nested_list(extracted_json, "core_concepts", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "exact_phrases", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "proxy_terms", "intervention_or_exposure")
    )

    pop_text_expanded = expand_terms(pop_text_raw)
    pop_terms = _dedupe_keep_order(
        [_format_mesh(t) for t in pop_mesh_raw if _format_mesh(t)]
        + [_format_tiab(t) for t in pop_text_expanded if _format_tiab(t)]
    )
    pop_terms = [t for t in pop_terms if t]
    pop_terms = pop_terms[:12]

    exp_blob = " | ".join(exp_mesh_raw + exp_text_raw).lower()
    diet_mesh_candidates: list[str] = []
    for token, mesh_terms in _DIET_MESH_TOKEN_MAP:
        if token in exp_blob:
            diet_mesh_candidates.extend(mesh_terms)

    seed_mesh = [
        t for t in _seed_mesh_terms(seed_data)
        if any(tok in t.lower() for tok in _DIET_SIGNAL_TOKENS)
    ]

    def _is_diet_core_mesh(term: str) -> bool:
        lower = term.lower()
        return any(
            tok in lower
            for tok in ("diet", "dietary", "food", "nutrition", "fiber", "fibre", "meat", "plant", "vegetarian", "vegan")
        )

    exp_mesh_primary = [t for t in exp_mesh_raw if _is_diet_core_mesh(t)]
    exp_mesh_secondary = [t for t in exp_mesh_raw if t not in exp_mesh_primary]

    exp_mesh_terms = _dedupe_keep_order(diet_mesh_candidates + exp_mesh_primary + seed_mesh + exp_mesh_secondary)
    exp_mesh_terms = [_format_mesh(t) for t in exp_mesh_terms if _format_mesh(t)]
    exp_mesh_terms = exp_mesh_terms[:12]

    exp_text_candidates: list[str] = list(expand_terms(exp_text_raw))
    for kw in _seed_keyword_terms(seed_data):
        if any(tok in kw.lower() for tok in _DIET_SIGNAL_TOKENS):
            exp_text_candidates.append(kw)
    for token, text_terms in _DIET_TEXT_TOKEN_MAP:
        if token in exp_blob:
            exp_text_candidates.extend(text_terms)

    exp_text_terms: list[str] = []
    priority_terms: list[str] = []
    for term in exp_text_candidates:
        norm = _normalize_term(term)
        if not norm:
            continue
        if norm.lower() in {"fiber", "fibre"}:
            priority_terms.append(norm)
    for term in priority_terms + exp_text_candidates:
        norm = _normalize_term(term)
        if not norm:
            continue
        if norm.lower() in _DIET_TW_TERMS and "*" not in norm:
            formatted = _format_tw(norm)
        else:
            formatted = _format_tiab(norm)
        if formatted:
            exp_text_terms.append(formatted)
    exp_text_terms = _dedupe_keep_order(exp_text_terms)
    exp_text_terms = exp_text_terms[:14]

    if not pop_terms or not (exp_mesh_terms or exp_text_terms):
        return ""

    pop_block = "(" + " OR ".join(pop_terms) + ")"
    exp_block = "(" + " OR ".join(_dedupe_keep_order(exp_mesh_terms + exp_text_terms)) + ")"

    return f"{pop_block} AND {exp_block} NOT (animals[MeSH] NOT humans[MeSH])"


def _build_nutrition_intervention_query(extracted_json: dict) -> str:
    """Build a focused 2-block query for perioperative nutrition interventions."""
    pop_mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", "population_or_condition")
    pop_text_raw = (
        _get_nested_list(extracted_json, "core_concepts", "population_or_condition")
        + _get_nested_list(extracted_json, "exact_phrases", "population_or_condition")
        + _get_nested_list(extracted_json, "proxy_terms", "population_or_condition")
    )

    exp_mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", "intervention_or_exposure")
    exp_text_raw = (
        _get_nested_list(extracted_json, "core_concepts", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "exact_phrases", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "proxy_terms", "intervention_or_exposure")
    )

    pop_blob = " | ".join(pop_mesh_raw + pop_text_raw).lower()
    pop_text_terms: list[str] = []
    if "colectom" in pop_blob:
        pop_text_terms.append("colectom*")
    if "colorectal" in pop_blob and "surg" in pop_blob:
        pop_text_terms.append("colorectal surg*")
    if "colorectal" in pop_blob and "resection" in pop_blob:
        pop_text_terms.append("colorectal resection*")
    if "colon" in pop_blob and "surg" in pop_blob:
        pop_text_terms.append("colon surg*")
    if "colon" in pop_blob and "resection" in pop_blob:
        pop_text_terms.append("colon resection*")
    if "colonic" in pop_blob and "surg" in pop_blob:
        pop_text_terms.append("colonic surg*")
    if "colonic" in pop_blob and "resection" in pop_blob:
        pop_text_terms.append("colonic resection*")
    if any(tok in pop_blob for tok in ("surg", "colectom", "resection", "colorectal", "colon")):
        pop_text_terms.append("abdominal surg*")

    pop_terms = _dedupe_keep_order(
        [_format_mesh(t) for t in pop_mesh_raw if _format_mesh(t)]
        + [_format_tiab(t) for t in pop_text_terms if _format_tiab(t)]
    )
    pop_terms = [t for t in pop_terms if t][:12]

    exp_mesh_terms: list[str] = []
    for term in exp_mesh_raw:
        lower = str(term).lower().strip()
        if lower in _NUTRITION_MESH_ALLOWLIST or "carbohydrate" in lower or "maltodextrin" in lower:
            exp_mesh_terms.append(term)
    exp_mesh_terms.extend(
        [
            "Diet, Carbohydrate Loading",
            "Dietary Carbohydrates",
            "Maltodextrin",
            "Preoperative Care",
        ]
    )
    exp_mesh_terms = _dedupe_keep_order(exp_mesh_terms)
    exp_mesh_terms = [_format_mesh(t) for t in exp_mesh_terms if _format_mesh(t)]

    exp_text_candidates: list[str] = []
    for term in expand_terms(exp_text_raw):
        lower = str(term).lower()
        if any(tok in lower for tok in ("carbohydrate", "maltodextrin", "preoperative", "oral")):
            exp_text_candidates.append(term)
    exp_text_candidates.extend(
        [
            "carbohydrate load*",
            "carbohydrate loading",
            "carbohydrate drink*",
            "oral carbohydrate*",
            "preoperative carbohydrate*",
            "pre-operative carbohydrate*",
            "preop carbohydrate*",
            "pre-op carbohydrate*",
            "intravenous carbohydrate*",
            "maltodextrin",
        ]
    )
    exp_text_terms = _dedupe_keep_order([_format_tiab(t) for t in exp_text_candidates if _format_tiab(t)])

    if not pop_terms or not (exp_mesh_terms or exp_text_terms):
        return ""

    pop_block = "(" + " OR ".join(pop_terms) + ")"
    exp_block = "(" + " OR ".join(_dedupe_keep_order(exp_mesh_terms + exp_text_terms)) + ")"

    return f"{pop_block} AND {exp_block} NOT (animals[MeSH] NOT humans[MeSH])"


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", text.lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _score_terms(term_sources: list[tuple[str, int]]) -> list[str]:
    scores: dict[str, int] = {}
    sources: dict[str, set[int]] = {}
    for term, weight in term_sources:
        if not term:
            continue
        key = _normalize_term(term)
        if not key:
            continue
        lower = key.lower()
        scores[lower] = scores.get(lower, 0) + weight
        sources.setdefault(lower, set()).add(weight)
    ranked: list[tuple[str, int, int, int]] = []
    for lower, score in scores.items():
        src_count = len(sources.get(lower, set()))
        ranked.append((lower, score, src_count, len(lower)))
    ranked.sort(key=lambda r: (-r[1], -r[2], -r[3], r[0]))
    return [r[0] for r in ranked]


def _select_scored_terms(terms: list[str], max_terms: int) -> list[str]:
    selected: list[str] = []
    for term in terms:
        if len(selected) >= max_terms:
            break
        selected.append(term)
    return selected


def _build_structured_query(extracted_json: dict, seed_data: dict | None) -> str:
    """Build a deterministic, seed-aware 2-block query."""
    review_text = " ".join(
        [
            str(extracted_json.get("review_title", "")),
            str(extracted_json.get("research_objective", "")),
        ]
    )
    review_tokens = _tokenize(review_text)

    def collect_facet(facet: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", facet)
        core_raw = _get_nested_list(extracted_json, "core_concepts", facet)
        phrase_raw = _get_nested_list(extracted_json, "exact_phrases", facet)
        proxy_raw = _get_nested_list(extracted_json, "proxy_terms", facet)

        def _clean_text_terms(items: list[str]) -> list[str]:
            cleaned: list[str] = []
            for t in items:
                norm = _normalize_term(t)
                if not norm:
                    continue
                if norm.lower() in _GENERIC_TEXT_TERMS:
                    continue
                cleaned.append(norm)
            return cleaned

        core_raw = _clean_text_terms(core_raw)
        phrase_raw = _clean_text_terms(phrase_raw)
        proxy_raw = _clean_text_terms(proxy_raw)

        facet_tokens = _tokenize(" ".join(core_raw + phrase_raw + proxy_raw))
        if review_tokens:
            facet_tokens = facet_tokens | review_tokens

        seed_mesh_terms: list[str] = []
        seed_keywords: list[str] = []
        if seed_data:
            for term in _seed_mesh_terms(seed_data):
                if _tokenize(term) & facet_tokens:
                    seed_mesh_terms.append(term)
            for kw in _seed_keyword_terms(seed_data):
                if _tokenize(kw) & facet_tokens:
                    seed_keywords.append(kw)

        mesh_terms: list[tuple[str, int]] = []
        for term in mesh_raw:
            norm = _normalize_term(term)
            if not norm:
                continue
            lower = norm.lower()
            if lower in _GENERIC_MESH_TERMS and not (_tokenize(lower) & review_tokens):
                continue
            mesh_terms.append((norm, 3))
        for term in seed_mesh_terms:
            norm = _normalize_term(term)
            if not norm:
                continue
            lower = norm.lower()
            if lower in _GENERIC_MESH_TERMS and not (_tokenize(lower) & review_tokens):
                continue
            mesh_terms.append((norm, 2))

        text_terms: list[tuple[str, int]] = []
        text_terms.extend((t, 3) for t in core_raw)
        text_terms.extend((t, 2) for t in phrase_raw)
        text_terms.extend((t, 1) for t in proxy_raw)
        text_terms.extend((t, 1) for t in seed_keywords)

        return mesh_terms, text_terms

    pop_mesh, pop_text = collect_facet("population_or_condition")
    exp_mesh, exp_text = collect_facet("intervention_or_exposure")

    pop_mesh_ranked = _score_terms(pop_mesh)
    exp_mesh_ranked = _score_terms(exp_mesh)

    pop_text_ranked = _score_terms(pop_text)
    exp_text_ranked = _score_terms(exp_text)

    pop_mesh_selected = _select_scored_terms(pop_mesh_ranked, 5)
    exp_mesh_selected = _select_scored_terms(exp_mesh_ranked, 5)

    pop_text_selected = _select_scored_terms(pop_text_ranked, 6)
    exp_text_selected = _select_scored_terms(exp_text_ranked, 6)

    pop_text_expanded = expand_terms(pop_text_selected)
    exp_text_expanded = expand_terms(exp_text_selected)

    pop_terms = _dedupe_keep_order(
        [_format_mesh(t) for t in pop_mesh_selected if _format_mesh(t)]
        + [_format_tiab(t) for t in pop_text_expanded if _format_tiab(t)]
    )
    exp_terms = _dedupe_keep_order(
        [_format_mesh(t) for t in exp_mesh_selected if _format_mesh(t)]
        + [_format_tiab(t) for t in exp_text_expanded if _format_tiab(t)]
    )

    if not pop_terms and not exp_terms:
        return ""
    if pop_terms and not exp_terms:
        block = "(" + " OR ".join(pop_terms) + ")"
        return f"{block} NOT (animals[MeSH] NOT humans[MeSH])"
    if exp_terms and not pop_terms:
        block = "(" + " OR ".join(exp_terms) + ")"
        return f"{block} NOT (animals[MeSH] NOT humans[MeSH])"

    pop_block = "(" + " OR ".join(pop_terms) + ")"
    exp_block = "(" + " OR ".join(exp_terms) + ")"
    return f"{pop_block} AND {exp_block} NOT (animals[MeSH] NOT humans[MeSH])"


def _build_symptom_review_query(extracted_json: dict) -> str:
    """Build a robust 3-block query for early-onset symptom/presentation reviews."""
    pop_mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", "population_or_condition")
    pop_text_raw = (
        _get_nested_list(extracted_json, "core_concepts", "population_or_condition")
        + _get_nested_list(extracted_json, "exact_phrases", "population_or_condition")
        + _get_nested_list(extracted_json, "proxy_terms", "population_or_condition")
    )

    int_mesh_raw = _get_nested_list(extracted_json, "controlled_vocabulary_terms", "intervention_or_exposure")
    int_text_raw = (
        _get_nested_list(extracted_json, "core_concepts", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "exact_phrases", "intervention_or_exposure")
        + _get_nested_list(extracted_json, "proxy_terms", "intervention_or_exposure")
    )

    # Disease block
    disease_mesh = [
        t for t in pop_mesh_raw
        if any(k in t.lower() for k in ("colorectal", "colonic", "rectal", "neoplasm", "cancer"))
    ] or pop_mesh_raw
    disease_text = [t for t in pop_text_raw if not _looks_like_age_term(t)]
    disease_text += ["colorectal cancer", "colon cancer", "rectal cancer", "colorectal neoplasm*"]
    if any("colorectal" in t.lower() for t in disease_text):
        disease_text.append("CRC")

    disease_terms = _dedupe_keep_order(
        [_format_mesh(t) for t in disease_mesh[:4]]
        + [_format_tiab(t) for t in disease_text[:8]]
    )
    disease_terms = [t for t in disease_terms if t]

    # Age qualifier block (kept separate to avoid demographic MeSH as standalone OR with disease)
    age_text = [t for t in pop_text_raw if _looks_like_age_term(t)]
    age_text += [
        "early onset",
        "young onset",
        "younger patient*",
        "young patient*",
        "under 50",
        "before age 50",
        "age onset",
    ]
    age_terms = _dedupe_keep_order(
        [_format_mesh("Age of Onset")]
        + [_format_tiab(t) for t in age_text[:10]]
    )
    age_terms = [t for t in age_terms if t]

    # Symptom/presentation block
    symptom_mesh = [
        t for t in int_mesh_raw
        if any(k in t.lower() for k in ("diagnos", "hematochezia", "pain", "anemia", "anaemia", "delay"))
    ]
    symptom_mesh += ["Diagnosis", "Early Detection of Cancer"]
    symptom_text = list(int_text_raw) + [
        "diagnos*",
        "detect*",
        "symptom*",
        "sign*",
        "clinical presentation",
        "recognition",
    ]
    symptom_terms = _dedupe_keep_order(
        [_format_mesh(t) for t in symptom_mesh[:6]]
        + [_format_tiab(t) for t in symptom_text[:12]]
    )
    symptom_terms = [t for t in symptom_terms if t]

    if not disease_terms or not age_terms or not symptom_terms:
        return ""

    disease_block = "(" + " OR ".join(disease_terms) + ")"
    age_block = "(" + " OR ".join(age_terms) + ")"
    symptom_block = "(" + " OR ".join(symptom_terms) + ")"

    return f"(({age_block} AND {disease_block}) AND {symptom_block}) NOT (animals[MeSH] NOT humans[MeSH])"


def _clean_controlled_vocab_terms(extracted_json: dict) -> None:
    controlled = extracted_json.get("controlled_vocabulary_terms")
    if not isinstance(controlled, dict):
        return
    for facet in ("population_or_condition", "intervention_or_exposure"):
        raw_terms = controlled.get(facet)
        if not isinstance(raw_terms, list) or not raw_terms:
            continue
        if len(raw_terms) <= 1:
            continue
        cleaned: list[str] = []
        for term in raw_terms:
            if not isinstance(term, str):
                continue
            lower = term.strip().lower()
            if lower in _BROAD_MESH_DROP_IF_MULTIPLE:
                continue
            if "/surgery" in lower and ("disease" in lower or "colon" in lower):
                continue
            cleaned.append(term)
        controlled[facet] = cleaned


# ---------------------------------------------------------------------------
# Seed-paper helpers
# ---------------------------------------------------------------------------

def load_seed_papers(
    seed_papers_dir: Path,
    study_id: str,
    study_name: str,
    max_seeds: int | None = 3,
    rng_seed: int | None = None,
) -> dict | None:
    """Load seed papers for a study, sampling a realistic subset.

    In a real systematic review workflow, authors only have a handful of
    known-relevant papers when designing the search strategy — not the full
    set of included studies.  This function simulates that by randomly
    sampling *max_seeds* papers from the included-studies JSON.

    Parameters
    ----------
    seed_papers_dir : Path
        Directory containing ``<id> - <name>.json`` files.
    study_id, study_name : str
        Used to locate the correct JSON file.
    max_seeds : int | None
        Maximum number of papers to keep.  ``None`` means use all (legacy
        behaviour — **not** recommended for realistic evaluation).
    rng_seed : int | None
        Optional seed for the random number generator so results are
        reproducible.
    """
    pattern = f"{study_id} - {study_name}.json"
    path = seed_papers_dir / pattern
    data: dict | None = None
    if path.exists():
        with open(path) as f:
            data = json.load(f)
    else:
        for p in seed_papers_dir.glob(f"{study_id} - *.json"):
            with open(p) as f:
                data = json.load(f)
            break

    if data is None:
        return None

    papers = data.get("papers", [])
    # Only sample from papers that have actual metadata (title, MeSH, or abstract).
    # Some entries are empty placeholders from failed PubMed lookups.
    papers_with_data = [p for p in papers if p.get("title") or p.get("mesh_terms") or p.get("abstract")]
    papers_without_data = [p for p in papers if p not in papers_with_data]

    if rng_seed is None:
        seed_source = f"{study_id}:{study_name}".encode("utf-8")
        rng_seed = int(hashlib.md5(seed_source).hexdigest()[:8], 16)

    if max_seeds is not None and len(papers_with_data) > max_seeds:
        rng = random.Random(rng_seed)
        sampled = rng.sample(papers_with_data, max_seeds)
        logger.info(
            "Sampled %d/%d seed papers for study %s (rng_seed=%s): %s",
            max_seeds,
            len(papers_with_data),
            study_id,
            rng_seed,
            [p.get("pmid", "?") for p in sampled],
        )
        data = {**data, "papers": sampled, "paper_count": len(sampled)}
    else:
        # Use all papers with data (drop empty placeholders)
        data = {**data, "papers": papers_with_data, "paper_count": len(papers_with_data)}
        logger.info(
            "Using all %d seed papers for study %s (max_seeds=%s, %d empty skipped)",
            len(papers_with_data), study_id, max_seeds, len(papers_without_data),
        )

    return data


def summarise_seed_mesh(seed_data: dict, min_count: int = 1) -> str:
    """Produce a compact MeSH-frequency summary from seed papers.

    Only includes MeSH terms appearing in >= *min_count* papers and
    excludes generic demographic / study-design headings.

    Default *min_count* is 1 because with a small seed sample (e.g. 3
    papers) even single-occurrence terms are valuable signal.
    """
    _GENERIC_MESH = {
        "humans", "male", "female", "adult", "middle aged", "aged",
        "aged, 80 and over", "young adult", "adolescent", "child",
        "child, preschool", "infant", "infant, newborn",
        "retrospective studies", "prospective studies",
        "cross-sectional studies", "cohort studies",
        "follow-up studies", "treatment outcome",
        "randomized controlled trials as topic",
        # Overly broad MeSH that cause query bloat
        "signs and symptoms", "risk factors", "surveys and questionnaires",
        "biomarkers", "life style", "prognosis",
    }
    papers = seed_data.get("papers", [])
    papers_with_mesh = [p for p in papers if p.get("mesh_terms")]
    if not papers_with_mesh:
        return "(no MeSH data in seed papers)"
    counter: Counter = Counter()
    for p in papers_with_mesh:
        counter.update(t for t in p["mesh_terms"])
    n = len(papers_with_mesh)
    lines: list[str] = []
    for term, count in counter.most_common():
        if count < min_count:
            break
        if term.lower() in _GENERIC_MESH:
            continue
        lines.append(f"  {term}  ({count}/{n} papers)")
    return "\n".join(lines) if lines else "(no recurring non-generic MeSH terms)"


def _seed_paper_titles(seed_data: dict, max_papers: int = 5) -> str:
    """Return a few representative seed-paper titles."""
    papers = [p for p in seed_data.get("papers", []) if p.get("title")]
    lines = [f"  - {p['title']}" for p in papers[:max_papers]]
    return "\n".join(lines) if lines else "(none)"


def _seed_paper_keywords(seed_data: dict) -> str:
    """Aggregate author keywords from seed papers."""
    kw_counter: Counter = Counter()
    for p in seed_data.get("papers", []):
        for kw in p.get("keywords", []):
            if kw.strip():
                kw_counter[kw.strip()] += 1
    if not kw_counter:
        return "(no author keywords in seed papers)"
    lines = [f"  {kw}  ({c}x)" for kw, c in kw_counter.most_common(20)]
    return "\n".join(lines)


def _seed_paper_abstracts(seed_data: dict, max_chars: int = 300) -> str:
    """Return truncated abstract snippets from seed papers."""
    parts: list[str] = []
    for p in seed_data.get("papers", []):
        title = p.get("title", "")
        abstract = p.get("abstract", "")
        if not title:
            continue
        snippet = abstract[:max_chars].rsplit(" ", 1)[0] + "..." if len(abstract) > max_chars else abstract
        parts.append(f"  PMID {p.get('pmid', '?')} — {title}\n    {snippet}")
    return "\n".join(parts) if parts else "(none)"


# ---------------------------------------------------------------------------
# Step 2 prompt — recall-optimised query composition
# ---------------------------------------------------------------------------

_COMPOSE_QUERY_PROMPT = """\
You are an expert medical librarian building a PubMed search strategy for \
a systematic review.  Your goal is **high recall** while keeping the query \
compact and well-targeted — like a human librarian would write.

## Task
Convert the structured extraction JSON into a single PubMed boolean query. \
You also receive MeSH terms, author keywords, and abstract snippets from a \
few known included studies ("seed papers").  Use these to pick the RIGHT \
terms, not ALL possible terms.

## Extracted concepts
{extracted_json}

## Seed-paper MeSH terms (from {n_seed} seed papers)
{seed_mesh}

## Seed-paper author keywords
{seed_keywords}

## Seed-paper titles & abstract snippets
{seed_abstracts}

## Rules

1. **Structure — use the MINIMUM number of AND blocks needed.**
   Default is TWO blocks:
     (condition block) AND (intervention / exposure block)
   Use THREE AND blocks when the review defines a specific sub-population
   that would otherwise make the query too broad.  Example:
     (early-onset terms AND colorectal cancer) AND (symptom terms)
   This is necessary when the condition block contains both a disease AND
   a population qualifier (age, setting, etc.) — the qualifier must be
   its own AND block or nested with AND inside the condition block.

2. **CRITICAL — demographic MeSH must be AND'd with the disease.**
   "Young Adult"[MeSH], "Adolescent"[MeSH], "Adult"[MeSH], "Child"[MeSH],
   "Aged"[MeSH] — these each match MILLIONS of papers.  They must NEVER
   appear as standalone OR terms in a block.  They must always be AND'd
   with the disease term, either:
   - As a separate AND block: (age terms) AND (disease) AND (exposure)
   - Or nested: ("Young Adult"[Mesh] AND "Colorectal Neoplasms"[MeSH])
   WRONG: "Colorectal Neoplasms"[MeSH] OR "Young Adult"[MeSH] OR ...
   RIGHT: ("Young Adult"[Mesh] AND "Colorectal Neoplasms"[MeSH]) as one
          OR-clause within a larger block.

3. **CRITICAL — EVERY free-text term must have a [tiab] field tag.**
   Bare terms (no field tag) search ALL fields and return orders of
   magnitude more results.
   WRONG: symptom* OR sign* OR "colorectal cancer"
   RIGHT: symptom*[tiab] OR sign*[tiab] OR "colorectal cancer"[tiab]
   The ONLY exception is when a term is already MeSH-tagged: "Term"[MeSH].

4. **Keep each block compact: 3-6 MeSH terms + 3-8 free-text terms.**
   A human librarian query typically has ~5-12 terms per block.
   SELECT the best terms — do NOT include everything from the extraction.

5. **MeSH term selection — quality over quantity.**
   - Include the most specific MeSH heading for the core concept.
   - Include ONE broader parent MeSH that appears in the seed papers
     (e.g., both "Colectomy"[MeSH] and "Colorectal Surgery"[MeSH]).
   - For topics with known subtypes, include 2-3 key sub-type MeSH.
   - NEVER use "Signs and Symptoms"[MeSH] — it matches >1M papers.
     Use "Diagnosis"[MeSH] or specific symptom MeSH instead.
   - NEVER use "Adult"[MeSH] or "Adolescent"[MeSH] as standalone OR
     terms.  Use "Age of Onset"[MeSH] for age-related reviews instead.
   - Do NOT include very broad MeSH like "Digestive System Surgical
     Procedures"[MeSH], "Food"[MeSH], "Eating"[MeSH], "Risk Factors"[MeSH],
     "Biomarkers"[MeSH], "Life Style"[MeSH] unless THE central topic.

6. **Free-text terms — use truncation, not enumeration.**
   - Use truncation to cover variants: colectom*[tiab] covers colectomy,
     colectomies.  Do NOT list both separately.
   - Include British/American spelling variants:
     appendectom*[tiab] OR appendicectom*[tiab]
     fiber[tiab] OR fibre[tiab]
   - Look at seed-paper titles for key phrases the query must capture.

7. **Do NOT include these unless they are the review's MAIN topic:**
   - Outcomes, assessment tools, biomarkers, lifestyle/risk factors (MeSH)
   - Study designs, comparators, ERAS / enhanced recovery

8. **End with**: NOT (animals[MeSH] NOT humans[MeSH])

9. **Output**: Return ONLY the PubMed query string.  No explanations, no
   markdown, no labels.

## Example of a well-structured 3-block query (for age-qualified reviews):
((early onset[tiab] OR young onset[tiab] OR "Age of Onset"[MeSH] OR \
"younger patient*"[tiab] OR ("Young Adult"[Mesh] AND "Colorectal \
Neoplasms"[MeSH])) AND ("Colorectal Neoplasms"[MeSH] OR "colorectal \
cancer"[tiab] OR "colon cancer"[tiab])) AND (diagnos*[tiab] OR \
detect*[tiab] OR sign*[tiab] OR symptom*[tiab] OR "Diagnosis"[MeSH]) \
NOT (animals[MeSH] NOT humans[MeSH])
"""


# ---------------------------------------------------------------------------
# Step 3 prompt — self-critique refinement
# ---------------------------------------------------------------------------

_REFINE_QUERY_PROMPT = """\
You are a medical librarian reviewing a draft PubMed systematic review \
search query.  Your goals are to (1) catch missing seed papers and \
(2) fix structural errors that would make the query too broad.

## Draft query
{draft_query}

## Seed papers (known included studies that the query MUST retrieve)
{seed_abstracts}

## Seed-paper MeSH terms
{seed_mesh}

## Seed-paper author keywords
{seed_keywords}

## Step 1 — Fix structural errors FIRST:
a) Every free-text term MUST have [tiab].  If you see bare terms like
   `symptom*` or `"colorectal cancer"` without a field tag, add [tiab].
b) Demographic MeSH ("Young Adult"[MeSH], "Adolescent"[MeSH], etc.) must
   NEVER be standalone OR terms — they must be AND'd with the disease.
   Fix: ("Young Adult"[Mesh] AND "Colorectal Neoplasms"[MeSH]) as a
   single OR clause, or move to a separate AND block.

## Step 2 — Check seed paper coverage:
For each seed paper, check whether the query would plausibly retrieve it.
If a seed paper might be missed, add ONLY the minimum terms needed.
Typical fixes (add at most 1-3 terms total):
- A parent MeSH heading (e.g., "Colorectal Surgery"[MeSH])
- A British/American spelling variant (e.g., appendicectom*[tiab])
- A key phrase from the seed paper title (tagged with [tiab])

## Constraints:
- Add at MOST 3 new terms.  Do not bloat the query.
- Keep the same number of AND blocks (do not add or remove AND blocks).
- Only ADD or FIX terms — do not remove existing terms.
- Ensure parentheses are balanced.
- End with NOT (animals[MeSH] NOT humans[MeSH]).

Return ONLY the revised PubMed query string.  No explanations.  \
If no changes are needed, return the draft query unchanged.
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GeneratedQuery:
    """Result of generating a PubMed query."""

    query: str
    prompt_version: str
    generation_time: float
    token_usage: dict
    is_valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    extracted_json: dict | None = None


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

_DEFAULT_SEED_DIR = Path("seed_papers")


class QueryGenerator:
    """Generate PubMed queries from PROSPERO PDFs.

    Pipeline:
    1. LLM extracts structured JSON from protocol PDF.
    2. LLM composes the final PubMed query, informed by seed-paper MeSH.
       Falls back to the deterministic rule-based builder on failure.
    """

    def __init__(
        self,
        client: OpenAIClient,
        seed_papers_dir: Path = _DEFAULT_SEED_DIR,
        max_seeds: int | None = 3,
        rng_seed: int | None = None,
    ):
        self.client = client
        self.seed_papers_dir = seed_papers_dir
        self.max_seeds = max_seeds
        self.rng_seed = rng_seed

    # ── public API ─────────────────────────────────────────────────────

    def generate_query(self, prospero_path: Path) -> GeneratedQuery:
        """Generate a PubMed query from a PROSPERO protocol PDF."""
        start_time = time.time()
        tokens: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        prompt_version = "llm_seed_v2"

        # ── Step 1: LLM extraction ────────────────────────────────────
        pico_response: LLMResponse = self.client.generate_with_file(
            prompt=PICO_EXTRACTION_PROMPT,
            file_path=prospero_path,
        )
        self._accum_tokens(tokens, pico_response)

        try:
            extracted_json = parse_extracted_json(pico_response.content)
        except (json.JSONDecodeError, ValueError) as exc:
            return self._fail(
                f"Failed to parse extraction JSON: {exc}",
                tokens, start_time,
            )
        _clean_controlled_vocab_terms(extracted_json)

        # ── Resolve seed papers ────────────────────────────────────────
        study_id, study_name = self._infer_study_id(prospero_path)
        seed_data = load_seed_papers(
            self.seed_papers_dir, study_id, study_name,
            max_seeds=self.max_seeds,
            rng_seed=self.rng_seed,
        )
        if _looks_like_diet_review(extracted_json) and (self.max_seeds or 0) < 5:
            seed_data = load_seed_papers(
                self.seed_papers_dir, study_id, study_name,
                max_seeds=5,
                rng_seed=self.rng_seed,
            )

        # ── Step 2: Query composition ───────────────────────────────────
        # For early-onset cancer symptom/presentation reviews we use a
        # deterministic high-recall 3-block template to avoid LLM drift.
        if _looks_like_symptom_review(extracted_json):
            logger.info("Detected symptom/presentation review — using rule-based 3-block composer")
            query = _build_symptom_review_query(extracted_json)
            prompt_version = "symptom_rule_v1"
        elif _looks_like_nutrition_intervention(extracted_json):
            logger.info("Detected perioperative nutrition review — using rule-based nutrition composer")
            query = _build_nutrition_intervention_query(extracted_json)
            prompt_version = "nutrition_rule_v1"
        elif _looks_like_diet_review(extracted_json):
            logger.info("Detected diet/exposure review — using rule-based diet composer")
            query = _build_diet_review_query(extracted_json, seed_data)
            prompt_version = "diet_rule_v1"
        else:
            query = _build_structured_query(extracted_json, seed_data)
            prompt_version = "structured_seed_v1"
            if not query:
                query = self._compose_query_llm(extracted_json, seed_data, tokens)
                prompt_version = "llm_seed_v2"

        # ── Fallback to rule-based builder ─────────────────────────────
        if not query:
            logger.info("LLM composition failed/empty — falling back to rule-based builder")
            query = build_query(extracted_json)

        generation_time = time.time() - start_time

        if not query:
            return GeneratedQuery(
                query="",
                prompt_version=prompt_version,
                generation_time=generation_time,
                token_usage=tokens,
                is_valid=False,
                validation_errors=["Both LLM and rule-based builder produced empty query"],
                extracted_json=extracted_json,
            )

        errors = _validate_query(query)
        return GeneratedQuery(
            query=query,
            prompt_version=prompt_version,
            generation_time=generation_time,
            token_usage=tokens,
            is_valid=len(errors) == 0,
            validation_errors=errors,
            extracted_json=extracted_json,
        )

    def generate_queries_batch(
        self,
        prospero_paths: list[Path],
        max_workers: int = 5,
    ) -> list[GeneratedQuery]:
        """Generate PubMed queries for multiple PROSPERO PDFs in parallel."""
        results: list[GeneratedQuery | None] = [None] * len(prospero_paths)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {}
            for idx, path in enumerate(prospero_paths):
                future = executor.submit(self.generate_query, path)
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = GeneratedQuery(
                        query="",
                        prompt_version="llm_seed_v2",
                        generation_time=0.0,
                        token_usage={},
                        is_valid=False,
                        validation_errors=[f"Generation failed: {e}"],
                    )

        return results  # type: ignore[return-value]

    # ── private helpers ────────────────────────────────────────────────

    def _compose_query_llm(
        self,
        extracted_json: dict,
        seed_data: dict | None,
        tokens: dict,
    ) -> str:
        """Use the LLM to compose the final PubMed query, then refine.

        Returns the query string, or empty string on failure.
        """
        seed_mesh = summarise_seed_mesh(seed_data) if seed_data else "(no seed papers available)"
        seed_keywords = _seed_paper_keywords(seed_data) if seed_data else "(none)"
        seed_abstracts = _seed_paper_abstracts(seed_data) if seed_data else "(none)"
        n_seed = len(seed_data.get("papers", [])) if seed_data else 0

        prompt = _COMPOSE_QUERY_PROMPT.format(
            extracted_json=json.dumps(extracted_json, indent=2, ensure_ascii=False),
            seed_mesh=seed_mesh,
            seed_keywords=seed_keywords,
            seed_abstracts=seed_abstracts,
            n_seed=n_seed,
        )

        try:
            response: LLMResponse = self.client.generate_text(prompt)
            self._accum_tokens(tokens, response)
            query = _extract_query_from_llm(response.content)
            errors = _validate_query(query)
            if errors:
                logger.warning("LLM composition produced invalid query: %s", errors)
                return ""
        except Exception as exc:
            logger.warning("LLM composition failed: %s", exc)
            return ""

        # ── Step 3: Self-critique refinement ───────────────────────────
        if seed_data and seed_data.get("papers"):
            query = self._refine_query_llm(query, seed_data, tokens)

        # ── Post-processing: tag any bare free-text terms with [tiab] ──
        query = _tag_bare_terms(query)

        return query

    def _refine_query_llm(
        self,
        draft_query: str,
        seed_data: dict,
        tokens: dict,
    ) -> str:
        """Ask the LLM to review the draft query against seed papers.

        Returns the refined query, or the original on failure.
        """
        seed_mesh = summarise_seed_mesh(seed_data)
        seed_keywords = _seed_paper_keywords(seed_data)
        seed_abstracts = _seed_paper_abstracts(seed_data)

        prompt = _REFINE_QUERY_PROMPT.format(
            draft_query=draft_query,
            seed_mesh=seed_mesh,
            seed_keywords=seed_keywords,
            seed_abstracts=seed_abstracts,
        )

        try:
            response: LLMResponse = self.client.generate_text(prompt)
            self._accum_tokens(tokens, response)
            refined = _extract_query_from_llm(response.content)
            errors = _validate_query(refined)
            if errors:
                logger.warning("Refinement produced invalid query (%s) — keeping draft", errors)
                return draft_query
            logger.info("Query refined by self-critique step")
            return refined
        except Exception as exc:
            logger.warning("Refinement step failed (%s) — keeping draft", exc)
            return draft_query

    @staticmethod
    def _infer_study_id(prospero_path: Path) -> tuple[str, str]:
        """Infer study_id and study_name from the PROSPERO path.

        Expects the parent directory to be named like ``34 - Lu 2022``.
        """
        parent = prospero_path.parent.name
        m = re.match(r"^(\d+)\s*-\s*(.+)$", parent)
        if m:
            return m.group(1), m.group(2).strip()
        return "", ""

    @staticmethod
    def _accum_tokens(totals: dict, response: LLMResponse) -> None:
        totals["prompt_tokens"] += response.prompt_tokens
        totals["completion_tokens"] += response.completion_tokens
        totals["total_tokens"] += response.total_tokens

    @staticmethod
    def _fail(
        message: str,
        tokens: dict,
        start_time: float,
    ) -> GeneratedQuery:
        return GeneratedQuery(
            query="",
            prompt_version="llm_seed_v2",
            generation_time=time.time() - start_time,
            token_usage=tokens,
            is_valid=False,
            validation_errors=[message],
            extracted_json=None,
        )
