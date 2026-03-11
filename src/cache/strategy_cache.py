"""Cache for extracted human search strategies."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class CachedStrategy:
    """A cached human search strategy."""

    query: str
    database: str
    source_file: str
    source_file_hash: str
    extracted_at: str
    model_version: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CachedStrategy":
        return cls(**data)


class StrategyCache:
    """Persistent cache for extracted human strategies."""

    CACHE_FILE = "human_strategies.json"

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / self.CACHE_FILE
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f, indent=2)

    def _compute_file_hash(self, path: Path) -> str:
        """Compute MD5 hash of file for change detection."""
        hash_md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _get_cache_key(self, docx_path: Path) -> str:
        """Generate cache key from file path."""
        return str(docx_path.resolve())

    def get(self, docx_path: Path) -> CachedStrategy | None:
        """Get cached strategy, validating file hasn't changed."""
        key = self._get_cache_key(docx_path)
        if key not in self._cache:
            return None

        cached_data = self._cache[key]
        current_hash = self._compute_file_hash(docx_path)

        if cached_data.get("source_file_hash") != current_hash:
            # File has changed, invalidate cache
            del self._cache[key]
            self._save()
            return None

        return CachedStrategy.from_dict(cached_data)

    def set(
        self,
        docx_path: Path,
        query: str,
        database: str = "PubMed",
        model_version: str = "gpt-5-nano",
    ) -> CachedStrategy:
        """Cache an extracted strategy."""
        key = self._get_cache_key(docx_path)
        strategy = CachedStrategy(
            query=query,
            database=database,
            source_file=str(docx_path),
            source_file_hash=self._compute_file_hash(docx_path),
            extracted_at=datetime.now().isoformat(),
            model_version=model_version,
        )
        self._cache[key] = strategy.to_dict()
        self._save()
        return strategy

    def invalidate(self, docx_path: Path) -> None:
        """Remove cached strategy."""
        key = self._get_cache_key(docx_path)
        if key in self._cache:
            del self._cache[key]
            self._save()

    def clear(self) -> None:
        """Clear all cached strategies."""
        self._cache = {}
        self._save()

    def list_cached(self) -> list[str]:
        """List all cached file paths."""
        return list(self._cache.keys())
