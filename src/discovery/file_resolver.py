"""Fuzzy file matching for inconsistent file names in study directories."""

import re
from pathlib import Path


class FileResolver:
    """Fuzzy matching for inconsistent file names across study directories."""

    PROSPERO_PATTERNS = [
        r"(?i).*prospero.*\.pdf$",
        r"(?i).*protocol.*\.pdf$",
        r"(?i)^CRD\d+.*\.pdf$",
    ]

    INCLUDED_PATTERNS = [
        r"(?i).*included.*stud.*\.xlsx$",
        r"(?i).*studies.*included.*\.xlsx$",
    ]

    STRATEGY_PATTERNS = [
        r"(?i).*search.*strateg.*\.docx$",
        r"(?i).*strateg.*search.*\.docx$",
    ]

    # Exclude temporary Word files
    EXCLUDED_PATTERNS = [
        r"^~\$.*",  # Word temp files
        r"^\._.*",  # macOS resource forks
    ]

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _is_excluded(self, filename: str) -> bool:
        """Check if file matches any exclusion pattern."""
        for pattern in self.EXCLUDED_PATTERNS:
            if re.match(pattern, filename):
                return True
        return False

    def _find_by_patterns(self, patterns: list[str]) -> Path | None:
        """Find the first file matching any of the given patterns."""
        if not self.directory.exists():
            return None

        for path in self.directory.iterdir():
            if not path.is_file():
                continue
            if self._is_excluded(path.name):
                continue
            for pattern in patterns:
                if re.match(pattern, path.name):
                    return path
        return None

    def find_prospero(self) -> Path | None:
        """Find PROSPERO PDF using fuzzy patterns."""
        return self._find_by_patterns(self.PROSPERO_PATTERNS)

    def find_included_studies(self) -> Path | None:
        """Find included studies Excel file."""
        return self._find_by_patterns(self.INCLUDED_PATTERNS)

    def find_search_strategy(self) -> Path | None:
        """Find search strategy document."""
        return self._find_by_patterns(self.STRATEGY_PATTERNS)

    def find_all(self) -> dict[str, Path | None]:
        """Find all relevant files in the directory."""
        return {
            "prospero": self.find_prospero(),
            "included_studies": self.find_included_studies(),
            "search_strategy": self.find_search_strategy(),
        }
