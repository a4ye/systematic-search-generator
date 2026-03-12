"""Rule-based PubMed query builder.

Takes structured concept JSON from the LLM extraction step and
deterministically assembles a PubMed boolean query.

Design choices
--------------
- Two concept blocks: population/condition AND intervention/exposure.
- MeSH terms first, then free-text terms (core → exact phrases → proxies).
- Proxy terms are also promoted to MeSH (safe — PubMed returns 0 for
  invalid headings, so false positives are harmless).
- Single-word terms are expanded with truncation wildcards for strong
  medical stems (``-ectomy`` → ``ectom*``, ``-operative`` → ``operat*``, …).
- Hyphen/space variants are generated for multi-word phrases.
- Cohort-description phrases (``patients undergoing …``) and methodology
  terms (``… questionnaire``) are filtered from exact_phrases / proxy_terms.
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
        if key not in seen:
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


# ── lexical expansion ─────────────────────────────────────────────────────
#
# Truncation rules for strong medical stems.  Each tuple maps a suffix to
# its wildcard-truncated replacement.  Only applied to single-word terms
# whose stem (the part before the suffix) is at least ``_MIN_STEM_LEN``
# characters long.
#
# Ordered longest-suffix-first so that e.g. "ectomies" is tried before
# "ectomy".

_TRUNCATION_RULES: list[tuple[str, str]] = [
    ("ectomies", "ectom*"),
    ("ectomized", "ectom*"),
    ("ectomy", "ectom*"),       # colectomy  → colectom*
    ("otomies", "otom*"),
    ("otomy", "otom*"),         # laparotomy → laparotom*
    ("oscopies", "oscop*"),
    ("oscopy", "oscop*"),       # colonoscopy → colonoscop*
    ("plasties", "plast*"),
    ("plasty", "plast*"),       # arthroplasty → arthroplast*
    ("operatively", "operat*"),
    ("operative", "operat*"),   # preoperative → preoperat*
]

_MIN_STEM_LEN = 3  # minimum chars before the matched suffix


def truncation_variants(term: str) -> list[str]:
    """Generate wildcard-truncated forms for a single-word medical term.

    Returns a list of 0–1 variants:
      * the truncated form itself  (``appendectom*``)
    """
    lower = normalize_term(term).lower()
    if not lower or " " in lower or "*" in lower:
        return []

    for suffix, replacement in _TRUNCATION_RULES:
        if lower.endswith(suffix):
            stem = lower[: len(lower) - len(suffix)]
            if len(stem) < _MIN_STEM_LEN:
                break
            return [stem + replacement]
    return []



def expand_terms(raw_terms: list[str]) -> list[str]:
    """Return *raw_terms* plus truncation and hyphen/space variants.

    * Single-word terms get truncation variants.
    * Multi-word terms get hyphen/space variants.
    """
    expanded: list[str] = list(raw_terms)
    for term in raw_terms:
        norm = normalize_term(term)
        if not norm:
            continue
        words = norm.split()
        if len(words) == 1:
            expanded.extend(truncation_variants(norm))
        else:
            if "-" in norm:
                expanded.append(norm.replace("-", " "))
    return expanded


# ── noise filtering ────────────────────────────────────────────────────────
#
# Applied only to exact_phrases and proxy_terms (never to core_concepts,
# which are trusted as-is).

_COHORT_PREFIXES: tuple[str, ...] = (
    "patients with ",
    "patients undergoing ",
    "patients who ",
    "patients receiving ",
    "patients diagnosed ",
    "people with ",
    "people undergoing ",
    "individuals with ",
    "individuals undergoing ",
    "subjects with ",
    "following ",
    "after ",
    "adults with ",
    "adults undergoing ",
    "children with ",
    "children undergoing ",
    "women with ",
    "women undergoing ",
    "men with ",
    "men undergoing ",
)

_NOISE_SUBSTRINGS: tuple[str, ...] = (
    "questionnaire",
    "survey instrument",
    "assessment tool",
    "rating scale",
    "screening tool",
)


def is_noise_term(term: str) -> bool:
    """Return ``True`` if the term is a cohort description or methodology/instrument term."""
    lower = normalize_term(term).lower()
    if not lower:
        return False
    for prefix in _COHORT_PREFIXES:
        if lower.startswith(prefix):
            return True
    for sub in _NOISE_SUBSTRINGS:
        if sub in lower:
            return True
    return False


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
    """Collect MeSH terms for a facet.

    Sources (in order):

    1. ``controlled_vocabulary_terms`` — the primary MeSH source.
    2. ``proxy_terms`` — also promoted to MeSH (title-cased).  Terms that
       contain wildcards are skipped since MeSH does not support them.
       This is safe: PubMed returns 0 results for invalid MeSH headings.
    """
    raw = _get_list(extracted, "controlled_vocabulary_terms", facet)
    # Promote proxy terms to MeSH (skip wildcards and noise)
    for proxy in _get_list(extracted, "proxy_terms", facet):
        if "*" not in proxy and not is_noise_term(proxy):
            raw.append(proxy.title())
    return [format_mesh(t) for t in raw if format_mesh(t)]


def _collect_freetext_terms(extracted: dict, facet: str) -> list[str]:
    """Collect free-text terms with lexical expansion and noise filtering.

    Sources: ``core_concepts`` (always trusted), ``strategy_terms``,
    ``spelling_variants``, ``wildcard_terms``, ``exact_phrases`` and
    ``proxy_terms`` (noise-filtered).  All surviving terms are then
    expanded with truncation and hyphen/space variants.
    """
    raw: list[str] = []
    # Core concepts — always included
    raw.extend(_get_list(extracted, "core_concepts", facet))
    # Optional structured terms (already curated by extraction)
    raw.extend(_get_list(extracted, "strategy_terms", facet))
    raw.extend(_get_list(extracted, "spelling_variants", facet))
    raw.extend(_get_list(extracted, "wildcard_terms", facet))
    # Exact phrases and proxy terms — noise-filtered
    for section in ("exact_phrases", "proxy_terms"):
        for t in _get_list(extracted, section, facet):
            if not is_noise_term(t):
                raw.append(t)
    # Expand with truncation + hyphen/space variants
    expanded = expand_terms(raw)
    return [format_tiab(t) for t in expanded if format_tiab(t)]


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
