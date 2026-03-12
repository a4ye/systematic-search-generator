"""Execute PubMed queries via Entrez API."""

import time
from dataclasses import dataclass, field
from datetime import datetime
from http.client import IncompleteRead, RemoteDisconnected
from typing import Any
from urllib.error import HTTPError, URLError

from Bio import Entrez, Medline


@dataclass
class PubMedSearchResults:
    """Results from a PubMed search."""

    query: str
    records: list[dict[str, Any]]
    result_count: int
    execution_time: float
    executed_at: datetime = field(default_factory=datetime.now)

    # Lookup maps built from records
    doi_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    pmid_map: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        """Build lookup maps from records."""
        self._build_maps()

    def _build_maps(self) -> None:
        """Build DOI and PMID lookup maps from records."""
        for rec in self.records:
            pmid = rec.get("PMID", "")
            title = rec.get("TI", "")
            dois = set()

            # Extract DOIs from AID field (list of "value [type]" entries)
            for aid in rec.get("AID", []):
                if "[doi]" in aid:
                    doi = aid.replace("[doi]", "").strip()
                    dois.add(doi.lower())

            # Also check LID field
            lid = rec.get("LID", "")
            if isinstance(lid, list):
                lid = " ".join(lid)
            if "[doi]" in lid:
                doi = lid.split("[doi]")[0].strip()
                dois.add(doi.lower())

            # Store in PMID map
            if pmid:
                self.pmid_map[pmid] = {"pmid": pmid, "title": title, "dois": list(dois)}

            # Store in DOI map
            for doi in dois:
                self.doi_map[doi] = {"pmid": pmid, "title": title}

    def match_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Try to match a DOI."""
        return self.doi_map.get(doi.lower())

    def match_by_pmid(self, pmid: str) -> dict[str, Any] | None:
        """Try to match a PMID."""
        return self.pmid_map.get(pmid)

    @classmethod
    def from_cached(
        cls,
        query: str,
        pmids: list[str],
        result_count: int,
        doi_to_pmid: dict[str, str],
    ) -> "PubMedSearchResults":
        """Create a PubMedSearchResults from cached data.

        This creates a minimal result that can match PMIDs and DOIs
        without having full record data.
        """
        instance = cls(
            query=query,
            records=[],  # No full records needed for matching
            result_count=result_count,
            execution_time=0.0,
        )
        # Populate maps from cached data
        for pmid in pmids:
            instance.pmid_map[pmid] = {"pmid": pmid, "title": "(cached)"}
        for doi, pmid in doi_to_pmid.items():
            instance.doi_map[doi.lower()] = {"pmid": pmid, "title": "(cached)"}
        return instance


class PubMedExecutor:
    """Execute queries on PubMed via Entrez API."""

    def __init__(
        self,
        email: str,
        api_key: str | None = None,
        batch_size: int = 200,
    ):
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
        self.batch_size = batch_size
        # Rate limit: 3/sec without API key, 10/sec with API key
        self.rate_limit_delay = 0.1 if api_key else 0.34
        self.max_retries = 4

    def _entrez_call_with_retry(self, fn, **kwargs):
        """Call an Entrez function with retry/backoff for transient failures."""
        for attempt in range(self.max_retries):
            try:
                return fn(**kwargs)
            except (URLError, RemoteDisconnected, IncompleteRead, TimeoutError, ConnectionError, OSError) as exc:
                if attempt >= self.max_retries - 1:
                    raise
                # Exponential backoff capped at 8s
                time.sleep(min(2 ** attempt, 8))
            except HTTPError as exc:
                # Syntax / bad request should fail fast
                if exc.code in (400, 404):
                    raise
                if attempt >= self.max_retries - 1:
                    raise
                time.sleep(min(2 ** attempt, 8))

    def count_results(self, query: str) -> int:
        """Get result count without downloading records."""
        handle = self._entrez_call_with_retry(Entrez.esearch, db="pubmed", term=query, retmax=0)
        results = Entrez.read(handle)
        handle.close()
        return int(results.get("Count", 0))

    def execute_query(
        self,
        query: str,
        max_results: int = 10000,
    ) -> PubMedSearchResults:
        """Execute query and return results."""
        start_time = time.time()

        # First, search to get IDs
        handle = self._entrez_call_with_retry(
            Entrez.esearch,
            db="pubmed",
            term=query,
            retmax=max_results,
            usehistory="y",
        )
        search_results = Entrez.read(handle)
        handle.close()

        id_list = search_results.get("IdList", [])
        total_count = int(search_results.get("Count", 0))
        webenv = search_results.get("WebEnv")
        query_key = search_results.get("QueryKey")

        if not id_list:
            return PubMedSearchResults(
                query=query,
                records=[],
                result_count=total_count,
                execution_time=time.time() - start_time,
            )

        # Fetch records in batches using history
        all_records: list[dict[str, Any]] = []

        for start in range(0, len(id_list), self.batch_size):
            time.sleep(self.rate_limit_delay)

            handle = self._entrez_call_with_retry(
                Entrez.efetch,
                db="pubmed",
                rettype="medline",
                retmode="text",
                retstart=start,
                retmax=self.batch_size,
                webenv=webenv,
                query_key=query_key,
            )

            records = list(Medline.parse(handle))
            handle.close()
            all_records.extend(records)

        execution_time = time.time() - start_time

        return PubMedSearchResults(
            query=query,
            records=all_records,
            result_count=total_count,
            execution_time=execution_time,
        )

    def execute_query_fast(
        self,
        query: str,
        max_results: int = 10000,
    ) -> PubMedSearchResults:
        """Execute query and return results using lightweight esummary.

        This is much faster than execute_query() because it uses esummary
        instead of fetching full MEDLINE records. Only PMIDs and DOIs are
        retrieved, which is sufficient for matching against included studies.
        """
        start_time = time.time()

        # First, search to get IDs
        handle = self._entrez_call_with_retry(
            Entrez.esearch,
            db="pubmed",
            term=query,
            retmax=max_results,
            usehistory="y",
        )
        search_results = Entrez.read(handle)
        handle.close()

        id_list = search_results.get("IdList", [])
        total_count = int(search_results.get("Count", 0))
        webenv = search_results.get("WebEnv")
        query_key = search_results.get("QueryKey")

        if not id_list:
            return PubMedSearchResults(
                query=query,
                records=[],
                result_count=total_count,
                execution_time=time.time() - start_time,
            )

        # Use esummary to get DOIs (much lighter than full MEDLINE)
        pmid_to_doi: dict[str, str] = {}

        for start in range(0, len(id_list), self.batch_size):
            time.sleep(self.rate_limit_delay)

            handle = self._entrez_call_with_retry(
                Entrez.esummary,
                db="pubmed",
                retstart=start,
                retmax=self.batch_size,
                webenv=webenv,
                query_key=query_key,
            )
            summaries = Entrez.read(handle)
            handle.close()

            # Extract DOIs from summaries
            for summary in summaries:
                if isinstance(summary, dict):
                    pmid = str(summary.get("Id", ""))
                    # DOI can be in ArticleIds or elocationid
                    article_ids = summary.get("ArticleIds", {})
                    doi = article_ids.get("doi", "")
                    if not doi:
                        # Try elocationid field
                        eloc = summary.get("elocationid", "")
                        if eloc and eloc.startswith("doi:"):
                            doi = eloc[4:].strip()
                    if pmid and doi:
                        pmid_to_doi[pmid] = doi.lower()

        execution_time = time.time() - start_time

        # Build minimal result with just PMIDs and DOIs
        result = PubMedSearchResults(
            query=query,
            records=[],
            result_count=total_count,
            execution_time=execution_time,
        )

        # Populate maps directly
        for pmid in id_list:
            doi = pmid_to_doi.get(pmid)
            result.pmid_map[pmid] = {"pmid": pmid, "title": "(fast)", "dois": [doi] if doi else []}
            if doi:
                result.doi_map[doi] = {"pmid": pmid, "title": "(fast)"}

        return result

    def validate_query_captures_pmids(
        self,
        query: str,
        pmids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Check which PMIDs a query captures.

        Tests the query against known PMIDs by searching:
        (query) AND (pmid1[uid] OR pmid2[uid] OR ...)

        Args:
            query: PubMed query to test
            pmids: List of PMIDs that should be in results

        Returns:
            Tuple of (found_pmids, missed_pmids)
        """
        if not pmids:
            return [], []

        # Build a query that intersects with the target PMIDs
        # Process in batches to avoid query length limits
        all_found: set[str] = set()
        batch_size = 50  # PMIDs per validation batch

        for start in range(0, len(pmids), batch_size):
            time.sleep(self.rate_limit_delay)
            batch = pmids[start:start + batch_size]

            pmid_filter = " OR ".join(f"{p}[uid]" for p in batch)
            validation_query = f"({query}) AND ({pmid_filter})"

            try:
                handle = self._entrez_call_with_retry(
                    Entrez.esearch,
                    db="pubmed",
                    term=validation_query,
                    retmax=len(batch),
                )
                results = Entrez.read(handle)
                handle.close()

                found_ids = results.get("IdList", [])
                all_found.update(found_ids)
            except Exception:
                # If validation fails, assume all found (don't block generation)
                all_found.update(batch)

        found = [p for p in pmids if p in all_found]
        missed = [p for p in pmids if p not in all_found]
        return found, missed

    def fetch_by_pmids(self, pmids: list[str]) -> list[dict[str, Any]]:
        """Fetch records by PMID list."""
        if not pmids:
            return []

        all_records: list[dict[str, Any]] = []

        for start in range(0, len(pmids), self.batch_size):
            time.sleep(self.rate_limit_delay)
            batch = pmids[start:start + self.batch_size]

            handle = Entrez.efetch(
                db="pubmed",
                id=",".join(batch),
                rettype="medline",
                retmode="text",
            )
            records = list(Medline.parse(handle))
            handle.close()
            all_records.extend(records)

        return all_records
