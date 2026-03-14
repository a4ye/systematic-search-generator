"""Generate a PubMed query from a PROSPERO PDF using a single-shot prompt, then evaluate it."""

import argparse
import json
import math
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from Bio import Entrez, Medline

from src.cache.pubmed_index_cache import PubMedIndexCache
from src.cache.query_results_cache import QueryResultsCache
from src.compare_search import IncludedStudy, extract_included_studies
from src.discovery.study_finder import StudyFinder
from src.evaluation.metrics import EvaluationMetrics, calculate_metrics_with_pubmed_check, match_studies
from src.llm.openai_client import OpenAIClient
from src.mesh import MeshDB
from src.pipeline.config import PipelineConfig
from src.pubmed.search_executor import PubMedExecutor, PubMedSearchResults

# ── Configuration ────────────────────────────────────────────────────────────
MODEL = "gpt-5.3-chat-latest"

QUERY_PROMPT = """\
Given a systematic review plan, generate a PubMed Boolean search query optimized for systematic review searching (target roughly <20,000 PubMed results).

Goal:
Maximize sensitivity.

Instructions:

1. Identify the core concept blocks from the research question.
   - Usually 2–3 blocks total.
   - Include:
     • the disease/condition
     • the main phenomenon/exposure/topic being studied
     • a population modifier only if it is essential (e.g., early-onset, pediatric).

2. Only include concept blocks that define the topic of the review.
   - Do NOT add blocks for outcomes, measurements, or diagnostic tests unless they define eligibility.

3. Within each concept block:
   - Combine synonyms using OR.
   - Include both MeSH terms and free-text synonyms.

4. Restrict free-text terms to title/abstract fields using [tiab].

5. Prefer literature vocabulary used by authors rather than protocol wording.

6. Avoid overly generic biomedical terms that retrieve large irrelevant literature (e.g., risk*, detect*, factor*, outcome*).

7. Avoid very broad MeSH terms (e.g., "Adult"[Mesh]) that explode the search.

8. Prefer umbrella terms (e.g., symptom*, clinical presentation) rather than enumerating many specific items unless required.

9. Use adjacency logic or combined conditions only when it improves precision without reducing recall.

10. Keep the search concise:
    - remove redundant synonyms
    - avoid unnecessary numeric age phrases.

11. If known relevant papers are provided below, use their MeSH terms, keywords, and vocabulary to inform your term selection. Ensure the query would plausibly retrieve these papers.

Output:
Return the final PubMed Boolean query in one line only.
"""

SUPPLEMENT_PROMPT = """\
You previously generated a PubMed Boolean query for this systematic review, but it missed some known relevant papers.

Task:
Generate a supplementary PubMed query (not a full rewrite) that would capture the missed papers.

Rules:
- Focus on missing vocabulary and indexing terms.
- Do NOT repeat the original query.
- This supplementary query will be run separately and results will be merged.

Output:
Return the supplementary PubMed Boolean query in one line only.
"""

EXTRACT_PROMPT = """\
Extract the systematic review plan from this PROSPERO protocol document. Use the exact wording from the document — do not paraphrase or interpret.

Output the plan in this exact format:

Here is the plan for the systematic review:

Title: [exact title from the document]

Condition or domain being studied: [exact wording from the document]

PICO (Outcome is excluded):
Population
[exact population description]
Intervention(s) or exposure(s)
[exact intervention/exposure description, including any numbered research questions and listed items]
Comparator(s) or control(s)
[exact comparator description]

Important:
- Copy text verbatim from the document. Do not reword, summarize, or add interpretation.
- Include all listed items (e.g., signs, symptoms, exposures) exactly as written.
- If the protocol has multiple research questions, preserve the Q1/Q2/Q3 structure.
- Exclude outcomes entirely.
- If a field is not present in the document, write "Not specified".
"""

SEED_PAPERS_DIR = Path("seed_papers")
SPLASH_FILE = Path("splash_messages.txt")


def load_seed_papers(study_id: str, study_name: str, n: int) -> list[dict] | None:
    """Load n random valid seed papers for a study.

    Skips papers that are missing title and abstract (broken/empty entries).
    Returns None if no seed paper file exists for this study.
    """
    # Try exact match first, then fallback to ID prefix
    path = SEED_PAPERS_DIR / f"{study_id} - {study_name}.json"
    if not path.exists():
        matches = list(SEED_PAPERS_DIR.glob(f"{study_id} - *.json"))
        if not matches:
            return None
        path = matches[0]

    with open(path) as f:
        data = json.load(f)

    papers = data.get("papers", [])
    # Filter out broken/empty entries
    valid = [p for p in papers if p.get("title") and p.get("abstract")]
    if not valid:
        return None

    if len(valid) <= n:
        return valid

    sampled = random.sample(valid, n)
    return sampled


# Mapping from single-letter codes to seed paper fields
SEED_FIELD_CODES = {
    "t": "title",
    "a": "abstract",
    "m": "mesh_terms",
    "k": "keywords",
}


def format_seed_papers(papers: list[dict], fields: str = "tamk") -> str:
    """Format seed papers into a text block for the LLM prompt.

    Fields is a string of single-letter codes controlling which parts to include:
      t = title, a = abstract, m = MeSH terms, k = keywords
    """
    lines = []
    lines.append("Here are some known relevant papers that should be captured by the search:")
    lines.append("")
    for i, p in enumerate(papers, 1):
        lines.append(f"Paper {i}:")
        if "t" in fields and p.get("title"):
            lines.append(f"  Title: {p['title']}")
        if "a" in fields and p.get("abstract"):
            abstract = p["abstract"]
            if len(abstract) > 800:
                abstract = abstract[:800] + "..."
            lines.append(f"  Abstract: {abstract}")
        if "m" in fields and p.get("mesh_terms"):
            lines.append(f"  MeSH Terms: {', '.join(p['mesh_terms'])}")
        if "k" in fields and p.get("keywords"):
            lines.append(f"  Keywords: {', '.join(p['keywords'])}")
        lines.append("")
    return "\n".join(lines)


def load_splash_text() -> str:
    """Load a random splash message from the splash text file."""
    try:
        lines = [l.strip() for l in SPLASH_FILE.read_text().splitlines()]
        choices = [l for l in lines if l and not l.startswith("#")]
        if choices:
            return random.choice(choices)
    except Exception:
        pass
    return "Crunching citations..."


def load_splash_messages() -> list[str]:
    """Load all splash messages from file."""
    try:
        lines = [l.strip() for l in SPLASH_FILE.read_text().splitlines()]
        return [l for l in lines if l and not l.startswith("#")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Citation DOI enrichment helpers
# ---------------------------------------------------------------------------

def _extract_dois_from_medline_record(record: dict) -> list[str]:
    """Extract DOI(s) from a MEDLINE record."""
    dois = set()
    for aid in record.get("AID", []):
        if "[doi]" in aid:
            doi = aid.replace("[doi]", "").strip().lower()
            if doi:
                dois.add(doi)

    lid = record.get("LID", "")
    if isinstance(lid, list):
        lid = " ".join(lid)
    if "[doi]" in lid:
        doi = lid.split("[doi]")[0].strip().lower()
        if doi:
            dois.add(doi)

    return sorted(dois)


def fetch_dois_for_pmids(
        pmids: list[str],
        email: str,
        api_key: str | None,
        rate_delay: float,
        batch_size: int = 200,
) -> dict[str, list[str]]:
    """Fetch DOI mappings for PMIDs via Entrez MEDLINE."""
    if not pmids:
        return {}

    Entrez.email = email
    if api_key:
        Entrez.api_key = api_key

    pmid_to_dois: dict[str, list[str]] = {}
    for start in range(0, len(pmids), batch_size):
        batch = pmids[start:start + batch_size]
        time.sleep(rate_delay)
        handle = Entrez.efetch(
            db="pubmed",
            id=",".join(batch),
            rettype="medline",
            retmode="text",
        )
        try:
            records = list(Medline.parse(handle))
        finally:
            handle.close()

        for rec in records:
            pmid = rec.get("PMID")
            if not pmid:
                continue
            dois = _extract_dois_from_medline_record(rec)
            if dois:
                pmid_to_dois[pmid] = dois

    return pmid_to_dois


def fetch_similar_pmids(
        seed_pmids: list[str],
        email: str,
        api_key: str | None,
        rate_delay: float,
        per_seed: int,
) -> dict[str, list[str]]:
    """Fetch similar articles from PubMed for each seed PMID."""
    if not seed_pmids or per_seed <= 0:
        return {}

    Entrez.email = email
    if api_key:
        Entrez.api_key = api_key

    results: dict[str, list[str]] = {}
    for pmid in seed_pmids:
        time.sleep(rate_delay)
        handle = Entrez.elink(
            dbfrom="pubmed",
            db="pubmed",
            id=pmid,
            linkname="pubmed_pubmed",
            retmax=per_seed,
        )
        try:
            record = Entrez.read(handle)
        finally:
            handle.close()

        pmids: list[str] = []
        try:
            linksets = record or []
            for linkset in linksets:
                for db in linkset.get("LinkSetDb", []):
                    for link in db.get("Link", []):
                        pid = link.get("Id")
                        if pid:
                            pmids.append(str(pid))
        except Exception:
            pmids = []

        if pmids:
            results[pmid] = pmids[:per_seed]

    return results


def count_found_studies(
        search_results: PubMedSearchResults,
        included_studies: list[IncludedStudy],
) -> int:
    """Count how many included studies match the search results."""
    found = 0
    for study in included_studies:
        match = None
        if study.doi:
            match = search_results.match_by_doi(study.doi)
        if not match and study.pmid:
            match = search_results.match_by_pmid(study.pmid)
        if match:
            found += 1
    return found


def get_missed_seed_papers(
        seed_papers: list[dict],
        search_results: PubMedSearchResults,
) -> tuple[list[dict], int]:
    """Return seed papers missed by the search results and count unchecked seeds."""
    missed: list[dict] = []
    unchecked = 0
    for sp in seed_papers:
        pmid = sp.get("pmid")
        doi = sp.get("doi")
        if not pmid and not doi:
            unchecked += 1
            continue
        matched = False
        if doi:
            doi_norm = re.sub(r"^https?://doi\\.org/", "", str(doi), flags=re.IGNORECASE).lower()
            if search_results.match_by_doi(doi_norm):
                matched = True
        if not matched and pmid:
            pmid_str = str(pmid).strip()
            if search_results.match_by_pmid(pmid_str):
                matched = True
        if not matched:
            missed.append(sp)
    return missed, unchecked


def merge_seed_papers_into_included(
        included_studies: list[IncludedStudy],
        seed_papers: list[dict] | None,
) -> tuple[list[IncludedStudy], int]:
    """Merge seed papers into included studies for evaluation."""
    if not seed_papers:
        return included_studies, 0
    existing_pmids = {s.pmid for s in included_studies if s.pmid}
    existing_dois = {s.doi for s in included_studies if s.doi}
    merged = list(included_studies)
    added = 0
    for sp in seed_papers:
        pmid = sp.get("pmid")
        doi = sp.get("doi")
        if pmid:
            pmid = str(pmid).strip()
        if doi:
            doi = re.sub(r"^https?://doi\\.org/", "", str(doi), flags=re.IGNORECASE).lower()
        if not pmid and not doi:
            continue
        if pmid and pmid in existing_pmids:
            continue
        if doi and doi in existing_dois:
            continue
        merged.append(IncludedStudy(doi=doi, pmid=pmid, title=sp.get("title")))
        if pmid:
            existing_pmids.add(pmid)
        if doi:
            existing_dois.add(doi)
        added += 1
    return merged, added


_MESH_TERM_RE = re.compile(r"\"([^\"]+)\"\[(?:MeSH|Mesh)\]")
_MESH_TERM_UNQUOTED_RE = re.compile(r"\b([^\s\)\(]+?)\[(?:MeSH|Mesh)\]")


def _format_tiab(term: str) -> str:
    term = " ".join(term.strip().split())
    if not term:
        return ""
    if "*" in term:
        return f"{term}[tiab]"
    if " " in term:
        return f"\"{term}\"[tiab]"
    return f"{term}[tiab]"


def _format_ti(term: str) -> str:
    term = " ".join(term.strip().split())
    if not term:
        return ""
    if "*" in term:
        return f"{term}[ti]"
    if " " in term:
        return f"\"{term}\"[ti]"
    return f"{term}[ti]"


def expand_mesh_entry_terms(
        query: str,
        mesh_db: MeshDB,
        max_terms: int,
) -> tuple[str, dict]:
    """Expand MeSH terms with entry-term free-text variants."""
    lower_query = query.lower()
    added_lower: set[str] = set()
    cache: dict[str, str] = {}
    mesh_found = 0
    mesh_expanded = 0
    entry_added = 0
    detected_terms: list[str] = []
    debug_samples: list[tuple[str, int]] = []

    def _normalize_mesh_term(term: str) -> str:
        return term.strip().strip(",")

    def repl(match: re.Match) -> str:
        nonlocal mesh_found, mesh_expanded, entry_added
        mesh_found += 1
        term = _normalize_mesh_term(match.group(1))
        detected_terms.append(term)
        if term in cache:
            return cache[term]
        entry_terms = mesh_db.entry_terms(term, max_terms=max_terms)
        additions: list[str] = []
        for entry in entry_terms:
            tiab = _format_tiab(entry)
            tiab_lower = tiab.lower() if tiab else ""
            if tiab and tiab_lower not in lower_query and tiab_lower not in added_lower:
                additions.append(tiab)
                added_lower.add(tiab_lower)
        if not additions:
            cache[term] = match.group(0)
            return match.group(0)
        mesh_expanded += 1
        entry_added += len(additions)
        debug_samples.append((term, len(additions)))
        replacement = "(" + match.group(0) + " OR " + " OR ".join(additions) + ")"
        cache[term] = replacement
        return replacement

    expanded = _MESH_TERM_RE.sub(repl, query)
    expanded = _MESH_TERM_UNQUOTED_RE.sub(repl, expanded)
    stats = {
        "mesh_terms_found": mesh_found,
        "mesh_terms_expanded": mesh_expanded,
        "entry_terms_added": entry_added,
        "mesh_terms_detected": detected_terms,
        "mesh_terms_samples": debug_samples[:5],
        "mesh_year": mesh_db.loaded_year(),
    }
    return expanded, stats


# ── TF-IDF term mining (seed papers) ────────────────────────────────────────

_TFIDF_MIN_TOKEN_LEN = 3
_TFIDF_MAX_DOC_FRACTION = 0.8
_TFIDF_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by",
    "for", "from", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "they", "this", "those", "to", "was", "were",
    "with", "within", "without", "over", "under", "between", "among",
    "before", "after", "during", "per", "via", "vs", "versus",
    "we", "our", "ours", "you", "your", "i", "me", "my",
    "et", "al",
    "study", "studies", "trial", "trials", "randomized", "randomised",
    "randomization", "randomisation", "patient", "patients", "participant",
    "participants", "subject", "subjects", "cohort", "cohorts",
    "group", "groups", "case", "cases", "control", "controls",
    "analysis", "analyses", "result", "results", "outcome", "outcomes",
    "effect", "effects", "risk", "risks", "association", "associated",
    "associations", "evidence", "data", "method", "methods",
    "clinical", "systematic", "review", "reviews", "meta", "protocol",
    "disease", "disorder", "disorders", "syndrome", "condition",
    "treatment", "therapy", "management", "intervention",
    "baseline", "follow", "followup", "follow-up", "significant",
    "significance", "including", "include", "includes", "based",
}


def _tokenize_tfidf(text: str) -> list[str]:
    if not text:
        return []
    cleaned = text.lower()
    cleaned = re.sub(r"[-_/]", " ", cleaned)
    cleaned = re.sub(r"[^a-z\s]", " ", cleaned)
    tokens: list[str] = []
    for token in cleaned.split():
        if len(token) < _TFIDF_MIN_TOKEN_LEN:
            continue
        if token in _TFIDF_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def extract_tfidf_terms(
        papers: list[dict],
        max_terms: int,
) -> tuple[list[str], dict]:
    """Extract TF-IDF ranked terms from seed papers (title + abstract)."""
    docs: list[list[str]] = []
    skipped = 0
    for paper in papers:
        parts = [paper.get("title") or "", paper.get("abstract") or ""]
        text = " ".join(p for p in parts if p)
        tokens = _tokenize_tfidf(text)
        if tokens:
            docs.append(tokens)
        else:
            skipped += 1

    if not docs:
        return [], {"docs_used": 0, "docs_skipped": skipped, "terms_scored": 0}

    doc_counts: list[tuple[Counter, int]] = []
    df: Counter = Counter()
    for tokens in docs:
        counts = Counter(tokens)
        doc_counts.append((counts, len(tokens)))
        df.update(counts.keys())

    n_docs = len(docs)
    max_doc_fraction = _TFIDF_MAX_DOC_FRACTION if n_docs >= 3 else 1.0
    scores: dict[str, float] = {}
    for term, doc_freq in df.items():
        if doc_freq / n_docs > max_doc_fraction:
            continue
        idf = math.log((n_docs + 1) / (doc_freq + 1)) + 1.0
        score = 0.0
        for counts, total in doc_counts:
            if not total:
                continue
            tf = counts.get(term, 0) / total
            if tf:
                score += tf * idf
        if score > 0:
            scores[term] = score

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    terms = [term for term, _ in ranked[:max_terms]]
    stats = {
        "docs_used": n_docs,
        "docs_skipped": skipped,
        "terms_scored": len(scores),
        "max_doc_fraction": max_doc_fraction,
    }
    return terms, stats


def filter_tfidf_terms(terms: list[str], query: str) -> list[str]:
    if not query:
        return terms
    query_lower = query.lower()
    filtered: list[str] = []
    for term in terms:
        if not term:
            continue
        if re.search(rf"\\b{re.escape(term)}\\b", query_lower):
            continue
        filtered.append(term)
    return filtered


def build_tfidf_query(terms: list[str], field: str = "tiab") -> str:
    if field == "ti":
        formatter = _format_ti
    else:
        formatter = _format_tiab
    formatted = [formatter(t) for t in terms if formatter(t)]
    if not formatted:
        return ""
    return "(" + " OR ".join(formatted) + ")"


# ── End configuration ────────────────────────────────────────────────────────


@dataclass
class StudyResult:
    """Results from running the pipeline on a single study."""

    study_id: str
    study_name: str
    llm_metrics: object  # MetricsResult
    human_metrics: object | None  # MetricsResult or None
    llm_queries: list[str] | None = None
    merged_query: str | None = None
    executed_query: str | None = None
    human_query: str | None = None
    query_prompt: str | None = None
    missed_papers: list[dict] | None = None
    citation_stats: dict | None = None  # {total, new, hits}
    supplement_query: str | None = None
    supplement_stats: dict | None = None
    similar_stats: dict | None = None
    mesh_entry_stats: dict | None = None
    tfidf_query: str | None = None
    tfidf_stats: dict | None = None
    error: str | None = None


def _calculate_total_steps(
        n_runs: int,
        include_human: bool,
        two_pass: bool,
        similar: bool,
        tfidf: bool,
        two_pass_max: int,
) -> int:
    """Calculate the total number of progress steps for a study pipeline.

    Steps:
      1. Load included studies
      2. Extract plan from PDF
      3. Generate N queries (n_runs steps)
      4. Fetch PubMed results for N queries (n_runs steps)
      5. Evaluate LLM metrics
      6-8. (if human) Extract/load strategy, fetch PubMed, evaluate metrics
    """
    total = 2 + n_runs + 1 + 1  # load + extract + generate(n) + fetch(1) + evaluate
    if two_pass:
        total += 2 * max(1, two_pass_max)  # supplement LLM + supplement fetch (max passes)
    if similar:
        total += 1  # similar articles fetch
    if tfidf:
        total += 1  # TF-IDF supplemental query
    if include_human:
        total += 3  # strategy extract + fetch + evaluate
    return total


def extract_query_from_response(text: str) -> str:
    """Extract the PubMed query from an LLM response.

    Handles responses that include explanation text, code fences, etc.
    """
    # Strip code fences
    text = re.sub(r"```(?:\w+)?\n?", "", text).strip()

    # If the response contains a line starting with (, that's likely the query
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("(") and "[" in line:
            return line

    # Otherwise return the longest line containing boolean operators
    candidates = []
    for line in text.splitlines():
        line = line.strip()
        if " AND " in line or " OR " in line:
            candidates.append(line)

    if candidates:
        return max(candidates, key=len)

    # Fallback: return entire text stripped
    return text.strip()


def print_study_table(
        console: Console,
        llm_metrics: EvaluationMetrics,
        human_metrics: EvaluationMetrics | None,
        allow_float_counts: bool = False,
        title: str | None = None,
):
    """Print the comparison table."""
    m = llm_metrics
    h = human_metrics

    count_decimals = 1 if allow_float_counts else 0

    def fmt_count(val: float) -> str:
        if allow_float_counts:
            return f"{val:.1f}"
        return f"{int(val)}"

    def fmt_diff_count(gen_val, human_val, higher_is_better=True):
        if h is None:
            return "[dim]—[/dim]"
        diff = gen_val - human_val
        if human_val != 0:
            pct = (diff / human_val) * 100
            if allow_float_counts:
                s = f"{diff:+.{count_decimals}f} ({pct:+.0f}%)"
            else:
                s = f"{diff:+d} ({pct:+.0f}%)"
        else:
            s = f"{diff:+.{count_decimals}f}" if allow_float_counts else f"{diff:+d}"
        if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
            return f"[green]{s}[/green]"
        elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
            return f"[red]{s}[/red]"
        return s

    def fmt_diff_pct(gen_val, human_val, higher_is_better=True):
        if h is None:
            return "[dim]—[/dim]"
        diff = gen_val - human_val
        s = f"{diff * 100:+.1f}%"
        if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
            return f"[green]{s}[/green]"
        elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
            return f"[red]{s}[/red]"
        return s

    def fmt_diff_float(gen_val, human_val, higher_is_better=True):
        if h is None:
            return "[dim]—[/dim]"
        if gen_val == float("inf") or human_val == float("inf"):
            return "[dim]—[/dim]"
        diff = gen_val - human_val
        if human_val != 0:
            pct = (diff / human_val) * 100
            s = f"{diff:+.1f} ({pct:+.0f}%)"
        else:
            s = f"{diff:+.1f}"
        if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
            return f"[green]{s}[/green]"
        elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
            return f"[red]{s}[/red]"
        return s

    na = "[dim]—[/dim]"

    if title:
        console.print(f"[bold]{title}[/bold]")

    console.print(f"Included studies:       {m.total_included}")
    console.print(f"Not indexed in PubMed:  {m.not_in_pubmed}")
    console.print(f"PubMed-indexed:         {m.pubmed_indexed_count}")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric", style="dim", width=22)
    table.add_column("Generated", justify="right", width=18)
    table.add_column("Human", justify="right", width=18)
    table.add_column("Diff", justify="right", width=18)

    table.add_row(
        "Search results",
        fmt_count(m.total_results),
        fmt_count(h.total_results) if h else na,
        fmt_diff_count(m.total_results, h.total_results, higher_is_better=False) if h else na,
    )
    table.add_row(
        "Captured",
        f"{fmt_count(m.found)} / {fmt_count(m.pubmed_indexed_count)}",
        f"{fmt_count(h.found)} / {fmt_count(h.pubmed_indexed_count)}" if h else na,
        fmt_diff_count(m.found, h.found) if h else na,
    )
    table.add_row(
        "Missed (in PubMed)",
        fmt_count(m.missed_pubmed_indexed),
        fmt_count(h.missed_pubmed_indexed) if h else na,
        fmt_diff_count(
            m.missed_pubmed_indexed,
            h.missed_pubmed_indexed,
            higher_is_better=False,
        )
        if h
        else na,
    )
    table.add_row(
        "Recall (overall)",
        f"{m.recall_overall * 100:.1f}%  ({fmt_count(m.found)}/{fmt_count(m.total_included)})",
        f"{h.recall_overall * 100:.1f}%  ({fmt_count(h.found)}/{fmt_count(h.total_included)})" if h else na,
        fmt_diff_pct(m.recall_overall, h.recall_overall) if h else na,
    )
    table.add_row(
        "Recall (PubMed only)",
        f"{m.recall_pubmed_only * 100:.1f}%  ({fmt_count(m.found)}/{fmt_count(m.pubmed_indexed_count)})",
        f"{h.recall_pubmed_only * 100:.1f}%  ({fmt_count(h.found)}/{fmt_count(h.pubmed_indexed_count)})" if h else na,
        fmt_diff_pct(m.recall_pubmed_only, h.recall_pubmed_only) if h else na,
    )

    precision_diff = fmt_diff_pct(m.precision, h.precision) if h else na
    if h and h.precision > 0:
        rel = m.precision / h.precision
        color = "green" if rel >= 1.0 else "red"
        precision_diff += f"  [{color}]{rel:.1f}x[/{color}]"

    table.add_row(
        "Precision",
        f"{m.precision * 100:.2f}%  ({fmt_count(m.found)}/{fmt_count(m.total_results)})",
        f"{h.precision * 100:.2f}%  ({fmt_count(h.found)}/{fmt_count(h.total_results)})" if h else na,
        precision_diff,
    )
    table.add_row(
        "NNR",
        f"{m.nnr:.1f}",
        f"{h.nnr:.1f}" if h else na,
        fmt_diff_float(m.nnr, h.nnr, higher_is_better=False) if h else na,
    )

    console.print(table)
    console.print()


def aggregate_metrics(metrics_list: list[EvaluationMetrics]) -> EvaluationMetrics:
    """Aggregate metrics across multiple studies."""
    total_results = sum(m.total_results for m in metrics_list)
    total_included = sum(m.total_included for m in metrics_list)
    found = sum(m.found for m in metrics_list)
    not_in_pubmed = sum(m.not_in_pubmed for m in metrics_list)
    missed_pubmed_indexed = sum(m.missed_pubmed_indexed for m in metrics_list)
    missed = total_included - found
    pubmed_indexed = total_included - not_in_pubmed

    recall_overall = found / total_included if total_included > 0 else 0.0
    recall_pubmed = found / pubmed_indexed if pubmed_indexed > 0 else 0.0
    precision = found / total_results if total_results > 0 else 0.0
    nnr = total_results / found if found > 0 else float("inf")
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


def mean_metrics(metrics_list: list[EvaluationMetrics]) -> EvaluationMetrics:
    """Compute simple mean of per-study metrics."""
    n = len(metrics_list)
    if n == 0:
        return EvaluationMetrics(
            total_results=0,
            total_included=0,
            found=0,
            missed=0,
            not_in_pubmed=0,
            missed_pubmed_indexed=0,
            recall_overall=0.0,
            recall_pubmed_only=0.0,
            precision=0.0,
            nnr=float("inf"),
            f1_score=0.0,
        )

    total_results = sum(m.total_results for m in metrics_list) / n
    total_included = sum(m.total_included for m in metrics_list) / n
    found = sum(m.found for m in metrics_list) / n
    not_in_pubmed = sum(m.not_in_pubmed for m in metrics_list) / n
    missed_pubmed_indexed = sum(m.missed_pubmed_indexed for m in metrics_list) / n
    missed = total_included - found

    recall_overall = sum(m.recall_overall for m in metrics_list) / n
    recall_pubmed = sum(m.recall_pubmed_only for m in metrics_list) / n
    precision = sum(m.precision for m in metrics_list) / n

    finite_nnrs = [m.nnr for m in metrics_list if m.nnr != float("inf")]
    nnr = sum(finite_nnrs) / len(finite_nnrs) if finite_nnrs else float("inf")

    finite_f1 = [m.f1_score for m in metrics_list]
    f1 = sum(finite_f1) / n

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


def run_study(
        study_id_arg: str,
        args: argparse.Namespace,
        config: PipelineConfig,
        finder: StudyFinder,
        client: OpenAIClient,
        pubmed: PubMedExecutor,
        index_cache: PubMedIndexCache,
        query_cache: QueryResultsCache,
        console: Console,
) -> StudyResult | None:
    """Run the full pipeline for a single study. Returns StudyResult or None on skip."""
    rate_delay = 0.1 if config.entrez_api_key else 0.34

    study = finder.get_study(study_id_arg)
    if not study:
        console.print(f"[red]Study {study_id_arg} not found[/red]")
        return None

    if not study.prospero_pdf:
        console.print(f"[red]Study {study_id_arg} has no PROSPERO PDF[/red]")
        return None

    console.print(f"\n[bold]Study: {study.study_id} - {study.name}[/bold]")

    # Extract-only mode (no progress bar needed)
    if args.extract:
        console.print(f"\n[dim]Extracting plan with {MODEL}...[/dim]")
        response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=study.prospero_pdf)
        console.print(
            f"[dim]Tokens: {response.prompt_tokens} in / {response.completion_tokens} out, "
            f"{response.generation_time:.1f}s[/dim]\n"
        )
        console.print(response.content, markup=False, highlight=False)
        return None

    if not study.included_studies_xlsx:
        console.print(f"[red]Study {study_id_arg} has no included studies file[/red]")
        return None

    n_runs = args.n
    include_human = not args.no_human and study.search_strategy_docx is not None
    total_steps = _calculate_total_steps(
        n_runs,
        include_human,
        args.two_pass,
        args.similar > 0,
        args.tfidf,
        args.two_pass_max,
    )

    splash_messages = load_splash_messages()
    if not splash_messages:
        splash_messages = [load_splash_text()]
    splash_colors = ["bright_magenta", "bright_cyan", "bright_green", "bright_yellow", "bright_blue"]
    last_splash_change = time.time()
    splash_interval = random.uniform(5, 10)
    splash_index = 0
    color_index = 0

    def _shimmer_text(text: str, offset: int = 0) -> str:
        if not text:
            return text
        parts = []
        for i, ch in enumerate(text):
            color = splash_colors[(i + offset) % len(splash_colors)]
            parts.append(f"[bold {color}]{ch}[/]")
        return "".join(parts)

    def maybe_rotate_splash() -> str:
        nonlocal last_splash_change, splash_interval, splash_index, color_index
        now = time.time()
        if now - last_splash_change >= splash_interval:
            last_splash_change = now
            splash_interval = random.uniform(5, 10)
            splash_index = (splash_index + 1) % len(splash_messages)
        msg = splash_messages[splash_index]
        color_index = (color_index + 1) % len(splash_colors)
        return _shimmer_text(msg, color_index)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("[dim]{task.fields[splash]}[/dim]"),
        BarColumn(bar_width=25),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        expand=False,
    )

    with progress:
        task_id = progress.add_task(
            "Loading included studies...",
            total=total_steps,
            splash=maybe_rotate_splash(),
        )
        log = progress.console
        progress.refresh()
        def step(description: str) -> None:
            progress.update(task_id, description=description, advance=1, splash=maybe_rotate_splash())

        # Load included studies
        included_result = extract_included_studies(str(study.included_studies_xlsx))
        step("Loading included studies")
        if not included_result.is_valid:
            log.print(f"[red]Error loading included studies: {included_result.error}[/red]")
            return None

        included_studies = included_result.studies
        log.print(f"Included studies: {len(included_studies)}")

        # Step 1: Extract plan from PROSPERO PDF
        progress.update(task_id, description=f"Extracting plan with {MODEL}...", splash=maybe_rotate_splash())
        extract_response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=study.prospero_pdf)
        step("Extracted plan")
        plan_info = extract_response.content
        log.print(
            f"[dim]  Tokens: {extract_response.prompt_tokens} in / {extract_response.completion_tokens} out, "
            f"{extract_response.generation_time:.1f}s[/dim]"
        )

        # Step 2: Load seed papers if requested
        seed_section = ""
        seed_papers = None
        if args.seeds > 0:
            progress.update(task_id, description="Loading seed papers...", splash=maybe_rotate_splash())
            seed_papers = load_seed_papers(study.study_id, study.name, args.seeds)
            if seed_papers:
                seed_section = "\n\n" + format_seed_papers(seed_papers, fields=args.seed_fields)
                field_names = [SEED_FIELD_CODES[c] for c in args.seed_fields if c in SEED_FIELD_CODES]
                log.print(f"[dim]  Loaded {len(seed_papers)} seed papers ({', '.join(field_names)})[/dim]")
            else:
                log.print("[yellow]  No valid seed papers found for this study[/yellow]")

        eval_included_studies, added_seeds = merge_seed_papers_into_included(
            included_studies,
            seed_papers,
        )
        if added_seeds:
            log.print(f"[dim]  Added {added_seeds} seed paper(s) to evaluation set[/dim]")
        if eval_included_studies is not included_studies:
            log.print(f"[dim]  Included studies (with seeds): {len(eval_included_studies)}[/dim]")

        # Step 3: Generate query from extracted plan
        query_prompt = QUERY_PROMPT + "\n" + plan_info + seed_section
        if args.double_prompt:
            query_prompt = query_prompt + "\n\n---\n\n" + query_prompt
            log.print("[dim]  (prompt doubled)[/dim]")

        # Save the final composed prompt
        prompt_dir = Path("temp")
        prompt_dir.mkdir(exist_ok=True)
        (prompt_dir / "final-prompt.txt").write_text(query_prompt)

        def _generate_one(run_i: int) -> tuple[int, str, int, int, float]:
            resp = client.generate_text(prompt=query_prompt)
            q = extract_query_from_response(resp.content)
            return run_i, q, resp.prompt_tokens, resp.completion_tokens, resp.generation_time

        if n_runs == 1:
            progress.update(task_id, description="Generating query...", splash=maybe_rotate_splash())
            _, q, pt, ct, gt = _generate_one(0)
            step("Generated query")
            generated_queries = [q]
            log.print(f"[dim]  Tokens: {pt} in / {ct} out, {gt:.1f}s[/dim]")
        else:
            log.print(f"[dim]  Launching {n_runs} LLM calls in parallel...[/dim]")
            generated_queries = [""] * n_runs
            completed_runs = 0
            with ThreadPoolExecutor(max_workers=n_runs) as executor:
                futures = {executor.submit(_generate_one, i): i for i in range(n_runs)}
                for future in as_completed(futures):
                    run_i, q, pt, ct, gt = future.result()
                    generated_queries[run_i] = q
                    completed_runs += 1
                    step(f"Generated query {completed_runs}/{n_runs}")
                    log.print(
                        f"[dim]  Run {run_i + 1}/{n_runs} done — {pt} in / {ct} out, {gt:.1f}s[/dim]"
                    )

        def fetch_or_cached(
                query: str,
                label: str,
                max_count: int = 50000,
                known_count: int | None = None,
        ) -> PubMedSearchResults | None:
            cached_result = query_cache.get(query)
            if cached_result:
                if cached_result.result_count > max_count:
                    log.print(
                        f"[red]{label} too broad (cached): {cached_result.result_count:,} results "
                        f"(max {max_count:,})[/red]"
                    )
                    step(f"{label}: too broad")
                    return None
                log.print(f"[dim]{label}: using cached PubMed results[/dim]")
                step(f"{label}: cached")
                return PubMedSearchResults.from_cached(
                    query=query,
                    pmids=cached_result.pmids,
                    result_count=cached_result.result_count,
                    doi_to_pmid=cached_result.doi_to_pmid,
                )

            if known_count is None:
                progress.update(
                    task_id,
                    description=f"{label}: counting results...",
                    splash=maybe_rotate_splash(),
                )
            result_count = known_count if known_count is not None else pubmed.count_results(query)
            if result_count > max_count:
                log.print(
                    f"[red]{label} too broad: {result_count:,} results (max {max_count:,})[/red]"
                )
                step(f"{label}: too broad")
                return None

            progress.update(task_id, description=f"{label}: fetching {result_count:,} results...",
                            splash=maybe_rotate_splash())
            batch_task_id = None

            def _batch_progress(done: int, total: int) -> None:
                nonlocal batch_task_id
                if total <= 0:
                    return
                if batch_task_id is None:
                    batch_task_id = progress.add_task(
                        f"{label}: batches",
                        total=total,
                        splash=maybe_rotate_splash(),
                    )
                progress.update(batch_task_id, completed=done, splash=maybe_rotate_splash())

            search_results = pubmed.execute_query_fast(
                query,
                max_results=config.max_pubmed_results,
                progress_callback=_batch_progress,
            )
            if batch_task_id is not None:
                progress.remove_task(batch_task_id)
            step(f"{label}: fetched {result_count:,}")

            pmids = list(search_results.pmid_map.keys())
            doi_to_pmid = {doi: info["pmid"] for doi, info in search_results.doi_map.items()}
            query_cache.set(query, pmids, search_results.result_count, doi_to_pmid)

            return search_results

        # Build final query: OR together unique queries if n > 1
        unique_queries = list(dict.fromkeys(generated_queries))  # preserve order, dedupe
        if len(unique_queries) > 1:
            final_query = " OR ".join(f"({q})" for q in unique_queries)
            merged_query = final_query
        else:
            final_query = unique_queries[0]
            merged_query = None

        mesh_entry_stats = None
        if args.mesh_entry_terms:
            try:
                mesh_db = MeshDB(config.cache_dir)
                expanded_query, stats = expand_mesh_entry_terms(
                    final_query,
                    mesh_db,
                    max_terms=args.mesh_entry_max,
                )
                mesh_entry_stats = stats
                if stats["entry_terms_added"] > 0:
                    final_query = expanded_query
                    log.print(
                        f"[dim]  MeSH entry terms: +{stats['entry_terms_added']} "
                        f"across {stats['mesh_terms_expanded']}/{stats['mesh_terms_found']} "
                        f"MeSH terms[/dim]"
                    )
                else:
                    detected = stats.get("mesh_terms_detected", [])
                    log.print(
                        f"[dim]  MeSH entry terms: no additions "
                        f"(detected {len(detected)} headings)[/dim]"
                    )
                if stats.get("mesh_terms_samples"):
                    samples = ", ".join(f"{t} (+{n})" for t, n in stats["mesh_terms_samples"])
                    log.print(f"[dim]  MeSH samples: {samples}[/dim]")
            except Exception as exc:
                log.print(f"[yellow]MeSH entry-term expansion failed: {exc}[/yellow]")

        tfidf_terms: list[str] = []
        tfidf_term_stats: dict | None = None
        tfidf_skip_reason: str | None = None
        if args.tfidf:
            if not seed_papers:
                tfidf_skip_reason = "no_seed_papers"
            else:
                raw_terms, term_stats = extract_tfidf_terms(
                    seed_papers,
                    max_terms=max(1, args.tfidf_top * 3),
                )
                filtered_terms = filter_tfidf_terms(raw_terms, final_query)
                tfidf_terms = filtered_terms[: max(1, args.tfidf_top)]
                tfidf_term_stats = term_stats
                if tfidf_terms:
                    sample = ", ".join(tfidf_terms[:5])
                    suffix = "..." if len(tfidf_terms) > 5 else ""
                    log.print(f"[dim]  TF-IDF terms: {len(tfidf_terms)} ({sample}{suffix})[/dim]")
                else:
                    tfidf_skip_reason = "no_terms"

        # Execute the single (possibly merged) query against PubMed
        llm_results = fetch_or_cached(final_query, "LLM query")
        if llm_results is None:
            log.print("[red]No valid query results[/red]")
            return None

        supplement_query = None
        supplement_stats = None

        # Optional two-pass refinement: generate a supplemental query for missed seed papers
        if args.two_pass:
            if not seed_papers:
                log.print("[yellow]Two-pass enabled but no seed papers available; skipping[/yellow]")
                progress.advance(task_id, 2 * max(1, args.two_pass_max))
            else:
                max_passes = max(1, args.two_pass_max)
                pass_stats: list[dict] = []
                passes_run = 0

                while passes_run < max_passes:
                    missed_seed_papers, seed_unchecked = get_missed_seed_papers(
                        seed_papers,
                        llm_results,
                    )
                    if not missed_seed_papers:
                        log.print("[green]  Two-pass: all seed papers captured; stopping[/green]")
                        break

                    passes_run += 1
                    log.print(
                        f"[dim]  Two-pass {passes_run}/{max_passes}: {len(missed_seed_papers)} seed "
                        f"paper(s) missed ({seed_unchecked} unchecked)[/dim]"
                    )

                    supplement_seed_section = "\n\n" + format_seed_papers(
                        missed_seed_papers,
                        fields=args.seed_fields,
                    )
                    supplement_prompt = (
                            SUPPLEMENT_PROMPT
                            + "\n\nOriginal query:\n"
                            + final_query
                            + "\n\n"
                            + plan_info
                            + supplement_seed_section
                    )
                    progress.update(
                        task_id,
                        description=f"Generating supplement query {passes_run}...",
                        splash=maybe_rotate_splash(),
                    )
                    resp = client.generate_text(prompt=supplement_prompt)
                    supplement_query = extract_query_from_response(resp.content)
                    step(f"Generated supplement query {passes_run}")
                    log.print(
                        f"[dim]  Tokens: {resp.prompt_tokens} in / {resp.completion_tokens} out, "
                        f"{resp.generation_time:.1f}s[/dim]"
                    )

                    if not supplement_query:
                        log.print("[yellow]Supplement query was empty; stopping[/yellow]")
                        progress.advance(task_id, 1)
                        break

                    supplement_results = fetch_or_cached(
                        supplement_query,
                        f"Supplement query {passes_run}",
                    )
                    if supplement_results is None:
                        log.print("[yellow]Supplement query produced no results; stopping[/yellow]")
                        pass_stats.append({
                            "pass": passes_run,
                            "missed_seed_count": len(missed_seed_papers),
                            "seed_unchecked": seed_unchecked,
                            "total_pmids": 0,
                            "new_pmids": 0,
                            "dup_pmids": 0,
                        })
                        break

                    before_pmids = set(llm_results.pmid_map.keys())
                    before_dois = set(llm_results.doi_map.keys())
                    found_before = count_found_studies(llm_results, eval_included_studies)
                    supplement_pmids = set(supplement_results.pmid_map.keys())
                    new_pmids = supplement_pmids - before_pmids
                    dup_pmids = supplement_pmids & before_pmids

                    for pmid, info in supplement_results.pmid_map.items():
                        if pmid not in llm_results.pmid_map:
                            llm_results.pmid_map[pmid] = info
                    for doi, info in supplement_results.doi_map.items():
                        if doi not in llm_results.doi_map:
                            llm_results.doi_map[doi] = info

                    llm_results.result_count += len(new_pmids)

                    found_after = count_found_studies(llm_results, eval_included_studies)
                    delta_found = found_after - found_before
                    total_included = len(eval_included_studies)
                    recall_before = (found_before / total_included * 100) if total_included > 0 else 0.0
                    recall_after = (found_after / total_included * 100) if total_included > 0 else 0.0

                    log.print(
                        f"[dim]  Supplement {passes_run}: {len(supplement_pmids)} total PMIDs, "
                        f"{len(new_pmids)} new, {len(dup_pmids)} already in first pass[/dim]"
                    )
                    log.print(
                        f"[dim]  Supplement recall: {found_before}->{found_after} "
                        f"(+{delta_found}) [{recall_before:.1f}% -> {recall_after:.1f}%][/dim]"
                    )

                    pass_stats.append({
                        "pass": passes_run,
                        "missed_seed_count": len(missed_seed_papers),
                        "seed_unchecked": seed_unchecked,
                        "total_pmids": len(supplement_pmids),
                        "new_pmids": len(new_pmids),
                        "dup_pmids": len(dup_pmids),
                        "new_dois": len(set(supplement_results.doi_map.keys()) - before_dois),
                        "found_before": found_before,
                        "found_after": found_after,
                        "delta_found": delta_found,
                        "recall_before": recall_before,
                        "recall_after": recall_after,
                        "query": supplement_query,
                    })

                    if not new_pmids:
                        log.print("[yellow]  Supplement added no new PMIDs; stopping[/yellow]")
                        break

                if passes_run < max_passes:
                    progress.advance(task_id, (max_passes - passes_run) * 2)

                if pass_stats:
                    supplement_stats = {
                        "passes_run": passes_run,
                        "max_passes": max_passes,
                        "passes": pass_stats,
                    }
                else:
                    supplement_stats = {
                        "passes_run": passes_run,
                        "max_passes": max_passes,
                        "passes": [],
                    }

        tfidf_query = None
        tfidf_stats = None
        if args.tfidf:
            if tfidf_skip_reason == "no_seed_papers":
                log.print("[yellow]TF-IDF enabled but no seed papers available; skipping[/yellow]")
                progress.advance(task_id, 1)
            elif tfidf_skip_reason == "no_terms":
                log.print("[yellow]TF-IDF enabled but no usable terms found; skipping[/yellow]")
                progress.advance(task_id, 1)
            elif not tfidf_terms:
                log.print("[yellow]TF-IDF enabled but no terms available; skipping[/yellow]")
                progress.advance(task_id, 1)
            else:
                max_results = max(1, int(args.tfidf_max_results))
                max_count = min(max_results, 50000)
                attempt = min(len(tfidf_terms), max(1, args.tfidf_top))
                selected_terms: list[str] | None = None
                selected_count: int | None = None
                selected_field: str = "tiab"

                while attempt >= 1:
                    candidate_terms = tfidf_terms[:attempt]
                    last_count: int | None = None
                    for field in ("tiab", "ti"):
                        candidate_query = build_tfidf_query(candidate_terms, field=field)
                        if not candidate_query:
                            continue
                        cached = query_cache.get(candidate_query)
                        if cached:
                            count = cached.result_count
                        else:
                            progress.update(
                                task_id,
                                description=f"TF-IDF query: counting results ({attempt} terms, {field})...",
                                splash=maybe_rotate_splash(),
                            )
                            count = pubmed.count_results(candidate_query)
                        last_count = count

                        if count <= max_count:
                            tfidf_query = candidate_query
                            selected_terms = candidate_terms
                            selected_count = count
                            selected_field = field
                            break
                    if tfidf_query:
                        break
                    if last_count is None:
                        break

                    if attempt == 1:
                        break
                    if last_count > max_count * 5 and attempt > 2:
                        attempt = max(1, attempt // 2)
                    else:
                        attempt -= 1

                if not tfidf_query or not selected_terms:
                    log.print(
                        f"[yellow]TF-IDF query too broad (>{max_count:,} results); skipping[/yellow]"
                    )
                    progress.advance(task_id, 1)
                else:
                    if selected_field == "ti":
                        log.print("[dim]  TF-IDF query: fell back to title-only terms[/dim]")
                    tfidf_results = fetch_or_cached(
                        tfidf_query,
                        "TF-IDF query",
                        max_count=max_count,
                        known_count=selected_count,
                    )
                    if tfidf_results:
                        before_pmids = set(llm_results.pmid_map.keys())
                        before_dois = set(llm_results.doi_map.keys())
                        tfidf_pmids = set(tfidf_results.pmid_map.keys())
                        new_pmids = tfidf_pmids - before_pmids
                        dup_pmids = tfidf_pmids & before_pmids

                        for pmid, info in tfidf_results.pmid_map.items():
                            if pmid not in llm_results.pmid_map:
                                llm_results.pmid_map[pmid] = info
                        for doi, info in tfidf_results.doi_map.items():
                            if doi not in llm_results.doi_map:
                                llm_results.doi_map[doi] = info

                        llm_results.result_count += len(new_pmids)
                        log.print(
                            f"[dim]  TF-IDF query: {len(tfidf_pmids)} total PMIDs, "
                            f"{len(new_pmids)} new, {len(dup_pmids)} already in first pass[/dim]"
                        )

                        tfidf_stats = {
                            "docs_used": (tfidf_term_stats or {}).get("docs_used", 0),
                            "docs_skipped": (tfidf_term_stats or {}).get("docs_skipped", 0),
                            "terms_total": len(tfidf_terms),
                            "terms_used": len(selected_terms),
                            "terms": selected_terms,
                            "field": selected_field,
                            "max_results": max_count,
                            "result_count": selected_count or len(tfidf_pmids),
                            "total_pmids": len(tfidf_pmids),
                            "new_pmids": len(new_pmids),
                            "dup_pmids": len(dup_pmids),
                            "new_dois": len(set(tfidf_results.doi_map.keys()) - before_dois),
                        }

        # Augment with citation searching if enabled
        citation_stats = None
        if args.citations and args.seeds > 0 and seed_papers:
            from src.cache.citation_cache import CitationCache
            from src.citation.openalex import OpenAlexClient as OAClient

            citation_cache = CitationCache(config.cache_dir)
            oa_client = OAClient(
                email=config.openalex_email or config.entrez_email,
                api_key=config.openalex_api_key,
            )

            seed_pmids = [p["pmid"] for p in seed_papers if p.get("pmid")]
            query_pmid_count = len(llm_results.pmid_map)
            citation_pmids: set[str] = set()
            depth = max(1, int(getattr(args, "citation_depth", 1)))
            direction = getattr(args, "citation_direction", "both")
            max_frontier = int(getattr(args, "citation_max_frontier", 0))
            seed_missing_pmid: list[str] = []
            seed_not_found_openalex: list[str] = []

            if depth == 1:
                # Simple path: use get_citations which returns from cache immediately
                for sp in seed_papers:
                    sp_pmid = sp.get("pmid")
                    if not sp_pmid:
                        seed_missing_pmid.append(sp.get("title") or "unknown title")
                        continue
                    progress.update(task_id, description=f"Citations for PMID {sp_pmid}...", splash=maybe_rotate_splash())
                    cr = oa_client.get_citations(
                        sp_pmid,
                        cache=citation_cache,
                        max_forward=2000,
                    )
                    if not cr.forward_pmids and not cr.backward_pmids:
                        seed_not_found_openalex.append(sp_pmid)
                    citation_pmids |= cr.all_pmids
                    log.print(
                        f"[dim]  PMID {sp_pmid}: {len(cr.forward_pmids)} forward, "
                        f"{len(cr.backward_pmids)} backward[/dim]"
                    )
            else:
                # Depth > 1: need work IDs for frontier expansion
                frontier_ids: set[str] = set()
                visited_ids: set[str] = set()
                for sp in seed_papers:
                    sp_pmid = sp.get("pmid")
                    if not sp_pmid:
                        seed_missing_pmid.append(sp.get("title") or "unknown title")
                        continue
                    progress.update(task_id, description=f"Citations for PMID {sp_pmid}...", splash=maybe_rotate_splash())
                    cr, work_ids, found = oa_client.get_citations_with_work_ids(
                        sp_pmid,
                        cache=citation_cache,
                        direction=direction,
                    )
                    if not found:
                        seed_not_found_openalex.append(sp_pmid)
                    citation_pmids |= cr.all_pmids
                    for wid in work_ids:
                        if wid:
                            frontier_ids.add(wid)
                            visited_ids.add(wid)
                    log.print(
                        f"[dim]  PMID {sp_pmid}: {len(cr.forward_pmids)} forward, "
                        f"{len(cr.backward_pmids)} backward[/dim]"
                    )

                for level in range(2, depth + 1):
                    if not frontier_ids:
                        break
                    progress.update(task_id, description=f"Citations depth {level}...", splash=maybe_rotate_splash())
                    next_frontier: set[str] = set()
                    frontier_list = sorted(frontier_ids)
                    if max_frontier > 0 and len(frontier_list) > max_frontier:
                        frontier_list = frontier_list[:max_frontier]
                        log.print(
                            f"[dim]  Depth {level}: capped frontier to {len(frontier_list)} works[/dim]"
                        )
                    for oa_id in frontier_list:
                        pmids, work_ids = oa_client.get_citations_for_work_id(
                            oa_id,
                            direction=direction,
                        )
                        citation_pmids |= pmids
                        for wid in work_ids:
                            if wid and wid not in visited_ids:
                                visited_ids.add(wid)
                                next_frontier.add(wid)
                    if not next_frontier:
                        break
                    frontier_ids = next_frontier

            if seed_missing_pmid:
                log.print(
                    f"[yellow]  {len(seed_missing_pmid)} seed paper(s) missing PMID; "
                    "skipping for citations[/yellow]"
                )
            if seed_not_found_openalex:
                log.print(
                    f"[yellow]  {len(seed_not_found_openalex)} seed PMID(s) not found in OpenAlex[/yellow]"
                )

            citation_cache.save()

            # Check how many citation PMIDs match included studies
            included_pmids = {s.pmid for s in eval_included_studies if s.pmid}
            query_pmids_set = set(llm_results.pmid_map.keys())
            new_pmids = citation_pmids - query_pmids_set

            if seed_pmids:
                missing_seed_pmids = [p for p in seed_pmids if p not in query_pmids_set]
                if not missing_seed_pmids:
                    log.print("[green]  All seed PMIDs were captured in the first-pass query[/green]")
                else:
                    log.print(
                        f"[yellow]  {len(missing_seed_pmids)} seed PMID(s) not captured in the first-pass query[/yellow]"
                    )

            # Included studies found via citations
            citation_included_all = citation_pmids & included_pmids
            citation_already_in_query = citation_included_all & query_pmids_set
            citation_hits = citation_included_all - query_pmids_set  # truly new

            # Add citation PMIDs to the search results
            citation_overlap = citation_pmids & query_pmids_set
            log.print(
                f"[dim]  Citation pass (depth {depth}) total {len(citation_pmids)} PMIDs: "
                f"{len(new_pmids)} new, {len(citation_overlap)} already in query[/dim]"
            )
            citation_stats = {
                "total": len(citation_pmids),
                "new": len(new_pmids),
                "hits": len(citation_hits),
                "hits_already_in_query": len(citation_already_in_query),
                "hits_total": len(citation_included_all),
                "query_count": query_pmid_count,
                "seed_total": len(seed_papers),
                "seed_with_pmid": len(seed_pmids),
                "seed_missing_pmid": len(seed_missing_pmid),
                "seed_not_found_openalex": len(seed_not_found_openalex),
                "depth": depth,
                "direction": direction,
                "max_frontier": max_frontier,
            }

            if new_pmids:
                for pmid in new_pmids:
                    llm_results.pmid_map[pmid] = {"pmid": pmid, "title": "(citation)"}
                llm_results.result_count += len(new_pmids)
                log.print(
                    f"[dim]  Citations added {len(new_pmids)} new PMIDs "
                    f"({query_pmid_count} query + {len(new_pmids)} citations "
                    f"= {len(llm_results.pmid_map)} total)[/dim]"
                )
                # Skip DOI enrichment for citation PMIDs — included studies with DOIs
                # also have PMIDs, so PMID matching is sufficient and avoids extra API calls.
                if citation_included_all:
                    parts = []
                    parts.append(f"{len(citation_included_all)} included studies in citations")
                    if citation_hits:
                        parts.append(f"{len(citation_hits)} new (not in query)")
                    if citation_already_in_query:
                        parts.append(f"{len(citation_already_in_query)} already in query")
                    log.print(f"[green]  {', '.join(parts)}[/green]")
                else:
                    log.print("[dim]  No included studies found via citations[/dim]")
            else:
                log.print("[dim]  No new PMIDs from citations[/dim]")

            # Skip DOI-only citation resolution — included studies with DOIs also have PMIDs,
            # so this step adds no recall value and is very slow (hundreds of API calls).

        # Augment with PubMed "Similar Articles" if enabled
        similar_stats = None
        if args.similar > 0 and seed_papers:
            seed_pmids = [p["pmid"] for p in seed_papers if p.get("pmid")]
            if seed_pmids:
                found_before = count_found_studies(llm_results, eval_included_studies)
                total_included = len(eval_included_studies)
                progress.update(task_id, description="Fetching similar articles...", splash=maybe_rotate_splash())
                similar_map = fetch_similar_pmids(
                    seed_pmids,
                    email=config.entrez_email,
                    api_key=config.entrez_api_key,
                    rate_delay=rate_delay,
                    per_seed=args.similar,
                )
                step("Fetched similar articles")
                similar_pmids = set()
                for pmids in similar_map.values():
                    similar_pmids.update(pmids)

                before_pmids = set(llm_results.pmid_map.keys())
                new_pmids = similar_pmids - before_pmids
                dup_pmids = similar_pmids & before_pmids

                for pmid in new_pmids:
                    llm_results.pmid_map[pmid] = {"pmid": pmid, "title": "(similar)"}
                llm_results.result_count += len(new_pmids)

                found_after = count_found_studies(llm_results, eval_included_studies)
                delta_found = found_after - found_before
                if total_included > 0:
                    recall_before = found_before / total_included * 100
                    recall_after = found_after / total_included * 100
                else:
                    recall_before = 0.0
                    recall_after = 0.0

                log.print(
                    f"[dim]  Similar articles: {len(similar_pmids)} total PMIDs, "
                    f"{len(new_pmids)} new, {len(dup_pmids)} already in first pass[/dim]"
                )
                log.print(
                    f"[dim]  Similar recall: {found_before}->{found_after} "
                    f"(+{delta_found}) "
                    f"[{recall_before:.1f}% -> {recall_after:.1f}%][/dim]"
                )

                similar_stats = {
                    "seed_with_pmid": len(seed_pmids),
                    "per_seed": args.similar,
                    "total_pmids": len(similar_pmids),
                    "new_pmids": len(new_pmids),
                    "dup_pmids": len(dup_pmids),
                    "found_before": found_before,
                    "found_after": found_after,
                    "delta_found": delta_found,
                    "recall_before": recall_before,
                    "recall_after": recall_after,
                }
            else:
                log.print("[yellow]Similar articles enabled but no seed PMIDs available[/yellow]")

        progress.update(task_id, description="Checking PubMed indexing (LLM)...")
        llm_metrics = calculate_metrics_with_pubmed_check(
            llm_results,
            eval_included_studies,
            entrez_email=config.entrez_email,
            rate_delay=rate_delay,
            index_cache=index_cache,
        )
        step("Checked PubMed indexing (LLM)")

        # Identify missed papers (PubMed-indexed only, enriched with seed paper metadata)
        match_results = match_studies(llm_results, eval_included_studies)
        missed_studies = [mr.study for mr in match_results if not mr.matched]

        # Load seed papers JSON to enrich missed papers with metadata
        seed_lookup: dict[str, dict] = {}
        seed_path = SEED_PAPERS_DIR / f"{study.study_id} - {study.name}.json"
        if not seed_path.exists():
            seed_matches = list(SEED_PAPERS_DIR.glob(f"{study.study_id} - *.json"))
            if seed_matches:
                seed_path = seed_matches[0]
        if seed_path.exists():
            with open(seed_path) as f:
                seed_data = json.load(f)
            for sp in seed_data.get("papers", []):
                if sp.get("pmid"):
                    seed_lookup[sp["pmid"]] = sp
                if sp.get("doi"):
                    seed_lookup[sp["doi"].lower()] = sp

        missed_papers = []
        for ms in missed_studies:
            # Only include PubMed-indexed papers (check via index_cache, populated earlier)
            cached_status = index_cache.get(doi=ms.doi, pmid=ms.pmid)
            if cached_status is False:
                continue
            # If not cached at all and no PMID, skip (likely not in PubMed)
            if cached_status is None and not ms.pmid:
                continue
            # Try to enrich from seed papers cache
            enriched = (seed_lookup.get(ms.pmid) if ms.pmid else None) or (seed_lookup.get(ms.doi) if ms.doi else None)
            if enriched:
                missed_papers.append({
                    "title": enriched.get("title") or ms.title,
                    "doi": enriched.get("doi") or ms.doi,
                    "pmid": enriched.get("pmid") or ms.pmid,
                    "abstract": enriched.get("abstract"),
                    "mesh_terms": enriched.get("mesh_terms"),
                    "keywords": enriched.get("keywords"),
                })
            else:
                missed_papers.append({
                    "title": ms.title,
                    "doi": ms.doi,
                    "pmid": ms.pmid,
                })

        # Evaluate human strategy (default, skip with --no-human)
        human_metrics = None
        human_query = None
        if include_human:
            from src.cache.strategy_cache import StrategyCache

            strategy_cache = StrategyCache(config.cache_dir)
            cached = strategy_cache.get(study.search_strategy_docx)

            if cached:
                log.print("[dim]Using cached human strategy[/dim]")
                human_query = cached.query
                step("Human strategy: cached")
            else:
                from src.llm.strategy_extractor import StrategyExtractor

                extractor = StrategyExtractor(client, strategy_cache)
                progress.update(task_id, description="Extracting human strategy...")
                extracted = extractor.extract_strategy(study.search_strategy_docx)
                step("Extracted human strategy")
                if extracted.query:
                    human_query = extracted.query

            if human_query:
                human_results = fetch_or_cached(human_query, "Human query")
                if human_results:
                    progress.update(task_id, description="Checking PubMed indexing (human)...")
                    human_metrics = calculate_metrics_with_pubmed_check(
                        human_results,
                        eval_included_studies,
                        entrez_email=config.entrez_email,
                        rate_delay=rate_delay,
                        index_cache=index_cache,
                    )
                    step("Checked PubMed indexing (human)")
                else:
                    # Advance remaining human steps so bar completes
                    progress.advance(task_id, 2)
            else:
                log.print("[yellow]Failed to extract human strategy[/yellow]")
                # Advance remaining human steps so bar completes
                progress.advance(task_id, 2)
        elif not args.no_human and not study.search_strategy_docx:
            log.print("[yellow]No human search strategy available for this study[/yellow]")


    # Print per-study results (outside progress context so bar is cleared)
    console.print()
    console.print("─" * 70)
    print_study_table(console, llm_metrics, human_metrics)

    return StudyResult(
        study_id=study.study_id,
        study_name=study.name,
        llm_metrics=llm_metrics,
        human_metrics=human_metrics,
        llm_queries=generated_queries,
        merged_query=merged_query,
        executed_query=final_query,
        human_query=human_query,
        query_prompt=query_prompt,
        missed_papers=missed_papers,
        citation_stats=citation_stats,
        supplement_query=supplement_query,
        supplement_stats=supplement_stats,
        similar_stats=similar_stats,
        mesh_entry_stats=mesh_entry_stats,
        tfidf_query=tfidf_query,
        tfidf_stats=tfidf_stats,
    )


def save_results_md(results: list[StudyResult], args: argparse.Namespace) -> Path:
    """Save results to a markdown file in results/."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    study_ids = "_".join(r.study_id for r in results)
    results_dir = Path("results") / study_ids / date_str
    results_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now.strftime("%H%M")
    filename = f"results_{timestamp}.md"
    filepath = results_dir / filename

    lines: list[str] = []
    lines.append(f"# Query Generation Results")
    lines.append(f"")
    lines.append(f"- **Date**: {datetime.now().strftime('%b %d, %Y at %I:%M %p')}")
    lines.append(f"- **Model**: {MODEL}")
    lines.append(f"- **N runs**: {args.n}")
    lines.append(f"- **Double prompt**: {args.double_prompt}")
    lines.append(f"- **Seed papers**: {args.seeds}")
    lines.append(f"- **TF-IDF terms**: {args.tfidf}")
    if args.tfidf:
        lines.append(f"- **TF-IDF top terms**: {args.tfidf_top}")
        lines.append(f"- **TF-IDF max results**: {args.tfidf_max_results}")
    lines.append(f"- **Citations**: {args.citations}")
    if args.citations:
        lines.append(f"- **Citation depth**: {args.citation_depth}")
        lines.append(f"- **Citation direction**: {args.citation_direction}")
        lines.append(
            f"- **Citation max frontier**: {args.citation_max_frontier or 'none'}"
        )
    lines.append(f"- **Two-pass supplement**: {args.two_pass}")
    if args.two_pass:
        lines.append(f"- **Two-pass max**: {args.two_pass_max}")
    lines.append(f"- **MeSH entry-term expansion**: {args.mesh_entry_terms}")
    if args.mesh_entry_terms:
        lines.append(f"- **MeSH entry-term max**: {args.mesh_entry_max}")
    lines.append(f"- **Similar articles per seed**: {args.similar}")
    lines.append(f"- **Studies**: {', '.join(r.study_id for r in results)}")
    lines.append(f"")

    for r in results:
        m = r.llm_metrics
        h = r.human_metrics

        lines.append(f"## Study {r.study_id} - {r.study_name}")
        lines.append(f"")
        lines.append(f"| Metric | Generated | Human |")
        lines.append(f"|--------|-----------|-------|")
        lines.append(f"| Search results | {m.total_results} | {h.total_results if h else '—'} |")
        lines.append(f"| Included studies | {m.total_included} | {h.total_included if h else '—'} |")
        lines.append(f"| Not in PubMed | {m.not_in_pubmed} | {h.not_in_pubmed if h else '—'} |")
        lines.append(f"| PubMed-indexed | {m.pubmed_indexed_count} | {h.pubmed_indexed_count if h else '—'} |")
        lines.append(
            f"| Captured | {m.found}/{m.pubmed_indexed_count} | {h.found}/{h.pubmed_indexed_count} |" if h else f"| Captured | {m.found}/{m.pubmed_indexed_count} | — |")
        lines.append(f"| Missed (in PubMed) | {m.missed_pubmed_indexed} | {h.missed_pubmed_indexed if h else '—'} |")
        lines.append(
            f"| Recall (overall) | {m.recall_overall * 100:.1f}% ({m.found}/{m.total_included}) | {h.recall_overall * 100:.1f}% ({h.found}/{h.total_included}) |" if h else f"| Recall (overall) | {m.recall_overall * 100:.1f}% ({m.found}/{m.total_included}) | — |")
        lines.append(
            f"| Recall (PubMed only) | {m.recall_pubmed_only * 100:.1f}% ({m.found}/{m.pubmed_indexed_count}) | {h.recall_pubmed_only * 100:.1f}% ({h.found}/{h.pubmed_indexed_count}) |" if h else f"| Recall (PubMed only) | {m.recall_pubmed_only * 100:.1f}% ({m.found}/{m.pubmed_indexed_count}) | — |")
        lines.append(
            f"| Precision | {m.precision * 100:.2f}% ({m.found}/{m.total_results}) | {h.precision * 100:.2f}% ({h.found}/{h.total_results}) |" if h else f"| Precision | {m.precision * 100:.2f}% ({m.found}/{m.total_results}) | — |")
        nnr_str = f"{m.nnr:.1f}" if m.nnr != float("inf") else "—"
        h_nnr_str = f"{h.nnr:.1f}" if h and h.nnr != float("inf") else "—"
        lines.append(f"| NNR | {nnr_str} | {h_nnr_str} |")
        if r.citation_stats:
            cs = r.citation_stats
            lines.append(
                f"| **Citations** | depth {cs.get('depth', 1)}, {cs.get('direction', 'both')}, "
                f"cap {cs.get('max_frontier', 0) or 'none'} | — |"
            )
            lines.append(f"| **Citation PMIDs** | {cs['total']} total, {cs['new']} new | — |")
            lines.append(
                f"| **Citation included** | {cs['hits_total']} found ({cs['hits']} new, "
                f"{cs['hits_already_in_query']} already in query) | — |"
            )
            lines.append(
                f"| **Seed papers** | {cs.get('seed_with_pmid', 0)}/{cs.get('seed_total', 0)} with PMID, "
                f"{cs.get('seed_missing_pmid', 0)} missing PMID, "
                f"{cs.get('seed_not_found_openalex', 0)} not in OpenAlex | — |"
            )
        lines.append(f"")
        if r.mesh_entry_stats:
            ms = r.mesh_entry_stats
            lines.append("**MeSH entry-term expansion**")
            lines.append(
                f"- Added {ms.get('entry_terms_added', 0)} terms across "
                f"{ms.get('mesh_terms_expanded', 0)}/{ms.get('mesh_terms_found', 0)} MeSH headings"
            )
            lines.append(f"- Headings detected: {len(ms.get('mesh_terms_detected', []))}")
            if ms.get("mesh_year"):
                lines.append(f"- MeSH year: {ms.get('mesh_year')}")
            if ms.get("mesh_terms_samples"):
                samples = ", ".join(f"{t} (+{n})" for t, n in ms["mesh_terms_samples"])
                lines.append(f"- Samples: {samples}")
            lines.append(f"")
        if r.supplement_stats:
            ss = r.supplement_stats
            lines.append("**Supplement pass**")
            lines.append(
                f"- Passes: {ss.get('passes_run', 0)} / {ss.get('max_passes', 0)}"
            )
            for ps in ss.get("passes", []):
                lines.append(
                    f"- Pass {ps.get('pass', 0)} missed seeds: {ps.get('missed_seed_count', 0)} "
                    f"(unchecked: {ps.get('seed_unchecked', 0)})"
                )
                lines.append(
                    f"- Pass {ps.get('pass', 0)} results: {ps.get('total_pmids', 0)} total PMIDs, "
                    f"{ps.get('new_pmids', 0)} new, {ps.get('dup_pmids', 0)} already in first pass"
                )
                if "new_dois" in ps:
                    lines.append(f"- Pass {ps.get('pass', 0)} DOIs added: {ps.get('new_dois', 0)}")
                if "found_before" in ps:
                    lines.append(
                        f"- Pass {ps.get('pass', 0)} recall impact: {ps.get('found_before', 0)} -> {ps.get('found_after', 0)} "
                        f"(+{ps.get('delta_found', 0)}), "
                        f"{ps.get('recall_before', 0.0):.1f}% -> {ps.get('recall_after', 0.0):.1f}%"
                    )
                if ps.get("query"):
                    lines.append("```")
                    lines.append(ps["query"])
                    lines.append("```")
            lines.append(f"")
        if r.tfidf_stats:
            ts = r.tfidf_stats
            lines.append("**TF-IDF term mining**")
            lines.append(
                f"- Docs used: {ts.get('docs_used', 0)} "
                f"(skipped {ts.get('docs_skipped', 0)})"
            )
            lines.append(
                f"- Terms used: {ts.get('terms_used', 0)} / {ts.get('terms_total', 0)}"
            )
            lines.append(f"- Field: {ts.get('field', 'tiab')}")
            lines.append(
                f"- TF-IDF results: {ts.get('total_pmids', 0)} total PMIDs, "
                f"{ts.get('new_pmids', 0)} new, {ts.get('dup_pmids', 0)} already in first pass"
            )
            if "new_dois" in ts:
                lines.append(f"- DOIs added: {ts.get('new_dois', 0)}")
            if ts.get("terms"):
                lines.append(f"- Terms: {', '.join(ts['terms'])}")
            lines.append(f"")
        if r.similar_stats:
            ss = r.similar_stats
            lines.append("**Similar articles**")
            lines.append(
                f"- Seeds with PMID: {ss.get('seed_with_pmid', 0)}"
            )
            lines.append(
                f"- Per-seed cap: {ss.get('per_seed', 0)}"
            )
            lines.append(
                f"- Similar results: {ss.get('total_pmids', 0)} total PMIDs, "
                f"{ss.get('new_pmids', 0)} new, {ss.get('dup_pmids', 0)} already in first pass"
            )
            if "found_before" in ss:
                lines.append(
                    f"- Recall impact: {ss.get('found_before', 0)} -> {ss.get('found_after', 0)} "
                    f"(+{ss.get('delta_found', 0)}), "
                    f"{ss.get('recall_before', 0.0):.1f}% -> {ss.get('recall_after', 0.0):.1f}%"
                )
            lines.append(f"")

    # Summary table if multiple studies
    if len(results) > 1:
        lines.append(f"## Summary")
        lines.append(f"")
        lines.append(
            "| Study | Results | Recall | Recall (PM) | Precision | NNR | H-Recall | H-Recall (PM) | H-Results | H-Precision |"
        )
        lines.append(
            "|-------|---------|--------|-------------|-----------|-----|----------|---------------|-----------|-------------|"
        )

        for r in results:
            m = r.llm_metrics
            h = r.human_metrics
            label = f"{r.study_id} - {r.study_name}"
            recall_str = f"{m.recall_overall * 100:.1f}% ({m.found}/{m.total_included})"
            recall_pm_str = f"{m.recall_pubmed_only * 100:.1f}% ({m.found}/{m.pubmed_indexed_count})"
            precision_str = f"{m.precision * 100:.2f}%"
            nnr_str = f"{m.nnr:.1f}" if m.nnr != float("inf") else "—"
            h_recall_str = f"{h.recall_overall * 100:.1f}% ({h.found}/{h.total_included})" if h else "—"
            h_recall_pm_str = f"{h.recall_pubmed_only * 100:.1f}% ({h.found}/{h.pubmed_indexed_count})" if h else "—"
            h_results_str = str(h.total_results) if h else "—"
            h_precision_str = f"{h.precision * 100:.2f}%" if h else "—"
            lines.append(
                f"| {label} | {m.total_results} | {recall_str} | {recall_pm_str} | {precision_str} | {nnr_str} "
                f"| {h_recall_str} | {h_recall_pm_str} | {h_results_str} | {h_precision_str} |"
            )

        # Averages
        n = len(results)
        avg_recall = sum(r.llm_metrics.recall_overall for r in results) / n * 100
        avg_recall_pm = sum(r.llm_metrics.recall_pubmed_only for r in results) / n * 100
        avg_precision = sum(r.llm_metrics.precision for r in results) / n * 100
        finite_nnrs = [r.llm_metrics.nnr for r in results if r.llm_metrics.nnr != float("inf")]
        avg_nnr = sum(finite_nnrs) / len(finite_nnrs) if finite_nnrs else float("inf")
        avg_nnr_str = f"{avg_nnr:.1f}" if avg_nnr != float("inf") else "—"
        avg_results = sum(r.llm_metrics.total_results for r in results) // n

        human_with = [r for r in results if r.human_metrics is not None]
        if human_with:
            h_n = len(human_with)
            h_avg_recall = sum(r.human_metrics.recall_overall for r in human_with) / h_n * 100
            h_avg_recall_str = f"{h_avg_recall:.1f}%"
            h_avg_recall_pm = sum(r.human_metrics.recall_pubmed_only for r in human_with) / h_n * 100
            h_avg_recall_pm_str = f"{h_avg_recall_pm:.1f}%"
            h_avg_results_str = str(sum(r.human_metrics.total_results for r in human_with) // h_n)
            h_avg_precision = sum(r.human_metrics.precision for r in human_with) / h_n * 100
            h_avg_precision_str = f"{h_avg_precision:.2f}%"
        else:
            h_avg_recall_str = "—"
            h_avg_recall_pm_str = "—"
            h_avg_results_str = "—"
            h_avg_precision_str = "—"

        lines.append(
            f"| **AVG** | **{avg_results}** | **{avg_recall:.1f}%** | **{avg_recall_pm:.1f}%** "
            f"| **{avg_precision:.2f}%** | **{avg_nnr_str}** | **{h_avg_recall_str}** "
            f"| **{h_avg_recall_pm_str}** | **{h_avg_results_str}** | **{h_avg_precision_str}** |"
        )
        lines.append(f"")

    lines.append(f"## Queries")
    lines.append(f"")
    for r in results:
        lines.append(f"### Study {r.study_id} - {r.study_name}")
        lines.append(f"")
        if r.llm_queries:
            for i, q in enumerate(r.llm_queries):
                label = f"LLM Query" if len(r.llm_queries) == 1 else f"LLM Query {i + 1}"
                lines.append(f"**{label}:**")
                lines.append(f"```")
                lines.append(q)
                lines.append(f"```")
                lines.append(f"")
        if r.merged_query:
            lines.append(f"**Merged Query (OR union):**")
            lines.append(f"```")
            lines.append(r.merged_query)
            lines.append(f"```")
            lines.append(f"")
        if r.executed_query:
            lines.append(f"**Executed Query:**")
            lines.append(f"```")
            lines.append(r.executed_query)
            lines.append(f"```")
            lines.append(f"")
        if r.tfidf_query:
            lines.append(f"**TF-IDF Query:**")
            lines.append(f"```")
            lines.append(r.tfidf_query)
            lines.append(f"```")
            lines.append(f"")
        if r.human_query:
            lines.append(f"**Human Query:**")
            lines.append(f"```")
            lines.append(r.human_query)
            lines.append(f"```")
            lines.append(f"")

    if args.show_missed:
        lines.append(f"## Missed Papers (PubMed-indexed only)")
        lines.append(f"")
        for r in results:
            if r.missed_papers:
                lines.append(f"### Study {r.study_id} - {r.study_name}")
                lines.append(f"")
                for i, p in enumerate(r.missed_papers, 1):
                    title = p.get("title") or "—"
                    pmid = p.get("pmid") or "—"
                    doi = p.get("doi") or "—"
                    lines.append(f"**{i}. {title}**")
                    lines.append(f"- PMID: {pmid} | DOI: {doi}")
                    if p.get("mesh_terms"):
                        lines.append(f"- MeSH: {', '.join(p['mesh_terms'])}")
                    if p.get("keywords"):
                        lines.append(f"- Keywords: {', '.join(p['keywords'])}")
                    if p.get("abstract"):
                        abstract = p["abstract"]
                        if len(abstract) > 500:
                            abstract = abstract[:500] + "..."
                        lines.append(f"- Abstract: {abstract}")
                    lines.append(f"")
            elif r.missed_papers is not None:
                lines.append(f"### Study {r.study_id} - {r.study_name}")
                lines.append(f"")
                lines.append(f"No PubMed-indexed papers were missed.")
                lines.append(f"")

    if args.save_prompt:
        lines.append(f"## Prompts")
        lines.append(f"")
        for r in results:
            if r.query_prompt:
                lines.append(f"### Study {r.study_id} - {r.study_name}")
                lines.append(f"")
                lines.append(f"```")
                lines.append(r.query_prompt)
                lines.append(f"```")
                lines.append(f"")

    filepath.write_text("\n".join(lines))
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Generate a PubMed query from a PROSPERO PDF and evaluate it."
    )
    parser.add_argument("studies", type=str, nargs="+", help="Study ID(s) (e.g., 34 or 34 35 36)")
    parser.add_argument(
        "--no-human",
        action="store_true",
        help="Skip human strategy comparison",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract the systematic review plan from the PROSPERO PDF (no query generation)",
    )
    parser.add_argument(
        "-n",
        type=int,
        default=1,
        help="Run query generation N times and merge PubMed results (union of PMIDs)",
    )
    parser.add_argument(
        "--double-prompt",
        action="store_true",
        help="Repeat the query generation prompt twice in a single message for emphasis",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=0,
        help="Number of random seed papers to include in the prompt (0 = disabled)",
    )
    parser.add_argument(
        "--seed-fields",
        type=str,
        default="tamk",
        help="Which seed paper fields to include: t=title, a=abstract, m=MeSH, k=keywords (default: tamk = all)",
    )
    parser.add_argument(
        "--tfidf",
        action="store_true",
        help="Add a TF-IDF term-mined supplemental query from seed papers (requires --seeds)",
    )
    parser.add_argument(
        "--tfidf-top",
        type=int,
        default=8,
        help="Number of TF-IDF terms to include (default: 8)",
    )
    parser.add_argument(
        "--tfidf-max-results",
        type=int,
        default=20000,
        help="Maximum PubMed results allowed for TF-IDF supplemental query (default: 20000)",
    )
    parser.add_argument(
        "--save-prompt",
        action="store_true",
        help="Include the full LLM prompt in the results markdown file",
    )
    parser.add_argument(
        "--show-missed",
        action="store_true",
        help="Include a list of missed (not captured) papers in the results file",
    )
    parser.add_argument(
        "--citations",
        action="store_true",
        help="Augment query results with forward/backward citations of seed papers via OpenAlex (requires --seeds)",
    )
    parser.add_argument(
        "--two-pass",
        action="store_true",
        help="Generate a supplementary query for missed seed papers and merge results",
    )
    parser.add_argument(
        "--two-pass-max",
        type=int,
        default=3,
        help="Maximum number of supplementary passes to run (default: 3)",
    )
    parser.add_argument(
        "--mesh-entry-terms",
        action="store_true",
        help="Expand MeSH terms with entry-term free-text variants",
    )
    parser.add_argument(
        "--mesh-entry-max",
        type=int,
        default=6,
        help="Maximum number of entry terms per MeSH heading (default: 6)",
    )
    parser.add_argument(
        "--similar",
        type=int,
        default=0,
        help="Fetch up to N similar articles per seed paper and merge results (0 = disabled)",
    )
    parser.add_argument(
        "--citation-depth",
        type=int,
        default=1,
        help="Citation expansion depth (1 = direct citations only)",
    )
    parser.add_argument(
        "--citation-direction",
        type=str,
        choices=["both", "forward", "backward"],
        default="both",
        help="Citation direction to follow (default: both)",
    )
    parser.add_argument(
        "--citation-max-frontier",
        type=int,
        default=0,
        help="Cap number of works expanded at each depth (0 = no cap)",
    )
    args = parser.parse_args()

    config = PipelineConfig.from_env()
    console = Console()

    # Shared resources
    finder = StudyFinder(config.data_dir)
    client = OpenAIClient(api_key=config.openai_api_key, model=MODEL)
    pubmed = PubMedExecutor(
        email=config.entrez_email,
        api_key=config.entrez_api_key,
        batch_size=config.pubmed_batch_size,
    )
    index_cache = PubMedIndexCache(config.cache_dir)
    query_cache = QueryResultsCache(config.cache_dir)

    # Run each study
    results: list[StudyResult] = []
    for study_id in args.studies:
        result = run_study(
            study_id_arg=study_id,
            args=args,
            config=config,
            finder=finder,
            client=client,
            pubmed=pubmed,
            index_cache=index_cache,
            query_cache=query_cache,
            console=console,
        )
        if result:
            results.append(result)

    # Print summary table if multiple studies were run
    if len(results) > 1:
        console.print()
        console.print("━" * 70)
        console.print("[bold]Summary across all studies[/bold]")
        console.print()

        llm_summary = aggregate_metrics([r.llm_metrics for r in results])
        llm_mean = mean_metrics([r.llm_metrics for r in results])

        human_metrics_list = [r.human_metrics for r in results if r.human_metrics is not None]
        human_summary = None
        human_mean = None
        if len(human_metrics_list) == len(results):
            human_summary = aggregate_metrics(human_metrics_list)
            human_mean = mean_metrics(human_metrics_list)
        elif human_metrics_list:
            console.print(
                f"[dim]Human summary omitted: only {len(human_metrics_list)}/{len(results)} "
                f"studies have human strategies.[/dim]"
            )

        print_study_table(
            console,
            llm_summary,
            human_summary,
            title="Pooled totals (weighted)",
        )
        console.print()
        print_study_table(
            console,
            llm_mean,
            human_mean,
            allow_float_counts=True,
            title="Simple mean across studies",
        )

    # Save results to markdown
    if results:
        md_path = save_results_md(results, args)
        console.print(f"[dim]Results saved to {md_path}[/dim]")


if __name__ == "__main__":
    main()
