"""Discover and validate study directories."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .file_resolver import FileResolver


@dataclass
class StudyInfo:
    """Metadata about a study directory."""

    study_id: str
    name: str
    directory: Path
    prospero_pdf: Path | None = None
    search_strategy_docx: Path | None = None
    included_studies_xlsx: Path | None = None
    missing_files: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Check if all required files are present."""
        return len(self.missing_files) == 0

    @property
    def has_prospero(self) -> bool:
        return self.prospero_pdf is not None

    @property
    def has_strategy(self) -> bool:
        return self.search_strategy_docx is not None

    @property
    def has_included(self) -> bool:
        return self.included_studies_xlsx is not None

    def __str__(self) -> str:
        status = "complete" if self.is_complete else f"missing: {', '.join(self.missing_files)}"
        return f"Study {self.study_id} - {self.name} ({status})"


class StudyFinder:
    """Discovers and validates study directories."""

    # Pattern to match study directory names like "34 - Lu 2022"
    STUDY_DIR_PATTERN = re.compile(r"^(\d+)\s*-\s*(.+)$")

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def _parse_study_dir(self, path: Path) -> tuple[str, str] | None:
        """Parse study ID and name from directory name.

        Returns (study_id, name) or None if not a valid study directory.
        """
        match = self.STUDY_DIR_PATTERN.match(path.name)
        if match:
            return match.group(1), match.group(2).strip()
        return None

    def _create_study_info(self, directory: Path) -> StudyInfo | None:
        """Create StudyInfo for a directory, or None if not a study directory."""
        parsed = self._parse_study_dir(directory)
        if not parsed:
            return None

        study_id, name = parsed
        resolver = FileResolver(directory)
        files = resolver.find_all()

        missing = []
        if files["prospero"] is None:
            missing.append("PROSPERO PDF")
        if files["included_studies"] is None:
            missing.append("Included Studies")
        if files["search_strategy"] is None:
            missing.append("Search Strategy")

        return StudyInfo(
            study_id=study_id,
            name=name,
            directory=directory,
            prospero_pdf=files["prospero"],
            search_strategy_docx=files["search_strategy"],
            included_studies_xlsx=files["included_studies"],
            missing_files=missing,
        )

    def discover_all(self) -> list[StudyInfo]:
        """Scan data directory and find all studies."""
        if not self.data_dir.exists():
            return []

        studies = []
        for path in sorted(self.data_dir.iterdir()):
            if not path.is_dir():
                continue
            study = self._create_study_info(path)
            if study:
                studies.append(study)

        # Sort by study ID numerically
        studies.sort(key=lambda s: int(s.study_id))
        return studies

    def get_study(self, study_id: str) -> StudyInfo | None:
        """Get a specific study by ID."""
        for study in self.discover_all():
            if study.study_id == study_id:
                return study
        return None

    def get_studies(self, study_ids: list[str]) -> list[StudyInfo]:
        """Get multiple studies by ID."""
        all_studies = {s.study_id: s for s in self.discover_all()}
        return [all_studies[sid] for sid in study_ids if sid in all_studies]

    def get_complete_studies(self) -> list[StudyInfo]:
        """Return only studies with all required files."""
        return [s for s in self.discover_all() if s.is_complete]

    def get_incomplete_studies(self) -> list[StudyInfo]:
        """Return studies missing one or more required files."""
        return [s for s in self.discover_all() if not s.is_complete]

    def get_studies_with_prospero(self) -> list[StudyInfo]:
        """Return studies that have a PROSPERO PDF (for LLM generation)."""
        return [s for s in self.discover_all() if s.has_prospero and s.has_included]

    def get_studies_with_strategy(self) -> list[StudyInfo]:
        """Return studies that have a search strategy (for human comparison)."""
        return [s for s in self.discover_all() if s.has_strategy and s.has_included]
