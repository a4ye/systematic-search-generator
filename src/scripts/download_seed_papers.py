#!/usr/bin/env python3
"""
Download seed papers for systematic reviews.

This script reads included studies from each systematic review directory,
fetches metadata from PubMed, and saves them as structured JSON files
that can be used as seed papers for LLM-based search strategy generation.

Usage:
    uv run src/scripts/download_seed_papers.py                    # Process all reviews
    uv run src/scripts/download_seed_papers.py --review "34 - Lu 2022"  # Single review
    uv run src/scripts/download_seed_papers.py --force             # Re-download existing

Environment variables (via .env):
    ENTREZ_EMAIL   - Required by NCBI for API access
    PUBMED_API_KEY - Optional, increases rate limit from 3 to 10 requests/sec
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
from Bio import Entrez
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure Entrez from environment
Entrez.email = os.environ.get("ENTREZ_EMAIL") or os.environ.get("NCBI_EMAIL") or os.environ.get("PUBMED_EMAIL")
Entrez.api_key = os.environ.get("PUBMED_API_KEY") or os.environ.get("NCBI_API_KEY")

# Rate limiting: 10/sec with API key, 3/sec without
RATE_LIMIT_DELAY = 0.1 if Entrez.api_key else 0.34

DATA_DIR = Path(__file__).parent.parent.parent / "data"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "seed_papers"


def find_included_studies_file(review_dir: Path) -> Path | None:
    """Find the included studies Excel file in a review directory.

    Handles various naming conventions like:
    - "Included Studies.xlsx"
    - "Author Year Included Studies.xlsx"
    - "Included Studies - Author Year.xlsx"
    - "Included Examples - Author Year.xlsx"
    """
    xlsx_files = list(review_dir.glob("*.xlsx"))

    for f in xlsx_files:
        name_lower = f.name.lower()
        if "included" in name_lower and ("stud" in name_lower or "example" in name_lower):
            return f

    return None


def extract_pmid_from_doi(doi: str) -> str | None:
    """Try to get PMID from DOI using PubMed search."""
    if not doi or pd.isna(doi):
        return None

    # Clean the DOI
    doi = str(doi).strip()
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    elif doi.startswith("http://doi.org/"):
        doi = doi.replace("http://doi.org/", "")

    try:
        handle = Entrez.esearch(db="pubmed", term=f"{doi}[DOI]", retmax=1)
        record = Entrez.read(handle)
        handle.close()

        if record["IdList"]:
            return record["IdList"][0]
    except Exception as e:
        print(f"  Warning: Could not search DOI {doi}: {e}")

    return None


def fetch_pubmed_metadata(pmid: str) -> dict | None:
    """Fetch full metadata for a PMID from PubMed."""
    try:
        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="xml", retmode="xml")
        records = Entrez.read(handle)
        handle.close()

        if not records.get("PubmedArticle"):
            return None

        article = records["PubmedArticle"][0]
        medline = article["MedlineCitation"]
        article_data = medline["Article"]

        # Extract title
        title = str(article_data.get("ArticleTitle", ""))

        # Extract abstract
        abstract_parts = article_data.get("Abstract", {}).get("AbstractText", [])
        if isinstance(abstract_parts, list):
            abstract = " ".join(str(part) for part in abstract_parts)
        else:
            abstract = str(abstract_parts)

        # Extract authors
        authors = []
        author_list = article_data.get("AuthorList", [])
        for author in author_list:
            if "LastName" in author:
                name = author.get("LastName", "")
                if "ForeName" in author:
                    name = f"{author['ForeName']} {name}"
                authors.append(name)

        # Extract journal info
        journal = article_data.get("Journal", {})
        journal_title = str(journal.get("Title", ""))

        # Extract publication date
        pub_date = journal.get("JournalIssue", {}).get("PubDate", {})
        year = pub_date.get("Year", "")

        # Extract MeSH terms
        mesh_list = medline.get("MeshHeadingList", [])
        mesh_terms = []
        for mesh in mesh_list:
            if "DescriptorName" in mesh:
                mesh_terms.append(str(mesh["DescriptorName"]))

        # Extract keywords
        keyword_list = medline.get("KeywordList", [])
        keywords = []
        for kw_group in keyword_list:
            for kw in kw_group:
                keywords.append(str(kw))

        # Extract DOI
        doi = None
        article_ids = article.get("PubmedData", {}).get("ArticleIdList", [])
        for aid in article_ids:
            if aid.attributes.get("IdType") == "doi":
                doi = str(aid)
                break

        return {
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal_title,
            "year": year,
            "mesh_terms": mesh_terms,
            "keywords": keywords,
        }

    except Exception as e:
        print(f"  Warning: Could not fetch PMID {pmid}: {e}")
        return None


def process_review(review_dir: Path) -> dict:
    """Process a single systematic review directory."""
    review_name = review_dir.name
    print(f"\nProcessing: {review_name}")

    # Find included studies file
    studies_file = find_included_studies_file(review_dir)
    if not studies_file:
        print(f"  No included studies file found")
        return {"review": review_name, "error": "No included studies file found", "papers": []}

    print(f"  Found: {studies_file.name}")

    # Read the Excel file
    try:
        df = pd.read_excel(studies_file)
    except Exception as e:
        print(f"  Error reading file: {e}")
        return {"review": review_name, "error": str(e), "papers": []}

    papers = []

    for idx, row in df.iterrows():
        pmid = row.get("PubMed ID")
        doi = row.get("DOI")
        title = str(row.get("Title", "")) if pd.notna(row.get("Title")) else ""

        # Clean PMID
        if pd.notna(pmid):
            pmid = str(pmid).strip()
            # Handle various formats
            pmid = re.sub(r"[^\d]", "", pmid)
            if not pmid:
                pmid = None
        else:
            pmid = None

        # Try to get PMID from DOI if not available
        if not pmid and doi:
            print(f"  Searching DOI for PMID: {title[:50]}...")
            pmid = extract_pmid_from_doi(doi)
            time.sleep(RATE_LIMIT_DELAY)

        if pmid:
            print(f"  Fetching PMID {pmid}: {title[:50]}...")
            metadata = fetch_pubmed_metadata(pmid)
            time.sleep(RATE_LIMIT_DELAY)

            if metadata:
                papers.append(metadata)
            else:
                # Fall back to Excel data
                papers.append({
                    "pmid": pmid,
                    "doi": str(doi) if pd.notna(doi) else None,
                    "title": str(title) if pd.notna(title) else "",
                    "abstract": str(row.get("Abstract", "")) if pd.notna(row.get("Abstract")) else "",
                    "authors": [],
                    "journal": "",
                    "year": str(row.get("Year", "")) if pd.notna(row.get("Year")) else "",
                    "mesh_terms": [],
                    "keywords": [],
                    "source": "excel_fallback"
                })
        else:
            # No PMID available, use Excel data
            print(f"  No PMID found, using Excel data: {title[:50]}...")
            papers.append({
                "pmid": None,
                "doi": str(doi) if pd.notna(doi) else None,
                "title": str(title) if pd.notna(title) else "",
                "abstract": str(row.get("Abstract", "")) if pd.notna(row.get("Abstract")) else "",
                "authors": str(row.get("Full author list", "")).split(", ") if pd.notna(row.get("Full author list")) else [],
                "journal": str(row.get("Journal Volume", "")) if pd.notna(row.get("Journal Volume")) else "",
                "year": str(row.get("Year", "")) if pd.notna(row.get("Year")) else "",
                "mesh_terms": [],
                "keywords": [],
                "source": "excel_only"
            })

    return {
        "review": review_name,
        "source_file": studies_file.name,
        "paper_count": len(papers),
        "papers": papers,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download seed papers from systematic reviews for LLM-based search strategy generation."
    )
    parser.add_argument(
        "--review",
        type=str,
        help="Process only this review (directory name, e.g., '34 - Lu 2022')",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output directory (default: seed_papers/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )
    args = parser.parse_args()

    # Validate email is configured
    if not Entrez.email:
        print("Error: ENTREZ_EMAIL must be set in .env")
        return 1

    # Set output directory
    output_dir = Path(args.output) if args.output else OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)

    # Find review directories
    if args.review:
        review_dir = DATA_DIR / args.review
        if not review_dir.exists():
            print(f"Error: Review directory not found: {review_dir}")
            return 1
        review_dirs = [review_dir]
    else:
        review_dirs = sorted([d for d in DATA_DIR.iterdir() if d.is_dir()])

    print(f"Found {len(review_dirs)} systematic reviews")
    print(f"Using email: {Entrez.email}")
    print(f"API key: {'configured' if Entrez.api_key else 'not set (slower rate limit)'}")

    all_results = []
    skipped = 0

    for review_dir in review_dirs:
        review_output = output_dir / f"{review_dir.name}.json"

        # Skip if already downloaded (unless --force)
        if review_output.exists() and not args.force:
            print(f"\nSkipping (cached): {review_dir.name}")
            with open(review_output) as f:
                result = json.load(f)
            all_results.append(result)
            skipped += 1
            continue

        result = process_review(review_dir)
        all_results.append(result)

        # Save individual review results
        with open(review_output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  Saved to: {review_output.name}")

    # Save summary
    summary = {
        "total_reviews": len(all_results),
        "total_papers": sum(r.get("paper_count", 0) for r in all_results),
        "reviews": [
            {
                "name": r["review"],
                "paper_count": r.get("paper_count", 0),
                "error": r.get("error"),
            }
            for r in all_results
        ],
    }

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Complete! {summary['total_papers']} papers from {summary['total_reviews']} reviews")
    if skipped:
        print(f"  Skipped (cached): {skipped} reviews")
        print(f"  Downloaded: {len(review_dirs) - skipped} reviews")
    print(f"Output directory: {output_dir}")
    return 0


if __name__ == "__main__":
    exit(main() or 0)
