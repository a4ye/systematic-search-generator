"""MeSH term expansion using NCBI E-utilities."""

import time
from dataclasses import dataclass, field
from urllib.error import HTTPError

from Bio import Entrez


@dataclass
class MeSHMatch:
    """A matched MeSH term with metadata."""

    term: str
    ui: str  # MeSH Unique Identifier
    tree_numbers: list[str] = field(default_factory=list)
    scope_note: str = ""


@dataclass
class MeSHExpansion:
    """Results of expanding a concept to MeSH terms."""

    query_term: str
    exact_matches: list[MeSHMatch] = field(default_factory=list)
    related_terms: list[MeSHMatch] = field(default_factory=list)


class MeSHExpander:
    """Expand natural language concepts to MeSH terms using NCBI E-utilities."""

    def __init__(self, email: str, api_key: str | None = None):
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
        # More conservative rate limiting
        self.rate_limit_delay = 0.35 if api_key else 0.5
        self.max_retries = 3

    def _call_with_retry(self, func, *args, **kwargs):
        """Call an Entrez function with retry logic for rate limits."""
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.rate_limit_delay)
                return func(*args, **kwargs)
            except HTTPError as e:
                if e.code == 429:
                    # Rate limited - exponential backoff
                    wait_time = (2 ** attempt) * 2  # 2, 4, 8 seconds
                    time.sleep(wait_time)
                    continue
                raise
        # Final attempt without catching
        time.sleep(self.rate_limit_delay * 2)
        return func(*args, **kwargs)

    def search_mesh(self, term: str, max_results: int = 5) -> list[MeSHMatch]:
        """Search MeSH database for terms matching a query.

        Args:
            term: Natural language term to search for
            max_results: Maximum number of results to return

        Returns:
            List of matching MeSH terms
        """
        if not term or not term.strip():
            return []

        try:
            # Search the MeSH database
            handle = self._call_with_retry(
                Entrez.esearch,
                db="mesh",
                term=term,
                retmax=max_results,
            )
            search_results = Entrez.read(handle)
            handle.close()

            id_list = search_results.get("IdList", [])
            if not id_list:
                return []

            # Use esummary instead of efetch - more reliable for MeSH
            handle = self._call_with_retry(
                Entrez.esummary,
                db="mesh",
                id=",".join(id_list),
            )
            summaries = Entrez.read(handle)
            handle.close()

            matches = []
            for summary in summaries:
                if not isinstance(summary, dict):
                    continue

                # Extract the descriptor name from DS_MeshTerms or other fields
                name = ""
                ui = str(summary.get("Id", ""))

                # Try different field names that might contain the term
                mesh_terms = summary.get("DS_MeshTerms", [])
                if mesh_terms and isinstance(mesh_terms, list):
                    name = mesh_terms[0] if mesh_terms else ""
                elif "DS_MeshTerms" in summary:
                    name = str(summary["DS_MeshTerms"])

                # Fallback to other fields
                if not name:
                    name = summary.get("Title", "") or summary.get("Item", "")

                # Get scope note if available
                scope_note = summary.get("DS_ScopeNote", "")
                if isinstance(scope_note, list):
                    scope_note = scope_note[0] if scope_note else ""

                if name:
                    matches.append(MeSHMatch(
                        term=str(name),
                        ui=ui,
                        tree_numbers=[],
                        scope_note=str(scope_note)[:200] if scope_note else "",
                    ))

            return matches

        except Exception as e:
            # Log but don't fail - return empty list
            import sys
            print(f"MeSH search warning for '{term}': {e}", file=sys.stderr)
            return []

    def expand_concept(
        self,
        concept: str,
        synonyms: list[str] | None = None,
        max_per_term: int = 5,
    ) -> MeSHExpansion:
        """Expand a concept and its synonyms to MeSH terms.

        Args:
            concept: Main concept to expand
            synonyms: Optional list of synonyms to also search
            max_per_term: Max MeSH matches per search term

        Returns:
            MeSHExpansion with exact and related matches
        """
        all_terms = [concept] if concept else []
        if synonyms:
            all_terms.extend([s for s in synonyms[:5] if s])

        seen_uis = set()
        exact_matches = []
        related_terms = []

        for term in all_terms:
            matches = self.search_mesh(term, max_results=max_per_term)

            for match in matches:
                if match.ui in seen_uis:
                    continue
                seen_uis.add(match.ui)

                # Check if it's an exact match (term appears in MeSH name)
                term_lower = term.lower()
                mesh_lower = match.term.lower()
                if term_lower in mesh_lower or mesh_lower in term_lower:
                    exact_matches.append(match)
                else:
                    related_terms.append(match)

        return MeSHExpansion(
            query_term=concept or "",
            exact_matches=exact_matches,
            related_terms=related_terms,
        )

    def expand_pico_elements(
        self,
        population_main: str,
        population_synonyms: list[str],
        intervention_main: str,
        intervention_synonyms: list[str],
    ) -> dict[str, list[str]]:
        """Expand PICO elements to MeSH terms.

        Args:
            population_main: Main population concept
            population_synonyms: Population synonyms
            intervention_main: Main intervention concept
            intervention_synonyms: Intervention synonyms

        Returns:
            Dict with 'population' and 'intervention' keys mapping to MeSH term lists
        """
        result: dict[str, list[str]] = {"population": [], "intervention": []}

        # Expand population
        if population_main:
            pop_expansion = self.expand_concept(population_main, population_synonyms)
            for match in pop_expansion.exact_matches + pop_expansion.related_terms[:3]:
                if match.term not in result["population"]:
                    result["population"].append(match.term)

        # Expand intervention
        if intervention_main:
            int_expansion = self.expand_concept(intervention_main, intervention_synonyms)
            for match in int_expansion.exact_matches + int_expansion.related_terms[:3]:
                if match.term not in result["intervention"]:
                    result["intervention"].append(match.term)

        return result
