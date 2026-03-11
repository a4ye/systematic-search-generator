"""Cache for PubMed query results."""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CachedQueryResult:
    """Cached PubMed query result."""

    query_hash: str
    pmids: list[str]
    result_count: int
    doi_to_pmid: dict[str, str]  # Maps DOI -> PMID for matching
    cached_at: float
    ttl_days: int

    @property
    def is_expired(self) -> bool:
        """Check if this cached result has expired."""
        age_seconds = time.time() - self.cached_at
        age_days = age_seconds / (24 * 60 * 60)
        return age_days > self.ttl_days


class QueryResultsCache:
    """Cache for PubMed query results.

    Stores the PMIDs returned by a query, keyed by query hash.
    Includes TTL since PubMed database updates daily.
    """

    CACHE_FILE = "query_results_cache.json"
    DEFAULT_TTL_DAYS = 7

    def __init__(self, cache_dir: Path, ttl_days: int = DEFAULT_TTL_DAYS):
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / self.CACHE_FILE
        self.ttl_days = ttl_days
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self._cache, f, indent=2)

    def _hash_query(self, query: str) -> str:
        """Create a hash of the query string."""
        normalized = query.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, query: str) -> CachedQueryResult | None:
        """Get cached results for a query.

        Returns None if not cached or expired.
        """
        query_hash = self._hash_query(query)
        if query_hash not in self._cache:
            return None

        entry = self._cache[query_hash]
        result = CachedQueryResult(
            query_hash=query_hash,
            pmids=entry["pmids"],
            result_count=entry["result_count"],
            doi_to_pmid=entry.get("doi_to_pmid", {}),
            cached_at=entry["cached_at"],
            ttl_days=entry.get("ttl_days", self.ttl_days),
        )

        if result.is_expired:
            # Remove expired entry
            del self._cache[query_hash]
            self._save()
            return None

        return result

    def set(
        self,
        query: str,
        pmids: list[str],
        result_count: int,
        doi_to_pmid: dict[str, str] | None = None,
    ) -> None:
        """Cache results for a query."""
        query_hash = self._hash_query(query)
        self._cache[query_hash] = {
            "pmids": pmids,
            "result_count": result_count,
            "doi_to_pmid": doi_to_pmid or {},
            "cached_at": time.time(),
            "ttl_days": self.ttl_days,
        }
        self._save()

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = time.time()
        expired_keys = []

        for key, entry in self._cache.items():
            age_seconds = now - entry["cached_at"]
            age_days = age_seconds / (24 * 60 * 60)
            ttl = entry.get("ttl_days", self.ttl_days)
            if age_days > ttl:
                expired_keys.append(key)

        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            self._save()

        return len(expired_keys)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "total_entries": len(self._cache),
            "ttl_days": self.ttl_days,
        }
