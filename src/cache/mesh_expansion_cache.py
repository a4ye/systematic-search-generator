"""Cache for MeSH expansion results."""

import json
from pathlib import Path


class MeshExpansionCache:
    """Persistent cache for MeSH expansion lookups."""

    CACHE_FILE = "mesh_expansion.json"

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / self.CACHE_FILE
        self._cache: dict[str, dict[str, list[str]]] = {}
        self._load()

    def _load(self) -> None:
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cache = data
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f, indent=2)

    def get(self, term: str) -> dict[str, list[str]] | None:
        if not term:
            return None
        return self._cache.get(term.lower())

    def set(self, term: str, exact: list[str], related: list[str]) -> None:
        if not term:
            return
        self._cache[term.lower()] = {
            "exact": exact,
            "related": related,
        }
        self._save()
