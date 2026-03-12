"""Rule-based PubMed query builder.

Takes structured concept JSON from the LLM extraction step and
deterministically assembles a PubMed boolean query.

Design choices
--------------
- Two concept blocks: population/condition AND intervention/exposure.
- MeSH terms first, then free-text terms (core → exact phrases → proxies).
- Case-insensitive deduplication preserving first-seen casing.
- Terms already containing a wildcard ``*`` are kept as-is.
- Multi-word free-text terms are quoted.
- Animal exclusion filter appended by default.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# The two default facets that map to the extraction prompt's sub-keys.
# ---------------------------------------------------------------------------
_FACETS: tuple[str, str] = ("population_or_condition", "intervention_or_exposure")


# ── normalisation helpers ──────────────────────────────────────────────────

def normalize_term(term: str) -> str:
    """Normalize whitespace, strip surrounding quotes and trailing periods."""
    term = term.strip()
    # Strip matched surrounding double-quotes
    if len(term) >= 2 and term[0] == '"' and term[-1] == '"':
        term = term[1:-1].strip()
    # Strip trailing period (common LLM artefact)
    if term.endswith("."):
        term = term[:-1].strip()
    # Collapse internal whitespace
    term = " ".join(term.split())
    return term


def deduplicate(terms: list[str]) -> list[str]:
    """Case-insensitive deduplication preserving first-seen order and casing."""
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
    return result


# ── formatting helpers ─────────────────────────────────────────────────────

def format_mesh(term: str) -> str:
    """Format a term as a PubMed MeSH search token.

    Example:  ``"Appendicitis"[MeSH]``
    """
    term = normalize_term(term)
    if not term:
        return ""
    return f'"{term}"[MeSH]'


def format_tiab(term: str) -> str:
    """Format a term as a PubMed title/abstract free-text token.

    Multi-word terms are quoted.  Terms containing ``*`` (truncation) are
    left unquoted so PubMed interprets the wildcard correctly.
    """
    term = normalize_term(term)
    if not term:
        return ""
    # If the term contains a wildcard, do NOT add surrounding quotes
    if "*" in term:
        return f"{term}[tiab]"
    # Multi-word → quote
    if " " in term:
        return f'"{term}"[tiab]'
    return f"{term}[tiab]"


# ── internal collection helpers ────────────────────────────────────────────

def _get_list(data: dict, *keys: str) -> list[str]:
    """Traverse nested keys and return a list of strings.

    Example::

        _get_list(data, "core_concepts", "population_or_condition")

    Returns ``[]`` when any intermediate key is missing or the leaf is
    not a list.
    """
    current = data
    for k in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(k)
        if current is None:
            return []
    if isinstance(current, list):
        return [str(v).strip() for v in current if str(v).strip()]
    if isinstance(current, str) and current.strip():
        return [current.strip()]
    return []


def _collect_mesh_terms(extracted: dict, facet: str) -> list[str]:
    """Collect MeSH terms for a facet from ``controlled_vocabulary_terms``."""
    raw = _get_list(extracted, "controlled_vocabulary_terms", facet)
    return [format_mesh(t) for t in raw if format_mesh(t)]


def _collect_freetext_terms(extracted: dict, facet: str) -> list[str]:
    """Collect free-text terms for a facet from core, phrases, and proxies."""
    raw: list[str] = []
    raw.extend(_get_list(extracted, "core_concepts", facet))
    raw.extend(_get_list(extracted, "exact_phrases", facet))
    raw.extend(_get_list(extracted, "proxy_terms", facet))
    return [format_tiab(t) for t in raw if format_tiab(t)]


# ── block and query assembly ───────────────────────────────────────────────

def build_block(extracted: dict, facet: str) -> str:
    """Build a single concept block (e.g. population or intervention).

    Combines MeSH terms and free-text terms with OR, wrapped in parens.
    Returns empty string if no terms found.
    """
    mesh = _collect_mesh_terms(extracted, facet)
    freetext = _collect_freetext_terms(extracted, facet)
    all_terms = deduplicate(mesh + freetext)
    if not all_terms:
        return ""
    return "(" + " OR ".join(all_terms) + ")"


ANIMAL_FILTER: str = "NOT (animals[MeSH] NOT humans[MeSH])"


def build_query(extracted_json: dict) -> str:
    """Build a complete PubMed query from extraction JSON.

    Returns a single-line boolean query string of the form::

        (population block) AND (intervention block) NOT (animals …)

    If one facet has no terms, only the other block is used.
    If neither facet has terms, an empty string is returned.
    """
    blocks: list[str] = []
    for facet in _FACETS:
        block = build_block(extracted_json, facet)
        if block:
            blocks.append(block)
    if not blocks:
        return ""
    query = " AND ".join(blocks)
    query = f"{query} {ANIMAL_FILTER}"
    return query

