"""Cache for OpenAlex citation data."""

import json
import time
from pathlib import Path


class CitationCache:
    """Cache for forward/backward citations from OpenAlex.

    Citations change slowly, so this cache has no TTL.
    Keyed by PMID.
    """

    CACHE_FILE = "citation_cache.json"

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / self.CACHE_FILE
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self._cache, f, indent=2)

    def get(self, pmid: str) -> dict | None:
        """Get cached citations for a PMID.

        Returns dict with 'forward_pmids' and 'backward_pmids' lists,
        or None if not cached.
        """
        entry = self._cache.get(pmid)
        if entry:
            return {
                "forward_pmids": entry["forward_pmids"],
                "backward_pmids": entry["backward_pmids"],
            }
        return None

    def set(
        self,
        pmid: str,
        forward_pmids: list[str],
        backward_pmids: list[str],
        save: bool = True,
    ) -> None:
        self._cache[pmid] = {
            "forward_pmids": forward_pmids,
            "backward_pmids": backward_pmids,
            "cached_at": time.time(),
        }
        if save:
            self._save()

    def save(self) -> None:
        self._save()
