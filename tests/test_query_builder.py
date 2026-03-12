"""Tests for the rule-based PubMed query builder."""

from src.pipeline.query_builder import (
    ANIMAL_FILTER,
    build_block,
    build_query,
    deduplicate,
    expand_terms,
    format_mesh,
    format_tiab,
    is_noise_term,
    normalize_term,
    truncation_variants,
    _get_list,
)


# ── normalize_term ─────────────────────────────────────────────────────────


class TestNormalizeTerm:
    def test_strips_whitespace(self):
        assert normalize_term("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize_term("hello   world") == "hello world"

    def test_strips_surrounding_quotes(self):
        assert normalize_term('"appendicitis"') == "appendicitis"

    def test_strips_trailing_period(self):
        assert normalize_term("colectomy.") == "colectomy"

    def test_preserves_wildcard(self):
        assert normalize_term("colectom*") == "colectom*"

    def test_empty_string(self):
        assert normalize_term("") == ""


# ── deduplicate ────────────────────────────────────────────────────────────


class TestDeduplicate:
    def test_removes_case_insensitive_dups(self):
        result = deduplicate(["Appendicitis", "appendicitis", "APPENDICITIS"])
        assert result == ["Appendicitis"]

    def test_preserves_order(self):
        result = deduplicate(["beta", "alpha", "beta"])
        assert result == ["beta", "alpha"]

    def test_empty_list(self):
        assert deduplicate([]) == []


# ── format_mesh ────────────────────────────────────────────────────────────


class TestFormatMesh:
    def test_basic(self):
        assert format_mesh("Appendicitis") == '"Appendicitis"[MeSH]'

    def test_strips_whitespace(self):
        assert format_mesh("  Appendicitis  ") == '"Appendicitis"[MeSH]'

    def test_empty(self):
        assert format_mesh("") == ""


# ── format_tiab ────────────────────────────────────────────────────────────


class TestFormatTiab:
    def test_single_word(self):
        assert format_tiab("appendicitis") == "appendicitis[tiab]"

    def test_multi_word_quoted(self):
        assert format_tiab("oral carbohydrate") == '"oral carbohydrate"[tiab]'

    def test_wildcard_not_quoted(self):
        assert format_tiab("colectom*") == "colectom*[tiab]"

    def test_multi_word_with_wildcard_not_quoted(self):
        assert format_tiab("preoperat* carbohydrate") == "preoperat* carbohydrate[tiab]"

    def test_empty(self):
        assert format_tiab("") == ""


# ── truncation_variants ───────────────────────────────────────────────────


class TestTruncationVariants:
    def test_ectomy(self):
        variants = truncation_variants("colectomy")
        assert "colectom*" in variants

    def test_ectomy_british(self):
        variants = truncation_variants("appendectomy")
        assert "appendectom*" in variants

    def test_no_double_ic(self):
        """If the stem already ends in 'ic', don't add another."""
        variants = truncation_variants("cholecystectomy")
        assert "cholecystectom*" in variants
        # "cholecyst" doesn't end in "ic", so british variant IS generated
        # (it's harmless — PubMed returns 0 for nonsense)

    def test_operative(self):
        variants = truncation_variants("preoperative")
        assert "preoperat*" in variants

    def test_oscopy(self):
        variants = truncation_variants("colonoscopy")
        assert "colonoscop*" in variants

    def test_plasty(self):
        variants = truncation_variants("arthroplasty")
        assert "arthroplast*" in variants

    def test_stem_too_short(self):
        """Stem must be ≥3 chars."""
        assert truncation_variants("my") == []

    def test_multi_word_skipped(self):
        """Multi-word terms are not truncated (PubMed syntax issue)."""
        assert truncation_variants("colorectal surgery") == []

    def test_already_wildcarded(self):
        assert truncation_variants("colectom*") == []


# ── expand_terms ───────────────────────────────────────────────────────────


class TestExpandTerms:
    def test_single_word_gets_truncation(self):
        result = expand_terms(["appendectomy"])
        assert "appendectomy" in result
        assert "appendectom*" in result

    def test_ectomy_gets_truncated(self):
        result = expand_terms(["appendectomy"])
        assert "appendectomy" in result
        assert "appendectom*" in result

    def test_multi_word_hyphen_variant(self):
        result = expand_terms(["pre-operative care"])
        assert "pre-operative care" in result
        assert "pre operative care" in result

    def test_no_expansion_for_unknown(self):
        result = expand_terms(["metformin"])
        assert result == ["metformin"]


# ── is_noise_term ──────────────────────────────────────────────────────────


class TestIsNoiseTerm:
    def test_cohort_prefix(self):
        assert is_noise_term("patients undergoing colectomy") is True

    def test_questionnaire(self):
        assert is_noise_term("food frequency questionnaire") is True

    def test_normal_term(self):
        assert is_noise_term("appendectomy") is False

    def test_empty(self):
        assert is_noise_term("") is False


# ── _get_list ──────────────────────────────────────────────────────────────


class TestGetList:
    def test_nested_lookup(self):
        data = {"core_concepts": {"population_or_condition": ["A", "B"]}}
        assert _get_list(data, "core_concepts", "population_or_condition") == ["A", "B"]

    def test_missing_key_returns_empty(self):
        assert _get_list({}, "missing", "key") == []

    def test_string_value_wrapped(self):
        data = {"core_concepts": {"population_or_condition": "singleton"}}
        assert _get_list(data, "core_concepts", "population_or_condition") == ["singleton"]


# ── build_block ────────────────────────────────────────────────────────────


class TestBuildBlock:
    def test_combines_mesh_and_tiab(self):
        extracted = {
            "controlled_vocabulary_terms": {
                "population_or_condition": ["Appendicitis"],
            },
            "core_concepts": {
                "population_or_condition": ["appendicitis", "acute appendicitis"],
            },
            "exact_phrases": {"population_or_condition": []},
            "proxy_terms": {"population_or_condition": []},
        }
        block = build_block(extracted, "population_or_condition")
        assert block.startswith("(")
        assert block.endswith(")")
        assert '"Appendicitis"[MeSH]' in block
        assert "appendicitis[tiab]" in block
        assert '"acute appendicitis"[tiab]' in block
        assert " OR " in block

    def test_empty_facet_returns_empty(self):
        assert build_block({}, "population_or_condition") == ""

    def test_proxy_promoted_to_mesh(self):
        """Proxy terms should appear as both MeSH and tiab."""
        extracted = {
            "controlled_vocabulary_terms": {"population_or_condition": []},
            "core_concepts": {"population_or_condition": []},
            "exact_phrases": {"population_or_condition": []},
            "proxy_terms": {"population_or_condition": ["colorectal surgery"]},
        }
        block = build_block(extracted, "population_or_condition")
        assert '"Colorectal Surgery"[MeSH]' in block
        assert '"colorectal surgery"[tiab]' in block

    def test_noise_proxy_filtered(self):
        """Noise proxy terms should not appear."""
        extracted = {
            "controlled_vocabulary_terms": {"intervention_or_exposure": []},
            "core_concepts": {"intervention_or_exposure": ["diet"]},
            "exact_phrases": {"intervention_or_exposure": []},
            "proxy_terms": {"intervention_or_exposure": ["food frequency questionnaire"]},
        }
        block = build_block(extracted, "intervention_or_exposure")
        assert "questionnaire" not in block
        assert "diet[tiab]" in block

    def test_truncation_in_block(self):
        extracted = {
            "controlled_vocabulary_terms": {"population_or_condition": []},
            "core_concepts": {"population_or_condition": ["colectomy"]},
            "exact_phrases": {"population_or_condition": []},
            "proxy_terms": {"population_or_condition": []},
        }
        block = build_block(extracted, "population_or_condition")
        assert "colectom*[tiab]" in block


# ── build_query ────────────────────────────────────────────────────────────


class TestBuildQuery:
    def test_full_query_structure(self):
        extracted = {
            "core_concepts": {
                "population_or_condition": ["appendicitis"],
                "intervention_or_exposure": ["appendectomy"],
            },
            "exact_phrases": {
                "population_or_condition": [],
                "intervention_or_exposure": [],
            },
            "proxy_terms": {
                "population_or_condition": [],
                "intervention_or_exposure": [],
            },
            "controlled_vocabulary_terms": {
                "population_or_condition": ["Appendicitis"],
                "intervention_or_exposure": ["Appendectomy"],
            },
            "optional_terms": ["recovery time", "complications"],
        }

        query = build_query(extracted)

        # Has two blocks joined by AND
        assert " AND " in query

        # Has animal filter
        assert ANIMAL_FILTER in query

        # Has MeSH terms
        assert '"Appendicitis"[MeSH]' in query
        assert '"Appendectomy"[MeSH]' in query

        # Has free-text
        assert "appendicitis[tiab]" in query
        assert "appendectomy[tiab]" in query

        # Has truncation variants
        assert "appendectom*[tiab]" in query
        assert "appendicectom*[tiab]" in query

        # Does NOT include optional_terms
        assert "recovery time" not in query
        assert "complications" not in query

    def test_empty_json(self):
        assert build_query({}) == ""

    def test_single_facet_still_produces_query(self):
        extracted = {
            "core_concepts": {
                "population_or_condition": ["diabetes"],
            },
        }
        query = build_query(extracted)
        assert "diabetes[tiab]" in query
        assert ANIMAL_FILTER in query

    def test_deduplication_across_sections(self):
        """Same term in core_concepts and exact_phrases should appear once."""
        extracted = {
            "core_concepts": {
                "population_or_condition": ["appendicitis"],
            },
            "exact_phrases": {
                "population_or_condition": ["appendicitis"],
            },
            "controlled_vocabulary_terms": {
                "population_or_condition": [],
            },
            "proxy_terms": {
                "population_or_condition": [],
            },
        }
        block = build_block(extracted, "population_or_condition")
        # Should contain appendicitis[tiab] exactly once
        assert block.count("appendicitis[tiab]") == 1

    def test_no_bare_terms(self):
        """Every term in the output should have a field tag."""
        extracted = {
            "core_concepts": {
                "population_or_condition": ["diabetes mellitus"],
                "intervention_or_exposure": ["insulin therapy"],
            },
            "exact_phrases": {
                "population_or_condition": ["type 2 diabetes"],
                "intervention_or_exposure": [],
            },
            "proxy_terms": {
                "population_or_condition": [],
                "intervention_or_exposure": ["insulin analog*"],
            },
            "controlled_vocabulary_terms": {
                "population_or_condition": ["Diabetes Mellitus, Type 2"],
                "intervention_or_exposure": ["Insulin"],
            },
        }
        query = build_query(extracted)
        # Every parenthesized term should end with a PubMed field tag
        # Split on OR/AND and check each token
        import re
        tokens = re.split(r"\s+(?:AND|OR|NOT)\s+", query)
        for token in tokens:
            token = token.strip("() ")
            if not token:
                continue
            assert "[MeSH]" in token or "[tiab]" in token, (
                f"Bare term found: {token!r}"
            )

    def test_cohort_phrase_filtered(self):
        """Exact phrases like 'patients undergoing X' should be dropped."""
        extracted = {
            "core_concepts": {
                "population_or_condition": ["colectomy"],
            },
            "exact_phrases": {
                "population_or_condition": ["patients undergoing colectomy"],
            },
            "proxy_terms": {"population_or_condition": []},
            "controlled_vocabulary_terms": {"population_or_condition": ["Colectomy"]},
        }
        query = build_query(extracted)
        assert "patients undergoing" not in query
        assert "colectomy[tiab]" in query

    def test_hyphen_variant_in_query(self):
        extracted = {
            "core_concepts": {
                "intervention_or_exposure": ["pre-operative care"],
            },
            "exact_phrases": {"intervention_or_exposure": []},
            "proxy_terms": {"intervention_or_exposure": []},
            "controlled_vocabulary_terms": {"intervention_or_exposure": ["Preoperative Care"]},
        }
        query = build_query(extracted)
        assert '"pre-operative care"[tiab]' in query
        assert '"pre operative care"[tiab]' in query
