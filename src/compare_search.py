"""Compare a PubMed search results file against an included studies Excel file.

Reports how many included studies were captured by the search and the total
number of results returned.
"""

import argparse
import os
import re
import sys
import time
from typing import Any

import openpyxl
from Bio import Entrez, Medline


class PubMedSearchResults:
    """Results from parsing a PubMed MEDLINE-format file."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records
        self.doi_map: dict[str, dict[str, str]] = {}
        self.pmid_map: dict[str, dict[str, str]] = {}

        for rec in records:
            pmid = rec.get("PMID", "")
            title = rec.get("TI", "")
            dois = set()

            # Extract DOIs from AID field (list of "value [type]" entries)
            for aid in rec.get("AID", []):
                if "[doi]" in aid:
                    doi = aid.replace("[doi]", "").strip()
                    dois.add(normalize_doi(doi))

            # Also check LID field
            lid = rec.get("LID", "")
            if isinstance(lid, list):
                lid = " ".join(lid)
            if "[doi]" in lid:
                doi = lid.split("[doi]")[0].strip()
                dois.add(normalize_doi(doi))

            # Store in PMID map
            if pmid:
                self.pmid_map[pmid] = {"pmid": pmid, "title": title, "dois": list(dois)}

            # Store in DOI map
            for doi in dois:
                self.doi_map[doi] = {"pmid": pmid, "title": title}

    def match_study(self, study: "IncludedStudy") -> dict[str, str] | None:
        """Try to match an included study by DOI first, then by PMID."""
        if study.doi and normalize_doi(study.doi) in self.doi_map:
            return self.doi_map[normalize_doi(study.doi)]
        if study.pmid and study.pmid in self.pmid_map:
            return self.pmid_map[study.pmid]
        return None


def extract_dois_from_pubmed(filepath: str) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    """Parse a PubMed MEDLINE-format file and return a mapping of DOI -> record info.

    DEPRECATED: Use PubMedSearchResults for more complete matching.
    """
    results = PubMedSearchResults([])
    with open(filepath) as f:
        records: list[dict[str, Any]] = list(Medline.parse(f))
    results = PubMedSearchResults(records)
    return results.doi_map, records


def parse_pubmed_results(filepath: str) -> PubMedSearchResults:
    """Parse a PubMed MEDLINE-format file and return search results."""
    with open(filepath) as f:
        records: list[dict[str, Any]] = list(Medline.parse(f))
    return PubMedSearchResults(records)


def lookup_doi_metadata(doi: str) -> dict[str, Any] | None:
    """Look up a DOI on PubMed via Entrez and return article metadata.

    Returns None if the DOI is not indexed in PubMed.
    """
    try:
        handle = Entrez.esearch(db="pubmed", term=f"{doi}[DOI]")
        search_results = Entrez.read(handle)
        handle.close()

        id_list: list[str] = search_results.get("IdList", [])
        if not id_list:
            return {"pmid": None, "in_pubmed": False, "doi": doi}

        pmid = id_list[0]
        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="medline", retmode="text")
        records = list(Medline.parse(handle))
        handle.close()

        if not records:
            return {"pmid": pmid, "in_pubmed": True, "doi": doi}

        rec = records[0]
        return {
            "pmid": pmid,
            "in_pubmed": True,
            "doi": doi,
            "title": rec.get("TI", ""),
            "authors": rec.get("AU", []),
            "journal": rec.get("JT", "") or rec.get("TA", ""),
            "year": rec.get("DP", ""),
            "mesh_terms": rec.get("MH", []),
            "publication_types": rec.get("PT", []),
            "abstract": rec.get("AB", ""),
        }
    except Exception as e:
        return {"pmid": None, "in_pubmed": False, "doi": doi, "error": str(e)}


def normalize_doi(doi: str) -> str:
    """Normalize a DOI string for consistent matching.

    Handles known quirks:
    - Trailing periods from data entry
    - Double slashes (e.g., APA journals: 10.1037//0022-3514.84.2.377)
    - URL prefixes (https://doi.org/...)
    - Case normalization
    """
    doi = doi.strip().rstrip(".")
    doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
    # Collapse double (or more) slashes to single, but only after the "10." prefix
    # DOIs are structured as 10.PREFIX/SUFFIX — the double slash quirk occurs in the suffix
    prefix_end = doi.find("/")
    if prefix_end > 0:
        prefix = doi[:prefix_end]
        suffix = doi[prefix_end:]
        suffix = re.sub(r"/{2,}", "/", suffix)
        doi = prefix + suffix
    return doi.lower()


class IncludedStudy:
    """Represents a study from the included studies file."""

    def __init__(self, doi: str | None = None, pmid: str | None = None, title: str | None = None):
        self.doi = normalize_doi(doi) if doi else None
        self.pmid = str(pmid).strip() if pmid else None
        self.title = title.strip() if title else None

    def __repr__(self) -> str:
        return f"IncludedStudy(doi={self.doi!r}, pmid={self.pmid!r})"


class IncludedStudiesResult:
    """Result of extracting included studies from a file."""

    def __init__(
        self,
        studies: list[IncludedStudy],
        error: str | None = None,
        warnings: list[str] | None = None,
    ):
        self.studies = studies
        self.error = error
        self.warnings = warnings or []

    @property
    def is_valid(self) -> bool:
        return self.error is None and len(self.studies) > 0


def extract_included_studies(filepath: str) -> IncludedStudiesResult:
    """Extract included studies from an Excel file.

    Looks for DOIs and/or PubMed IDs. Handles various column layouts:
    - Standard layout with 'DOI' column
    - Files with only 'PubMed ID' column
    - Mixed data where some rows have DOIs, others have PMIDs
    - Full URL DOIs (https://doi.org/...) and bare DOIs

    Returns an IncludedStudiesResult with studies list, any error, and warnings.
    """
    warnings: list[str] = []

    # Check if file exists
    if not os.path.exists(filepath):
        return IncludedStudiesResult([], error=f"File not found: {filepath}")

    try:
        wb = openpyxl.load_workbook(filepath, read_only=True)
    except Exception as e:
        return IncludedStudiesResult([], error=f"Failed to open Excel file: {e}")

    ws = wb.active
    if ws is None:
        wb.close()
        return IncludedStudiesResult([], error="No active worksheet in Excel file")

    try:
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        wb.close()
        return IncludedStudiesResult([], error=f"Failed to read worksheet: {e}")

    if not rows:
        wb.close()
        return IncludedStudiesResult([], error="Excel file is empty")

    # Parse header row to find relevant columns
    header = [str(c).strip().lower() if c else "" for c in rows[0]]

    doi_col: int | None = None
    pmid_col: int | None = None
    title_col: int | None = None

    for i, h in enumerate(header):
        if "doi" in h and doi_col is None:
            doi_col = i
        elif "pubmed" in h or h == "pmid":
            pmid_col = i
        elif "title" in h and title_col is None:
            title_col = i

    # If no DOI or PMID column found, this file format is unsupported
    if doi_col is None and pmid_col is None:
        wb.close()
        return IncludedStudiesResult(
            [],
            error=f"No 'DOI' or 'PubMed ID' column found in header: {rows[0]}"
        )

    if doi_col is None:
        warnings.append("No 'DOI' column found; using PubMed IDs only")
    if pmid_col is None:
        warnings.append("No 'PubMed ID' column found; using DOIs only")

    studies: list[IncludedStudy] = []
    empty_row_count = 0

    for row_idx, row in enumerate(rows[1:], start=2):
        # Skip completely empty rows
        if not any(row):
            empty_row_count += 1
            continue

        # Safely get values with bounds checking
        doi_val = row[doi_col] if doi_col is not None and doi_col < len(row) else None
        pmid_val = row[pmid_col] if pmid_col is not None and pmid_col < len(row) else None
        title_val = row[title_col] if title_col is not None and title_col < len(row) else None

        # Process DOI
        doi: str | None = None
        if doi_val:
            doi = str(doi_val).strip()
            # Strip URL prefix if present
            doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
            if not doi:
                doi = None

        # Process PMID
        pmid: str | None = None
        if pmid_val:
            pmid_str = str(pmid_val).strip()
            # Handle numeric PMIDs stored as floats (e.g., 12345.0)
            if pmid_str.replace(".", "").isdigit():
                pmid = str(int(float(pmid_str)))
            elif pmid_str.isdigit():
                pmid = pmid_str

        # Process title
        title: str | None = None
        if title_val:
            title = str(title_val).strip()

        # Skip rows with neither DOI nor PMID
        if not doi and not pmid:
            warnings.append(f"Row {row_idx}: no DOI or PMID found, skipping")
            continue

        studies.append(IncludedStudy(doi=doi, pmid=pmid, title=title))

    wb.close()

    if empty_row_count > 0:
        warnings.append(f"Skipped {empty_row_count} empty rows")

    if not studies:
        return IncludedStudiesResult(
            [],
            error="No valid studies found (all rows missing DOI and PMID)"
        )

    return IncludedStudiesResult(studies, warnings=warnings)


def extract_dois_from_excel(filepath: str) -> list[str]:
    """Extract DOIs from the included studies Excel file.

    Looks for DOIs in a column named 'DOI' or in the first column.
    Handles both raw DOI strings and full URLs (https://doi.org/...).

    DEPRECATED: Use extract_included_studies() for more robust extraction.
    """
    result = extract_included_studies(filepath)
    if result.error:
        print(f"Warning: {result.error}")
        return []
    return [s.doi for s in result.studies if s.doi]


def lookup_pmid_metadata(pmid: str) -> dict[str, Any] | None:
    """Look up a PMID on PubMed via Entrez and return article metadata."""
    try:
        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="medline", retmode="text")
        records = list(Medline.parse(handle))
        handle.close()

        if not records:
            return {"pmid": pmid, "in_pubmed": False}

        rec = records[0]
        # Extract DOI from record
        dois = []
        for aid in rec.get("AID", []):
            if "[doi]" in aid:
                dois.append(aid.replace("[doi]", "").strip().lower())

        return {
            "pmid": pmid,
            "in_pubmed": True,
            "doi": dois[0] if dois else None,
            "title": rec.get("TI", ""),
            "authors": rec.get("AU", []),
            "journal": rec.get("JT", "") or rec.get("TA", ""),
            "year": rec.get("DP", ""),
            "mesh_terms": rec.get("MH", []),
            "publication_types": rec.get("PT", []),
            "abstract": rec.get("AB", ""),
        }
    except Exception as e:
        return {"pmid": pmid, "in_pubmed": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Compare PubMed search results against included studies."
    )
    parser.add_argument("pubmed_file", help="PubMed MEDLINE-format results file")
    parser.add_argument("included_file", help="Included studies Excel file (.xlsx)")
    parser.add_argument(
        "--email",
        default="user@example.com",
        help="Email for NCBI Entrez API (required by NCBI)",
    )
    args = parser.parse_args()

    Entrez.email = args.email

    # Parse PubMed search results
    try:
        pubmed_results = parse_pubmed_results(args.pubmed_file)
    except FileNotFoundError:
        print(f"Error: PubMed results file not found: {args.pubmed_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading PubMed results: {e}", file=sys.stderr)
        sys.exit(1)

    # Parse included studies with robust error handling
    included_result = extract_included_studies(args.included_file)

    if included_result.error:
        print(f"Error: {included_result.error}", file=sys.stderr)
        sys.exit(1)

    # Print any warnings from parsing
    for warning in included_result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    studies = included_result.studies
    total_search_results = len(pubmed_results.records)
    total_included = len(studies)

    # Match studies using both DOI and PMID
    found: list[tuple[IncludedStudy, dict[str, str]]] = []
    missed: list[IncludedStudy] = []

    for study in studies:
        match = pubmed_results.match_study(study)
        if match:
            found.append((study, match))
        else:
            missed.append(study)

    # For missed studies, look up metadata to determine if they're in PubMed
    not_in_pubmed: list[IncludedStudy] = []
    missed_in_pubmed: list[tuple[IncludedStudy, dict[str, Any]]] = []

    if missed:
        print("Fetching metadata for missed studies...", flush=True)
        for study in missed:
            meta: dict[str, Any] | None = None

            # Try DOI lookup first if available
            if study.doi:
                meta = lookup_doi_metadata(study.doi)
                time.sleep(0.34)  # respect NCBI rate limit

            # If no DOI or DOI lookup failed, try PMID
            if (meta is None or not meta.get("in_pubmed")) and study.pmid:
                meta = lookup_pmid_metadata(study.pmid)
                time.sleep(0.34)

            if meta is None or not meta.get("in_pubmed"):
                not_in_pubmed.append(study)
            else:
                missed_in_pubmed.append((study, meta))

    indexable_included = total_included - len(not_in_pubmed)

    # --- Summary metrics ---
    print(f"PubMed search results:  {total_search_results}")
    print(f"Included studies:       {total_included}")
    print()
    print(f"Captured by search:     {len(found)} / {total_included}")
    print(f"Missed by search:       {len(missed)} / {total_included}")
    if total_included > 0:
        print(f"Recall (overall):       {len(found) / total_included * 100:.1f}%")
    print()
    print(f"Not indexed in PubMed:  {len(not_in_pubmed)}")
    print(f"Missed (PubMed-indexed):{len(missed_in_pubmed)}")
    if indexable_included > 0:
        print(f"Recall (PubMed only):   {len(found) / indexable_included * 100:.1f}%"
              f"  ({len(found)} / {indexable_included})")
    if total_search_results > 0:
        print(f"Precision:              {len(found) / total_search_results * 100:.1f}%"
              f"  ({len(found)} / {total_search_results})")
    print(f"NNR:                    {total_search_results / len(found):.1f}"
          if found else "NNR:                    N/A")
    print()

    if found:
        print("--- Captured studies ---")
        for study, match in found:
            title = match.get("title", study.title or "N/A")
            print(f"  PMID {match['pmid']}: {title[:90] if title else 'N/A'}")
            if study.doi:
                print(f"    DOI: {study.doi}")
            elif study.pmid:
                print(f"    Matched by PMID: {study.pmid}")
        print()

    if missed_in_pubmed:
        print("--- Missed studies (indexed in PubMed) ---")
        for study, meta in missed_in_pubmed:
            print(f"  PMID {meta['pmid']}: {meta.get('title', 'N/A')[:100]}")
            if study.doi:
                print(f"    DOI:      {study.doi}")
            if study.pmid and study.pmid != meta['pmid']:
                print(f"    Input PMID: {study.pmid}")
            authors = meta.get("authors", [])
            if authors:
                print(f"    Authors:  {', '.join(authors[:5])}{'...' if len(authors) > 5 else ''}")
            print(f"    Journal:  {meta.get('journal', 'N/A')}")
            print(f"    Year:     {meta.get('year', 'N/A')}")
            pub_types = meta.get("publication_types", [])
            if pub_types:
                print(f"    Pub Type: {', '.join(pub_types)}")
            mesh = meta.get("mesh_terms", [])
            if mesh:
                print(f"    MeSH:     {', '.join(mesh)}")
            print()

    if not_in_pubmed:
        print("--- Not indexed in PubMed (cannot be captured by any PubMed query) ---")
        for study in not_in_pubmed:
            if study.doi:
                print(f"  DOI: {study.doi}")
            if study.pmid:
                print(f"  PMID: {study.pmid}")
            if study.title:
                print(f"    Title: {study.title[:80]}")
        print()


if __name__ == "__main__":
    main()
