"""Local MeSH descriptor database helper.

Downloads the official MeSH descriptor XML (descYYYY.xml) from NLM,
parses descriptor names, entry terms, and tree numbers, and caches a
compact JSON index for fast lookup.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from xml.etree.ElementTree import iterparse

logger = logging.getLogger(__name__)

_MESH_BASE_URL = (
    "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc{year}.xml"
)

_CACHE_FILENAME = "mesh_db.json"


@dataclass
class MeshDescriptor:
    """MeSH descriptor record."""

    name: str
    entry_terms: list[str] = field(default_factory=list)
    tree_numbers: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    text = " ".join(str(text).strip().split())
    return text.lower()


def _mesh_tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", text.lower())
    out: set[str] = set()
    for tok in tokens:
        out.add(tok)
        if tok.endswith("ies") and len(tok) > 4:
            out.add(tok[:-3] + "y")
        elif tok.endswith("s") and len(tok) > 4:
            out.add(tok[:-1])
    return list(out)


def _deinvert(term: str) -> str:
    """Convert inverted MeSH entry terms into natural order.

    Example: "Neoplasms, Colorectal" -> "Colorectal Neoplasms"
    """
    if term.count(",") != 1:
        return term
    left, right = [p.strip() for p in term.split(",", 1)]
    if not left or not right:
        return term
    return f"{right} {left}".strip()


def _is_noise_entry(term: str) -> bool:
    lower = term.lower()
    if not re.search(r"[a-zA-Z]", term):
        return True
    if "not otherwise specified" in lower or "nos" in lower:
        return True
    if "unspecified" in lower:
        return True
    if "specialty" in lower:
        return True
    if "/" in term:
        return True
    return False


class MeshDB:
    """Local cache of MeSH descriptor names and entry terms."""

    def __init__(
        self,
        cache_dir: Path,
        year: int | None = None,
        max_year_back: int = 2,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.year = year
        self.max_year_back = max_year_back
        self.cache_path = self.cache_dir / _CACHE_FILENAME
        self._records: dict[str, MeshDescriptor] = {}
        self._entry_to_descriptor: dict[str, str] = {}
        self._token_index: dict[str, list[str]] = {}
        self._loaded_year: int | None = None
        self._loaded = False
        self._failed = False

    def _candidate_years(self) -> list[int]:
        if self.year:
            return [self.year]
        current = date.today().year
        return [current - i for i in range(self.max_year_back + 1)]

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._failed:
            return
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    data = json.load(f)
                if isinstance(data, dict) and "records" in data:
                    self._load_from_cache(data)
                    self._loaded = True
                    return
            except (OSError, json.JSONDecodeError):
                logger.warning("Failed to read MeSH cache; rebuilding.")
        try:
            self._build_cache()
            self._loaded = True
        except Exception as exc:
            logger.warning("Failed to build MeSH cache: %s", exc)
            self._failed = True

    def _load_from_cache(self, data: dict) -> None:
        records = data.get("records", {})
        if not isinstance(records, dict):
            return
        self._records = {}
        self._entry_to_descriptor = {}
        self._token_index = {}
        for key, payload in records.items():
            if not isinstance(payload, dict):
                continue
            name = payload.get("name", "")
            entry_terms = payload.get("entry_terms", [])
            tree_numbers = payload.get("tree_numbers", [])
            if not name:
                continue
            record = MeshDescriptor(
                name=name,
                entry_terms=list(entry_terms) if isinstance(entry_terms, list) else [],
                tree_numbers=list(tree_numbers) if isinstance(tree_numbers, list) else [],
            )
            self._records[key] = record
            for term in record.entry_terms:
                norm = _normalize(term)
                if norm:
                    self._entry_to_descriptor[norm] = key
            for tok in _mesh_tokenize(record.name):
                self._token_index.setdefault(tok, []).append(key)
        loaded_year = data.get("year")
        if isinstance(loaded_year, int):
            self._loaded_year = loaded_year

    def _build_cache(self) -> None:
        xml_path, year = self._download_mesh_xml()
        records: dict[str, MeshDescriptor] = {}

        logger.info("Parsing MeSH descriptor XML (%s)", xml_path)
        context = iterparse(xml_path, events=("end",))
        for event, elem in context:
            if elem.tag != "DescriptorRecord":
                continue
            name_elem = elem.find("./DescriptorName/String")
            if name_elem is None or not name_elem.text:
                elem.clear()
                continue
            name = " ".join(name_elem.text.split())
            key = _normalize(name)
            entry_terms: list[str] = []
            for term_elem in elem.findall("./ConceptList/Concept/TermList/Term/String"):
                if term_elem.text:
                    term_text = " ".join(term_elem.text.split())
                    entry_terms.append(term_text)
            tree_numbers = [
                t.text.strip()
                for t in elem.findall("./TreeNumberList/TreeNumber")
                if t.text and t.text.strip()
            ]
            # Deduplicate entry terms (case-insensitive)
            deduped: list[str] = []
            seen: set[str] = set()
            for term in entry_terms:
                norm = _normalize(term)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                deduped.append(term)
            records[key] = MeshDescriptor(
                name=name,
                entry_terms=deduped,
                tree_numbers=tree_numbers,
            )
            elem.clear()

        self._records = records
        self._entry_to_descriptor = {}
        self._token_index = {}
        for key, record in records.items():
            for term in record.entry_terms:
                norm = _normalize(term)
                if norm:
                    self._entry_to_descriptor[norm] = key
            for tok in _mesh_tokenize(record.name):
                self._token_index.setdefault(tok, []).append(key)
        self._loaded_year = year

        payload = {
            "year": year,
            "records": {
                key: {
                    "name": rec.name,
                    "entry_terms": rec.entry_terms,
                    "tree_numbers": rec.tree_numbers,
                }
                for key, rec in records.items()
            },
        }
        with open(self.cache_path, "w") as f:
            json.dump(payload, f)
        logger.info("Saved MeSH cache to %s", self.cache_path)

    def _download_mesh_xml(self) -> tuple[Path, int]:
        for year in self._candidate_years():
            dest = self.cache_dir / f"desc{year}.xml"
            if dest.exists():
                logger.info("Using cached MeSH XML: %s", dest)
                return dest, year
            url = _MESH_BASE_URL.format(year=year)
            try:
                logger.info("Downloading MeSH XML: %s", url)
                with urlopen(url, timeout=60) as response, open(dest, "wb") as out:
                    out.write(response.read())
                return dest, year
            except (HTTPError, URLError, TimeoutError) as exc:
                logger.warning("Failed to download %s (%s)", url, exc)
                if dest.exists():
                    try:
                        dest.unlink()
                    except OSError:
                        pass
                continue
        raise RuntimeError("Unable to download MeSH descriptor XML.")

    def lookup_descriptor(self, term: str) -> MeshDescriptor | None:
        """Return the descriptor record for a term (descriptor or entry term)."""
        self._ensure_loaded()
        norm = _normalize(term)
        if not norm:
            return None
        if norm in self._records:
            return self._records[norm]
        descriptor_key = self._entry_to_descriptor.get(norm)
        if descriptor_key:
            return self._records.get(descriptor_key)
        return None

    def entry_terms(self, term: str, max_terms: int = 6) -> list[str]:
        """Return curated entry terms for a descriptor or entry term."""
        record = self.lookup_descriptor(term)
        if not record:
            return []
        terms: list[str] = []
        seen: set[str] = set()
        for entry in record.entry_terms:
            entry_norm = _normalize(entry)
            if not entry_norm or entry_norm == _normalize(record.name):
                continue
            if _is_noise_entry(entry):
                continue
            candidate = _deinvert(entry)
            candidate = " ".join(candidate.split())
            if not candidate:
                continue
            cand_norm = _normalize(candidate)
            if cand_norm in seen:
                continue
            seen.add(cand_norm)
            terms.append(candidate)
            if len(terms) >= max_terms:
                break
        return terms

    def search_by_token(self, token: str, max_terms: int = 6) -> list[str]:
        """Return descriptor names containing the given token."""
        self._ensure_loaded()
        tok = _normalize(token)
        if not tok:
            return []
        matches = self._token_index.get(tok, [])
        out: list[str] = []
        seen: set[str] = set()
        for key in matches:
            rec = self._records.get(key)
            if not rec:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(rec.name)
            if len(out) >= max_terms:
                break
        return out

    def parents(self, term: str, max_parents: int = 2) -> list[str]:
        """Return broader parent MeSH headings by tree number (one level up)."""
        record = self.lookup_descriptor(term)
        if not record:
            return []
        parents: list[str] = []
        seen: set[str] = set()
        for tree in record.tree_numbers:
            if "." not in tree:
                continue
            parent_tree = ".".join(tree.split(".")[:-1])
            parent = self._descriptor_by_tree(parent_tree)
            if not parent:
                continue
            norm = _normalize(parent.name)
            if norm in seen:
                continue
            seen.add(norm)
            parents.append(parent.name)
            if len(parents) >= max_parents:
                break
        return parents

    def _descriptor_by_tree(self, tree_number: str) -> MeshDescriptor | None:
        for rec in self._records.values():
            if tree_number in rec.tree_numbers:
                return rec
        return None

    def loaded_year(self) -> int | None:
        return self._loaded_year

    def is_loaded(self) -> bool:
        return self._loaded
