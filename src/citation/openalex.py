"""OpenAlex API client for forward/backward citation searching."""

import logging
import time
from dataclasses import dataclass, field
import re

import requests

from src.cache.citation_cache import CitationCache

logger = logging.getLogger(__name__)

# OpenAlex returns PMIDs as full URLs
_PMID_PREFIX = "https://pubmed.ncbi.nlm.nih.gov/"
_OPENALEX_PREFIX = "https://openalex.org/"
_DOI_PREFIX_RE = re.compile(r"^https?://doi\\.org/", re.IGNORECASE)


def _extract_pmid(ids: dict) -> str | None:
    """Extract bare PMID string from OpenAlex ids dict."""
    pmid_url = ids.get("pmid")
    if pmid_url and pmid_url.startswith(_PMID_PREFIX):
        return pmid_url[len(_PMID_PREFIX):]
    return None


def _extract_doi(ids: dict) -> str | None:
    """Extract bare DOI string from OpenAlex ids dict."""
    doi = ids.get("doi")
    if not doi:
        return None
    doi = _DOI_PREFIX_RE.sub("", doi).strip()
    return doi.lower() if doi else None


def _normalize_openalex_id(openalex_id: str) -> str:
    """Normalize OpenAlex IDs to bare form (no URL prefix)."""
    if openalex_id.startswith(_OPENALEX_PREFIX):
        return openalex_id[len(_OPENALEX_PREFIX):]
    return openalex_id


@dataclass
class CitationResult:
    """Result of citation searching for a single seed paper."""

    pmid: str
    forward_pmids: set[str] = field(default_factory=set)
    backward_pmids: set[str] = field(default_factory=set)

    @property
    def all_pmids(self) -> set[str]:
        return self.forward_pmids | self.backward_pmids


class OpenAlexClient:
    """Client for fetching citation data from OpenAlex."""

    BASE_URL = "https://api.openalex.org"

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        rate_delay: float = 0.2,
    ):
        self.session = requests.Session()
        self.email = email
        self.api_key = api_key
        if email:
            self.session.headers["User-Agent"] = f"mailto:{email}"
        self.rate_delay = rate_delay

    def _get(self, endpoint: str, params: dict | None = None, _retries: int = 3) -> dict | None:
        """Make a GET request to OpenAlex with rate limiting and retry on 429."""
        time.sleep(self.rate_delay)
        url = f"{self.BASE_URL}{endpoint}"
        params = dict(params) if params else {}
        if self.api_key and "api_key" not in params:
            params["api_key"] = self.api_key
        if self.email and "mailto" not in params:
            params["mailto"] = self.email
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 and _retries > 0:
                wait = max(float(resp.headers.get("Retry-After", 2)), 2.0)
                logger.info("Rate limited, waiting %.1fs (%d retries left)", wait, _retries)
                time.sleep(wait)
                return self._get(endpoint, params, _retries=_retries - 1)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("OpenAlex request failed: %s %s — %s", endpoint, params, e)
            return None

    def _get_openalex_id(self, pmid: str) -> str | None:
        """Look up the OpenAlex ID for a PMID."""
        data = self._get(f"/works/pmid:{pmid}", params={"select": "id,referenced_works"})
        if data:
            return data.get("id"), data.get("referenced_works", [])
        return None, []

    def _get_openalex_id_by_doi(self, doi: str) -> tuple[str | None, list[str], str | None]:
        """Look up the OpenAlex ID and PMID for a DOI.

        Returns (openalex_id, referenced_works, pmid).
        """
        data = self._get(
            f"/works/doi:{doi}",
            params={"select": "id,ids,referenced_works"},
        )
        if data:
            pmid = _extract_pmid(data.get("ids", {}))
            return data.get("id"), data.get("referenced_works", []), pmid
        return None, [], None

    def resolve_doi_to_pmid(self, doi: str) -> str | None:
        """Resolve a DOI to a PMID via OpenAlex."""
        data = self._get(f"/works/doi:{doi}", params={"select": "ids"})
        if data:
            return _extract_pmid(data.get("ids", {}))
        return None

    def resolve_pmids_to_dois(self, pmids: list[str]) -> dict[str, str]:
        """Resolve PMIDs to DOIs using OpenAlex batch filter."""
        pmid_to_doi: dict[str, str] = {}
        if not pmids:
            return pmid_to_doi

        batch_size = 50
        for i in range(0, len(pmids), batch_size):
            batch = pmids[i : i + batch_size]
            filter_str = "pmid:" + "|".join(batch)
            data = self._get("/works", params={
                "filter": filter_str,
                "select": "ids",
                "per_page": 200,
            })
            if not data:
                continue
            for work in data.get("results", []):
                ids = work.get("ids", {})
                pmid = _extract_pmid(ids)
                doi = _extract_doi(ids)
                if pmid and doi:
                    pmid_to_doi[pmid] = doi
        return pmid_to_doi

    def _resolve_openalex_ids_to_pmids(self, openalex_ids: list[str]) -> set[str]:
        """Resolve a list of OpenAlex work IDs to PMIDs in batches."""
        pmids = set()
        # Strip URL prefix to get bare IDs for the filter
        bare_ids = [_normalize_openalex_id(oa_id) for oa_id in openalex_ids]

        # OpenAlex filter supports pipe-separated IDs, batch in groups of 50
        batch_size = 50
        for i in range(0, len(bare_ids), batch_size):
            batch = bare_ids[i : i + batch_size]
            filter_str = "|".join(batch)
            data = self._get("/works", params={
                "filter": f"openalex:{filter_str}",
                "select": "ids",
                "per_page": 200,
            })
            if data:
                for work in data.get("results", []):
                    pmid = _extract_pmid(work.get("ids", {}))
                    if pmid:
                        pmids.add(pmid)
        return pmids

    def resolve_openalex_ids_to_dois(self, openalex_ids: list[str]) -> dict[str, str]:
        """Resolve a list of OpenAlex work IDs to DOIs in batches."""
        id_to_doi: dict[str, str] = {}
        if not openalex_ids:
            return id_to_doi

        bare_ids = [_normalize_openalex_id(oa_id) for oa_id in openalex_ids]

        batch_size = 50
        for i in range(0, len(bare_ids), batch_size):
            batch = bare_ids[i : i + batch_size]
            filter_str = "|".join(batch)
            data = self._get("/works", params={
                "filter": f"openalex:{filter_str}",
                "select": "id,ids",
                "per_page": 200,
            })
            if data:
                for work in data.get("results", []):
                    oa_id = work.get("id")
                    doi = _extract_doi(work.get("ids", {}))
                    if oa_id and doi:
                        id_to_doi[oa_id] = doi
        return id_to_doi

    def _get_forward_citations_with_ids(
        self, openalex_id: str, max_results: int = 2000
    ) -> tuple[set[str], list[str]]:
        """Get PMIDs and OpenAlex IDs of papers that cite the given work."""
        pmids = set()
        oa_ids: list[str] = []
        # Strip prefix for filter
        bare_id = _normalize_openalex_id(openalex_id)

        per_page = 200
        cursor = "*"
        fetched = 0

        while fetched < max_results:
            data = self._get("/works", params={
                "filter": f"cites:{bare_id}",
                "select": "id,ids",
                "per_page": per_page,
                "cursor": cursor,
            })
            if not data:
                break

            results = data.get("results", [])
            if not results:
                break

            for work in results:
                oa_id = work.get("id")
                if oa_id:
                    oa_ids.append(oa_id)
                pmid = _extract_pmid(work.get("ids", {}))
                if pmid:
                    pmids.add(pmid)

            fetched += len(results)
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor:
                break

        return pmids, oa_ids

    def _get_forward_citations(self, openalex_id: str, max_results: int = 2000) -> set[str]:
        """Get PMIDs of papers that cite the given work."""
        pmids, _ = self._get_forward_citations_with_ids(openalex_id, max_results=max_results)
        return pmids

    def get_citations(
        self,
        pmid: str,
        cache: CitationCache | None = None,
        max_forward: int = 2000,
    ) -> CitationResult:
        """Get forward and backward citations for a PMID.

        Uses cache if available. Returns CitationResult with sets of PMIDs.
        """
        # Check cache first
        if cache:
            cached = cache.get(pmid)
            if cached:
                return CitationResult(
                    pmid=pmid,
                    forward_pmids=set(cached["forward_pmids"]),
                    backward_pmids=set(cached["backward_pmids"]),
                )

        result = CitationResult(pmid=pmid)

        # Look up the paper in OpenAlex
        openalex_id, referenced_works = self._get_openalex_id(pmid)
        if not openalex_id:
            logger.info("PMID %s not found in OpenAlex", pmid)
            # Cache empty result to avoid re-fetching
            if cache:
                cache.set(pmid, [], [], save=False)
            return result

        # Backward citations: resolve referenced_works to PMIDs
        if referenced_works:
            result.backward_pmids = self._resolve_openalex_ids_to_pmids(referenced_works)

        # Forward citations: papers that cite this work
        result.forward_pmids = self._get_forward_citations(openalex_id, max_results=max_forward)

        # Cache the result
        if cache:
            cache.set(
                pmid,
                sorted(result.forward_pmids),
                sorted(result.backward_pmids),
                save=False,
            )

        return result

    def get_citations_with_work_ids(
        self,
        pmid: str,
        cache: CitationCache | None = None,
        max_forward: int = 2000,
        direction: str = "both",
    ) -> tuple[CitationResult, list[str], bool]:
        """Get citation PMIDs and OpenAlex work IDs for a PMID."""
        cached_result: CitationResult | None = None
        if cache:
            cached = cache.get(pmid)
            if cached:
                cached_result = CitationResult(
                    pmid=pmid,
                    forward_pmids=set(cached["forward_pmids"]),
                    backward_pmids=set(cached["backward_pmids"]),
                )

        result = cached_result or CitationResult(pmid=pmid)

        openalex_id, referenced_works = self._get_openalex_id(pmid)
        if not openalex_id:
            logger.info("PMID %s not found in OpenAlex", pmid)
            if cache and not cached_result:
                cache.set(pmid, [], [], save=False)
            return result, [], False

        forward_pmids: set[str] = set()
        forward_ids: list[str] = []
        if direction in ("both", "forward"):
            forward_pmids, forward_ids = self._get_forward_citations_with_ids(
                openalex_id, max_results=max_forward
            )
            if not cached_result:
                result.forward_pmids = forward_pmids
        elif not cached_result:
            result.forward_pmids = set()

        if direction in ("both", "backward"):
            if referenced_works and not cached_result:
                result.backward_pmids = self._resolve_openalex_ids_to_pmids(referenced_works)
        elif not cached_result:
            result.backward_pmids = set()

        if cache and not cached_result:
            cache.set(
                pmid,
                sorted(result.forward_pmids),
                sorted(result.backward_pmids),
                save=False,
            )

        all_ids = []
        if direction in ("both", "backward") and referenced_works:
            all_ids.extend(referenced_works)
        if direction in ("both", "forward") and forward_ids:
            all_ids.extend(forward_ids)
        return result, all_ids, True

    def get_citations_by_doi(
        self,
        doi: str,
        cache: CitationCache | None = None,
        max_forward: int = 2000,
    ) -> tuple[CitationResult, str | None]:
        """Get forward and backward citations for a DOI.

        Returns (CitationResult, resolved_pmid). The cache key is the
        resolved PMID when available, otherwise the DOI prefixed with "doi:".
        """
        # Look up in OpenAlex by DOI to get openalex_id, referenced_works, and PMID
        openalex_id, referenced_works, resolved_pmid = self._get_openalex_id_by_doi(doi)

        # Determine cache key: prefer resolved PMID, fall back to "doi:<doi>"
        cache_key = resolved_pmid or f"doi:{doi.lower()}"

        # Check cache
        if cache:
            cached = cache.get(cache_key)
            if cached:
                return CitationResult(
                    pmid=cache_key,
                    forward_pmids=set(cached["forward_pmids"]),
                    backward_pmids=set(cached["backward_pmids"]),
                ), resolved_pmid

        result = CitationResult(pmid=cache_key)

        if not openalex_id:
            logger.info("DOI %s not found in OpenAlex", doi)
            if cache:
                cache.set(cache_key, [], [], save=False)
            return result, resolved_pmid

        # Backward citations
        if referenced_works:
            result.backward_pmids = self._resolve_openalex_ids_to_pmids(referenced_works)

        # Forward citations
        result.forward_pmids = self._get_forward_citations(openalex_id, max_results=max_forward)

        if cache:
            cache.set(
                cache_key,
                sorted(result.forward_pmids),
                sorted(result.backward_pmids),
                save=False,
            )

        return result, resolved_pmid

    def get_citations_with_work_ids_by_doi(
        self,
        doi: str,
        cache: CitationCache | None = None,
        max_forward: int = 2000,
        direction: str = "both",
    ) -> tuple[CitationResult, list[str], bool, str | None]:
        """Get citation PMIDs and OpenAlex work IDs for a DOI.

        Returns (CitationResult, work_ids, found, resolved_pmid).
        """
        openalex_id, referenced_works, resolved_pmid = self._get_openalex_id_by_doi(doi)
        cache_key = resolved_pmid or f"doi:{doi.lower()}"

        cached_result: CitationResult | None = None
        if cache:
            cached = cache.get(cache_key)
            if cached:
                cached_result = CitationResult(
                    pmid=cache_key,
                    forward_pmids=set(cached["forward_pmids"]),
                    backward_pmids=set(cached["backward_pmids"]),
                )

        result = cached_result or CitationResult(pmid=cache_key)

        if not openalex_id:
            logger.info("DOI %s not found in OpenAlex", doi)
            if cache and not cached_result:
                cache.set(cache_key, [], [], save=False)
            return result, [], False, resolved_pmid

        forward_pmids: set[str] = set()
        forward_ids: list[str] = []
        if direction in ("both", "forward"):
            forward_pmids, forward_ids = self._get_forward_citations_with_ids(
                openalex_id, max_results=max_forward
            )
            if not cached_result:
                result.forward_pmids = forward_pmids
        elif not cached_result:
            result.forward_pmids = set()

        if direction in ("both", "backward"):
            if referenced_works and not cached_result:
                result.backward_pmids = self._resolve_openalex_ids_to_pmids(referenced_works)
        elif not cached_result:
            result.backward_pmids = set()

        if cache and not cached_result:
            cache.set(
                cache_key,
                sorted(result.forward_pmids),
                sorted(result.backward_pmids),
                save=False,
            )

        all_ids = []
        if direction in ("both", "backward") and referenced_works:
            all_ids.extend(referenced_works)
        if direction in ("both", "forward") and forward_ids:
            all_ids.extend(forward_ids)
        return result, all_ids, True, resolved_pmid

    def get_citations_for_work_id(
        self,
        openalex_id: str,
        max_forward: int = 2000,
        direction: str = "both",
    ) -> tuple[set[str], list[str]]:
        """Get citation PMIDs and OpenAlex work IDs for a work ID."""
        bare_id = _normalize_openalex_id(openalex_id)
        data = self._get(f"/works/{bare_id}", params={"select": "id,referenced_works"})
        referenced_works = data.get("referenced_works", []) if data else []

        backward_pmids = set()
        forward_pmids = set()
        forward_ids: list[str] = []
        if direction in ("both", "backward") and referenced_works:
            backward_pmids = self._resolve_openalex_ids_to_pmids(referenced_works)
        if direction in ("both", "forward"):
            forward_pmids, forward_ids = self._get_forward_citations_with_ids(
                openalex_id, max_results=max_forward
            )

        all_ids: list[str] = []
        if direction in ("both", "backward") and referenced_works:
            all_ids.extend(referenced_works)
        if direction in ("both", "forward") and forward_ids:
            all_ids.extend(forward_ids)

        return backward_pmids | forward_pmids, all_ids
