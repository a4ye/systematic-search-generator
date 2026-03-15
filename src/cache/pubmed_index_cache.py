"""Cache for PubMed indexing status of studies."""

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path


def _normalize_doi_key(doi: str) -> str:
    """Normalize DOI for cache key consistency."""
    doi = doi.strip().rstrip(".")
    doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
    # Collapse double (or more) slashes to single, only in the suffix after "10.xxx/"
    prefix_end = doi.find("/")
    if prefix_end > 0:
        prefix = doi[:prefix_end]
        suffix = doi[prefix_end:]
        suffix = re.sub(r"/{2,}", "/", suffix)
        doi = prefix + suffix
    return doi.lower()


@dataclass
class IndexStatus:
    """PubMed indexing status for a study."""

    indexed: bool
    checked_at: float  # Unix timestamp


class PubMedIndexCache:
    """Cache for storing whether studies are indexed in PubMed.

    Studies don't get de-indexed from PubMed, so this cache can be
    long-lived. We store by both DOI and PMID for flexible lookups.
    """

    CACHE_FILE = "pubmed_index_cache.json"

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / self.CACHE_FILE
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

    def _make_key(self, doi: str | None, pmid: str | None) -> str | None:
        """Create a cache key from DOI or PMID."""
        if pmid:
            return f"pmid:{pmid}"
        if doi:
            return f"doi:{_normalize_doi_key(doi)}"
        return None

    def get(self, doi: str | None = None, pmid: str | None = None) -> bool | None:
        """Get cached indexing status for a study.

        Returns True/False if cached, None if not in cache.
        """
        key = self._make_key(doi, pmid)
        if key and key in self._cache:
            return self._cache[key]["indexed"]
        return None

    def set(
        self, indexed: bool, doi: str | None = None, pmid: str | None = None, save: bool = True
    ) -> None:
        """Cache indexing status for a study.

        Args:
            indexed: Whether the study is indexed in PubMed
            doi: DOI of the study
            pmid: PMID of the study
            save: Whether to save to disk immediately (set False for batch operations)
        """
        key = self._make_key(doi, pmid)
        if key:
            self._cache[key] = {
                "indexed": indexed,
                "checked_at": time.time(),
            }
            if save:
                self._save()

    def save(self) -> None:
        """Explicitly save cache to disk. Use after batch set() calls with save=False."""
        self._save()

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = len(self._cache)
        indexed = sum(1 for v in self._cache.values() if v["indexed"])
        return {
            "total_entries": total,
            "indexed_count": indexed,
            "not_indexed_count": total - indexed,
        }
