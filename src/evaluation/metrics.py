"""Calculate evaluation metrics for search strategies."""

import time
from dataclasses import dataclass, field
from typing import Any

from Bio import Entrez, Medline

from src.cache.pubmed_index_cache import PubMedIndexCache
from src.compare_search import IncludedStudy, extract_included_studies
from src.pubmed.search_executor import PubMedSearchResults


@dataclass
class EvaluationMetrics:
    """Evaluation metrics for a search strategy."""

    total_results: int
    total_included: int
    found: int
    missed: int
    not_in_pubmed: int
    missed_pubmed_indexed: int  # Missed but actually in PubMed
    recall_overall: float
    recall_pubmed_only: float
    precision: float
    nnr: float  # Number Needed to Read
    f1_score: float

    @property
    def pubmed_indexed_count(self) -> int:
        """Number of included studies that are indexed in PubMed."""
        return self.total_included - self.not_in_pubmed


@dataclass
class MatchResult:
    """Result of matching an included study against search results."""

    study: IncludedStudy
    matched: bool
    in_pubmed: bool = True
    match_info: dict[str, Any] | None = None


def check_pubmed_indexed_batch(
    studies: list[IncludedStudy],
    rate_delay: float = 0.1,
    cache: PubMedIndexCache | None = None,
    batch_size: int = 200,
) -> dict[int, bool]:
    """Check if multiple studies are indexed in PubMed using batch lookups.

    Uses cache if provided to avoid redundant API calls. Returns a dict
    mapping study index to indexed status.

    Args:
        studies: List of studies to check
        rate_delay: Delay between API calls (0.1s = 10/sec with API key)
        cache: Optional cache for results
        batch_size: Max PMIDs per batch request (NCBI recommends ~200)
    """
    results: dict[int, bool] = {}
    uncached_pmid_studies: list[tuple[int, IncludedStudy]] = []  # (index, study)
    uncached_doi_studies: list[tuple[int, IncludedStudy]] = []  # (index, study)

    # Check cache first
    for i, study in enumerate(studies):
        if cache:
            cached = cache.get(doi=study.doi, pmid=study.pmid)
            if cached is not None:
                results[i] = cached
                continue

        # Categorize uncached studies by lookup type
        if study.pmid:
            uncached_pmid_studies.append((i, study))
        elif study.doi:
            uncached_doi_studies.append((i, study))
        else:
            # No identifier - assume not indexed
            results[i] = False

    # Batch lookup PMIDs in chunks (NCBI recommends ~200 per request)
    if uncached_pmid_studies:
        found_pmids: set[str] = set()

        for batch_start in range(0, len(uncached_pmid_studies), batch_size):
            batch = uncached_pmid_studies[batch_start:batch_start + batch_size]
            pmid_list = [s.pmid for _, s in batch]

            time.sleep(rate_delay)

            try:
                handle = Entrez.efetch(
                    db="pubmed",
                    id=",".join(pmid_list),
                    rettype="medline",
                    retmode="text",
                )
                records = list(Medline.parse(handle))
                handle.close()

                # Add found PMIDs to set
                found_pmids.update(rec.get("PMID") for rec in records if rec.get("PMID"))

            except Exception:
                # On error for this batch, those PMIDs won't be in found_pmids
                pass

        # Update results for all PMID studies
        for idx, study in uncached_pmid_studies:
            indexed = study.pmid in found_pmids
            results[idx] = indexed
            if cache:
                cache.set(indexed, pmid=study.pmid, save=False)

    # DOI lookups must be done individually (no batch search for DOIs)
    for idx, study in uncached_doi_studies:
        time.sleep(rate_delay)
        indexed = False
        try:
            handle = Entrez.esearch(db="pubmed", term=f"{study.doi}[DOI]")
            search_results = Entrez.read(handle)
            handle.close()
            indexed = len(search_results.get("IdList", [])) > 0
        except Exception:
            pass

        results[idx] = indexed
        if cache:
            cache.set(indexed, doi=study.doi, save=False)

    # Save cache once at the end
    if cache:
        cache.save()

    return results


def check_pubmed_indexed(
    study: IncludedStudy,
    rate_delay: float = 0.1,
    cache: PubMedIndexCache | None = None,
) -> bool:
    """Check if a study is indexed in PubMed by looking up its DOI or PMID.

    Uses cache if provided to avoid redundant API calls.
    """
    results = check_pubmed_indexed_batch([study], rate_delay, cache)
    return results.get(0, False)


def calculate_metrics(
    search_results: PubMedSearchResults,
    included_studies: list[IncludedStudy],
    not_in_pubmed_count: int = 0,
    missed_pubmed_indexed: int = 0,
) -> EvaluationMetrics:
    """Calculate evaluation metrics for search results against included studies."""
    total_results = search_results.result_count
    total_included = len(included_studies)

    # Count matches
    found = 0
    for study in included_studies:
        match = None
        if study.doi:
            match = search_results.match_by_doi(study.doi)
        if not match and study.pmid:
            match = search_results.match_by_pmid(study.pmid)
        if match:
            found += 1

    missed = total_included - found
    pubmed_indexed = total_included - not_in_pubmed_count

    # Calculate metrics
    recall_overall = found / total_included if total_included > 0 else 0.0
    recall_pubmed = found / pubmed_indexed if pubmed_indexed > 0 else 0.0
    precision = found / total_results if total_results > 0 else 0.0
    nnr = total_results / found if found > 0 else float("inf")

    # F1 score
    if precision + recall_overall > 0:
        f1 = 2 * (precision * recall_overall) / (precision + recall_overall)
    else:
        f1 = 0.0

    return EvaluationMetrics(
        total_results=total_results,
        total_included=total_included,
        found=found,
        missed=missed,
        not_in_pubmed=not_in_pubmed_count,
        missed_pubmed_indexed=missed_pubmed_indexed,
        recall_overall=recall_overall,
        recall_pubmed_only=recall_pubmed,
        precision=precision,
        nnr=nnr,
        f1_score=f1,
    )


def calculate_metrics_with_pubmed_check(
    search_results: PubMedSearchResults,
    included_studies: list[IncludedStudy],
    entrez_email: str,
    rate_delay: float = 0.34,
    index_cache: PubMedIndexCache | None = None,
) -> EvaluationMetrics:
    """Calculate metrics, checking which missed studies are actually in PubMed.

    Args:
        search_results: PubMed search results to evaluate
        included_studies: List of studies that should be found
        entrez_email: Email for Entrez API
        rate_delay: Delay between API calls for rate limiting
        index_cache: Optional cache for PubMed indexing status
    """
    Entrez.email = entrez_email

    total_results = search_results.result_count
    total_included = len(included_studies)

    # Match studies and identify missed ones
    found_studies = []
    missed_studies = []

    for study in included_studies:
        match = None
        if study.doi:
            match = search_results.match_by_doi(study.doi)
        if not match and study.pmid:
            match = search_results.match_by_pmid(study.pmid)

        if match:
            found_studies.append(study)
        else:
            missed_studies.append(study)

    found = len(found_studies)
    missed = len(missed_studies)

    # Check which missed studies are actually indexed in PubMed (batch lookup)
    not_in_pubmed = 0
    missed_pubmed_indexed = 0

    if missed_studies:
        indexed_results = check_pubmed_indexed_batch(missed_studies, rate_delay, cache=index_cache)
        for idx, study in enumerate(missed_studies):
            if indexed_results.get(idx, False):
                missed_pubmed_indexed += 1
            else:
                not_in_pubmed += 1

    pubmed_indexed = total_included - not_in_pubmed

    # Calculate metrics
    recall_overall = found / total_included if total_included > 0 else 0.0
    recall_pubmed = found / pubmed_indexed if pubmed_indexed > 0 else 0.0
    precision = found / total_results if total_results > 0 else 0.0
    nnr = total_results / found if found > 0 else float("inf")

    # F1 score
    if precision + recall_overall > 0:
        f1 = 2 * (precision * recall_overall) / (precision + recall_overall)
    else:
        f1 = 0.0

    return EvaluationMetrics(
        total_results=total_results,
        total_included=total_included,
        found=found,
        missed=missed,
        not_in_pubmed=not_in_pubmed,
        missed_pubmed_indexed=missed_pubmed_indexed,
        recall_overall=recall_overall,
        recall_pubmed_only=recall_pubmed,
        precision=precision,
        nnr=nnr,
        f1_score=f1,
    )


def match_studies(
    search_results: PubMedSearchResults,
    included_studies: list[IncludedStudy],
) -> list[MatchResult]:
    """Match included studies against search results, returning detailed results."""
    results = []
    for study in included_studies:
        match = None
        if study.doi:
            match = search_results.match_by_doi(study.doi)
        if not match and study.pmid:
            match = search_results.match_by_pmid(study.pmid)

        results.append(MatchResult(
            study=study,
            matched=match is not None,
            match_info=match,
        ))

    return results
