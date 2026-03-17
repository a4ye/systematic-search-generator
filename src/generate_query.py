"""Generate a PubMed systematic review query from a PROSPERO PDF."""

import argparse
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

from Bio import Entrez, Medline

from .cache.query_results_cache import QueryResultsCache
from .llm.openai_client import OpenAIClient
from .mesh import MeshDB
from .pipeline.config import PipelineConfig
from .pubmed.search_executor import PubMedExecutor, PubMedSearchResults

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


# Mapping from single-letter codes to seed paper fields
SEED_FIELD_CODES = {
    "t": "title",
    "a": "abstract",
    "m": "mesh_terms",
    "k": "keywords",
}


def fetch_seed_papers_by_pmid(
    pmids: list[str],
    email: str,
    api_key: str | None,
    rate_delay: float,
    batch_size: int = 200,
) -> list[dict]:
    """Fetch seed paper metadata from PubMed by PMID."""
    if not pmids:
        return []
    Entrez.email = email
    if api_key:
        Entrez.api_key = api_key

    papers = []
    for start in range(0, len(pmids), batch_size):
        batch = pmids[start:start + batch_size]
        time.sleep(rate_delay)
        handle = Entrez.efetch(db="pubmed", id=",".join(batch), rettype="medline", retmode="text")
        try:
            records = list(Medline.parse(handle))
        finally:
            handle.close()
        for rec in records:
            pmid = rec.get("PMID")
            title = rec.get("TI", "")
            abstract = rec.get("AB", "")
            mesh_terms = rec.get("MH", [])
            keywords = rec.get("OT", [])
            dois = []
            for aid in rec.get("AID", []):
                if "[doi]" in aid:
                    dois.append(aid.replace("[doi]", "").strip())
            papers.append({
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "mesh_terms": mesh_terms,
                "keywords": keywords,
                "doi": dois[0] if dois else None,
            })
    return papers


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
            doi_norm = re.sub(r"^https?://doi\.org/", "", str(doi), flags=re.IGNORECASE)
            doi_norm = re.sub(r"/{2,}", "/", doi_norm.strip().rstrip(".")).lower()
            if search_results.match_by_doi(doi_norm):
                matched = True
        if not matched and pmid:
            pmid_str = str(pmid).strip()
            if search_results.match_by_pmid(pmid_str):
                matched = True
        if not matched:
            missed.append(sp)
    return missed, unchecked


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


def build_tfidf_query(terms: list[str], field: str = "tiab", joiner: str = "OR") -> str:
    if field == "ti":
        formatter = _format_ti
    else:
        formatter = _format_tiab
    formatted = [formatter(t) for t in terms if formatter(t)]
    if not formatted:
        return ""
    joiner_norm = joiner.strip().upper() if joiner else "OR"
    if joiner_norm not in ("OR", "AND"):
        joiner_norm = "OR"
    return "(" + f" {joiner_norm} ".join(formatted) + ")"


# ── Query parsing utilities ─────────────────────────────────────────────────


def extract_query_from_response(text: str) -> str:
    """Extract the PubMed query from an LLM response."""
    text = re.sub(r"```(?:\w+)?\n?", "", text).strip()

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("(") and "[" in line:
            return line

    candidates = []
    for line in text.splitlines():
        line = line.strip()
        if " AND " in line or " OR " in line:
            candidates.append(line)

    if candidates:
        return max(candidates, key=len)

    return text.strip()


def _strip_outer_parens(text: str) -> str:
    s = text.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        closed_at_end = False
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    closed_at_end = (i == len(s) - 1)
                    break
        if depth != 0 or not closed_at_end:
            break
        s = s[1:-1].strip()
    return s


def _split_top_level(query: str, operator: str) -> list[str]:
    token = f" {operator.strip().upper()} "
    if not token.strip():
        return [query.strip()]
    parts: list[str] = []
    depth = 0
    in_quotes = False
    start = 0
    i = 0
    while i < len(query):
        ch = query[i]
        if ch == "\"":
            in_quotes = not in_quotes
            i += 1
            continue
        if not in_quotes:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                if query[i:i + len(token)].upper() == token:
                    parts.append(query[start:i].strip())
                    i += len(token)
                    start = i
                    continue
        i += 1
    parts.append(query[start:].strip())
    return [p for p in parts if p]


def _apply_field_restrictions(query: str, mode: str) -> str:
    mode_norm = (mode or "none").lower()
    if mode_norm in ("none", "off", "false", "0"):
        return query
    tightened = query
    if "ti" in mode_norm:
        tightened = re.sub(r"\[tiab\]", "[ti]", tightened, flags=re.IGNORECASE)
    if "majr" in mode_norm:
        tightened = re.sub(r"\[mesh\]", "[Majr]", tightened, flags=re.IGNORECASE)
    return tightened


def build_block_drop_queries(query: str, field_mode: str = "ti") -> list[str]:
    if not query:
        return []
    top_or_parts = _split_top_level(query, "OR")
    candidates: list[str] = []
    for part in top_or_parts:
        part_core = _strip_outer_parens(part)
        and_blocks = _split_top_level(part_core, "AND")
        if len(and_blocks) <= 1:
            continue
        for drop_idx in range(len(and_blocks)):
            remaining = [b for i, b in enumerate(and_blocks) if i != drop_idx]
            if not remaining:
                continue
            candidate = " AND ".join(remaining)
            candidate = candidate.strip()
            if len(remaining) > 1:
                candidate = f"({candidate})"
            candidate = _apply_field_restrictions(candidate, field_mode)
            candidates.append(candidate)
    unique: list[str] = []
    seen = set()
    for c in candidates:
        if not c:
            continue
        key = c.strip()
        if key and key not in seen and key != query.strip():
            seen.add(key)
            unique.append(c)
    return unique


_TIGHTEN_LEVELS: list[tuple[str, str]] = [
    ("ti", "ti"),
    ("ti+majr", "ti+majr"),
]


def build_block_drop_candidates_raw(query: str) -> list[str]:
    if not query:
        return []
    top_or_parts = _split_top_level(query, "OR")
    candidates: list[str] = []
    for part in top_or_parts:
        part_core = _strip_outer_parens(part)
        and_blocks = _split_top_level(part_core, "AND")
        if len(and_blocks) <= 1:
            continue
        for drop_idx in range(len(and_blocks)):
            remaining = [b for i, b in enumerate(and_blocks) if i != drop_idx]
            if not remaining:
                continue
            candidate = " AND ".join(remaining)
            candidate = candidate.strip()
            if len(remaining) > 1:
                candidate = f"({candidate})"
            candidates.append(candidate)
    unique: list[str] = []
    seen = set()
    for c in candidates:
        if not c:
            continue
        key = c.strip()
        if key and key not in seen and key != query.strip():
            seen.add(key)
            unique.append(c)
    return unique


# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class RunResult:
    """Results from running the query generation pipeline."""
    llm_queries: list[str]
    merged_query: str | None
    executed_query: str
    final_pmid_map: dict[str, dict]
    final_doi_map: dict[str, dict]
    total_result_count: int
    supplement_query: str | None = None
    supplement_stats: dict | None = None
    citation_stats: dict | None = None
    similar_stats: dict | None = None
    similar_augment_stats: dict | None = None
    mesh_entry_stats: dict | None = None
    tfidf_query: str | None = None
    tfidf_stats: dict | None = None
    block_drop_stats: dict | None = None


def _calculate_total_steps(
        n_runs: int,
        two_pass: bool,
        similar: bool,
        similar_augment: bool,
        tfidf: bool,
        block_drop: bool,
        two_pass_max: int,
) -> int:
    total = 1 + n_runs + 1  # extract plan + generate(n) + fetch(1)
    if two_pass:
        total += 2 * max(1, two_pass_max)
    if similar:
        total += 1
    if similar_augment:
        total += 1
    if tfidf:
        total += 1
    if block_drop:
        total += 1
    return total


# ── Main pipeline ────────────────────────────────────────────────────────────


def run_pipeline(
        prospero_pdf: Path,
        seed_papers: list[dict] | None,
        args: argparse.Namespace,
        config: PipelineConfig,
        client: OpenAIClient,
        pubmed: PubMedExecutor,
        query_cache: QueryResultsCache,
        console: Console,
) -> RunResult | None:
    """Run the full query generation pipeline. Returns RunResult or None on failure."""
    rate_delay = 0.1 if config.entrez_api_key else 0.34

    n_runs = args.n
    total_steps = _calculate_total_steps(
        n_runs,
        args.two_pass,
        args.similar > 0,
        args.similar_augment > 0,
        args.tfidf,
        args.block_drop,
        args.two_pass_max,
    )

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=25),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        expand=False,
    )

    with progress:
        task_id = progress.add_task("Extracting plan...", total=total_steps)
        log = progress.console
        progress.refresh()

        def step(description: str) -> None:
            progress.update(task_id, description=description, advance=1)

        # Step 1: Extract plan from PROSPERO PDF
        progress.update(task_id, description=f"Extracting plan with {MODEL}...")
        extract_response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=prospero_pdf)
        step("Extracted plan")
        plan_info = extract_response.content
        log.print(
            f"[dim]  Tokens: {extract_response.prompt_tokens} in / {extract_response.completion_tokens} out, "
            f"{extract_response.generation_time:.1f}s[/dim]"
        )

        # Step 2: Build seed section for prompt
        seed_section = ""
        if seed_papers:
            seed_section = "\n\n" + format_seed_papers(seed_papers, fields=args.seed_fields)
            field_names = [SEED_FIELD_CODES[c] for c in args.seed_fields if c in SEED_FIELD_CODES]
            log.print(f"[dim]  Using {len(seed_papers)} seed papers ({', '.join(field_names)})[/dim]")

        # Step 3: Generate query from extracted plan
        query_prompt = QUERY_PROMPT + "\n" + plan_info + seed_section
        if args.double_prompt:
            query_prompt = query_prompt + "\n\n---\n\n" + query_prompt
            log.print("[dim]  (prompt doubled)[/dim]")

        def _generate_one(run_i: int) -> tuple[int, str, int, int, float]:
            resp = client.generate_text(prompt=query_prompt)
            q = extract_query_from_response(resp.content)
            return run_i, q, resp.prompt_tokens, resp.completion_tokens, resp.generation_time

        if n_runs == 1:
            progress.update(task_id, description="Generating query...")
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
                advance_step: bool = True,
        ) -> PubMedSearchResults | None:
            def maybe_step(description: str) -> None:
                if advance_step:
                    step(description)
                else:
                    progress.update(task_id, description=description)

            cached_result = query_cache.get(query)
            if cached_result:
                if cached_result.result_count > max_count:
                    log.print(
                        f"[red]{label} too broad (cached): {cached_result.result_count:,} results "
                        f"(max {max_count:,})[/red]"
                    )
                    maybe_step(f"{label}: too broad")
                    return None
                log.print(f"[dim]{label}: using cached PubMed results[/dim]")
                maybe_step(f"{label}: cached")
                return PubMedSearchResults.from_cached(
                    query=query,
                    pmids=cached_result.pmids,
                    result_count=cached_result.result_count,
                    doi_to_pmid=cached_result.doi_to_pmid,
                )

            if known_count is None:
                progress.update(task_id, description=f"{label}: counting results...")
            result_count = known_count if known_count is not None else pubmed.count_results(query)
            if result_count > max_count:
                log.print(
                    f"[red]{label} too broad: {result_count:,} results (max {max_count:,})[/red]"
                )
                maybe_step(f"{label}: too broad")
                return None

            progress.update(task_id, description=f"{label}: fetching {result_count:,} results...")
            batch_task_id = None

            def _batch_progress(done: int, total: int) -> None:
                nonlocal batch_task_id
                if total <= 0:
                    return
                if batch_task_id is None:
                    batch_task_id = progress.add_task(f"{label}: batches", total=total)
                progress.update(batch_task_id, completed=done)

            search_results = pubmed.execute_query_fast(
                query,
                max_results=config.max_pubmed_results,
                progress_callback=_batch_progress,
            )
            if batch_task_id is not None:
                progress.remove_task(batch_task_id)
            maybe_step(f"{label}: fetched {result_count:,}")

            pmids = list(search_results.pmid_map.keys())
            doi_to_pmid = {doi: info["pmid"] for doi, info in search_results.doi_map.items()}
            query_cache.set(query, pmids, search_results.result_count, doi_to_pmid)

            return search_results

        # Build final query: OR together unique queries if n > 1
        unique_queries = list(dict.fromkeys(generated_queries))
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
                    final_query, mesh_db, max_terms=args.mesh_entry_max,
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
                    seed_papers, max_terms=max(1, args.tfidf_top * 3),
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
        baseline_pmids = set(llm_results.pmid_map.keys())

        # Optional two-pass refinement
        if args.two_pass:
            if not seed_papers:
                log.print("[yellow]Two-pass enabled but no seed papers available; skipping[/yellow]")
                progress.advance(task_id, 2 * max(1, args.two_pass_max))
            else:
                max_passes = max(1, args.two_pass_max)
                pass_stats: list[dict] = []
                passes_run = 0

                while passes_run < max_passes:
                    missed_seed_papers, seed_unchecked = get_missed_seed_papers(seed_papers, llm_results)
                    if not missed_seed_papers:
                        log.print("[green]  Two-pass: all seed papers captured; stopping[/green]")
                        break

                    passes_run += 1
                    log.print(
                        f"[dim]  Two-pass {passes_run}/{max_passes}: {len(missed_seed_papers)} seed "
                        f"paper(s) missed ({seed_unchecked} unchecked)[/dim]"
                    )

                    supplement_seed_section = "\n\n" + format_seed_papers(
                        missed_seed_papers, fields=args.seed_fields,
                    )
                    supplement_prompt = (
                        SUPPLEMENT_PROMPT
                        + "\n\nOriginal query:\n" + final_query
                        + "\n\n" + plan_info + supplement_seed_section
                    )
                    progress.update(task_id, description=f"Generating supplement query {passes_run}...")
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

                    supplement_results = fetch_or_cached(supplement_query, f"Supplement query {passes_run}")
                    if supplement_results is None:
                        log.print("[yellow]Supplement query produced no results; stopping[/yellow]")
                        pass_stats.append({
                            "pass": passes_run,
                            "missed_seed_count": len(missed_seed_papers),
                            "seed_unchecked": seed_unchecked,
                            "total_pmids": 0, "new_pmids": 0, "dup_pmids": 0,
                        })
                        break

                    before_pmids = set(llm_results.pmid_map.keys())
                    before_dois = set(llm_results.doi_map.keys())
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

                    log.print(
                        f"[dim]  Supplement {passes_run}: {len(supplement_pmids)} total PMIDs, "
                        f"{len(new_pmids)} new, {len(dup_pmids)} already in first pass[/dim]"
                    )

                    pass_stats.append({
                        "pass": passes_run,
                        "missed_seed_count": len(missed_seed_papers),
                        "seed_unchecked": seed_unchecked,
                        "total_pmids": len(supplement_pmids),
                        "new_pmids": len(new_pmids),
                        "dup_pmids": len(dup_pmids),
                        "new_dois": len(set(supplement_results.doi_map.keys()) - before_dois),
                        "query": supplement_query,
                    })

                    if not new_pmids:
                        log.print("[yellow]  Supplement added no new PMIDs; stopping[/yellow]")
                        break

                if passes_run < max_passes:
                    progress.advance(task_id, (max_passes - passes_run) * 2)

                supplement_stats = {
                    "passes_run": passes_run,
                    "max_passes": max_passes,
                    "passes": pass_stats,
                }

        block_drop_stats = None
        if args.block_drop:
            raw_candidates = build_block_drop_candidates_raw(final_query)
            block_drop_queries = build_block_drop_queries(final_query, field_mode=args.block_drop_field)
            if not block_drop_queries and not raw_candidates:
                log.print("[yellow]Block-drop enabled but no AND blocks found; skipping[/yellow]")
                progress.advance(task_id, 1)
            else:
                max_results = max(1, int(args.block_drop_max_results))
                before_pmids = set(llm_results.pmid_map.keys())
                before_dois = set(llm_results.doi_map.keys())
                per_query: list[dict] = []
                total_new_pmids = 0
                total_dup_pmids = 0
                total_new_dois = 0
                skipped = 0
                tightened_count = 0

                configured_mode = args.block_drop_field or "ti"
                tighten_levels = list(_TIGHTEN_LEVELS)
                configured_in_list = any(m == configured_mode for _, m in tighten_levels)
                if not configured_in_list:
                    tighten_levels.insert(0, (configured_mode, configured_mode))

                for i, raw_q in enumerate(raw_candidates, 1):
                    label = f"Block-drop query {i}/{len(raw_candidates)}"
                    progress.update(task_id, description=f"{label}: counting results...")

                    result = None
                    used_level = None
                    for level_label, level_mode in tighten_levels:
                        tightened_q = _apply_field_restrictions(raw_q, level_mode)
                        cached_result = query_cache.get(tightened_q)
                        if cached_result:
                            count = cached_result.result_count
                        else:
                            count = pubmed.count_results(tightened_q)

                        if count <= max_results:
                            result = fetch_or_cached(
                                tightened_q, label,
                                max_count=max_results, known_count=count, advance_step=False,
                            )
                            used_level = level_label
                            break
                        else:
                            log.print(
                                f"[dim]  {label} [{level_label}]: {count:,} results "
                                f"(> {max_results:,}), tightening...[/dim]"
                            )

                    if result is None:
                        skipped += 1
                        per_query.append({"query": raw_q, "skipped": True, "reason": "too_broad"})
                        continue

                    if used_level and used_level != configured_mode:
                        tightened_count += 1
                        log.print(
                            f"[dim]  {label}: auto-tightened to [{used_level}] "
                            f"({result.result_count:,} results)[/dim]"
                        )

                    pmids = set(result.pmid_map.keys())
                    new_pmids = pmids - before_pmids
                    dup_pmids = pmids & before_pmids
                    new_dois = set(result.doi_map.keys()) - before_dois

                    for pmid, info in result.pmid_map.items():
                        if pmid not in llm_results.pmid_map:
                            llm_results.pmid_map[pmid] = info
                    for doi, info in result.doi_map.items():
                        if doi not in llm_results.doi_map:
                            llm_results.doi_map[doi] = info

                    llm_results.result_count += len(new_pmids)
                    before_pmids |= new_pmids
                    before_dois |= new_dois
                    total_new_pmids += len(new_pmids)
                    total_dup_pmids += len(dup_pmids)
                    total_new_dois += len(new_dois)

                    per_query.append({
                        "query": result.query if hasattr(result, 'query') else raw_q,
                        "skipped": False,
                        "result_count": result.result_count,
                        "total_pmids": len(pmids),
                        "new_pmids": len(new_pmids),
                        "dup_pmids": len(dup_pmids),
                        "new_dois": len(new_dois),
                        "field_level": used_level,
                    })

                tightened_msg = f", {tightened_count} auto-tightened" if tightened_count else ""
                log.print(
                    f"[dim]  Block-drop: {len(raw_candidates)} queries, "
                    f"{total_new_pmids} new PMIDs, {total_dup_pmids} already in query"
                    f"{tightened_msg}[/dim]"
                )

                block_drop_stats = {
                    "queries_total": len(raw_candidates),
                    "queries_skipped": skipped,
                    "queries_tightened": tightened_count,
                    "max_results": max_results,
                    "field_mode": args.block_drop_field,
                    "total_new_pmids": total_new_pmids,
                    "total_dup_pmids": total_dup_pmids,
                    "total_new_dois": total_new_dois,
                    "queries": per_query,
                }
                step("Block-drop supplements")

        tfidf_query = None
        tfidf_stats = None
        if args.tfidf:
            if tfidf_skip_reason:
                log.print(f"[yellow]TF-IDF skipped: {tfidf_skip_reason}[/yellow]")
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
                selected_joiner: str = "OR"

                while attempt >= 1:
                    candidate_terms = tfidf_terms[:attempt]
                    last_count: int | None = None
                    for field in ("tiab", "ti"):
                        candidate_query = build_tfidf_query(candidate_terms, field=field, joiner="OR")
                        if not candidate_query:
                            continue
                        cached = query_cache.get(candidate_query)
                        if cached:
                            count = cached.result_count
                        else:
                            progress.update(
                                task_id,
                                description=f"TF-IDF query: counting results ({attempt} terms, {field})...",
                            )
                            count = pubmed.count_results(candidate_query)
                        last_count = count
                        if count <= max_count:
                            tfidf_query = candidate_query
                            selected_terms = candidate_terms
                            selected_count = count
                            selected_field = field
                            selected_joiner = "OR"
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
                    strict_terms = tfidf_terms[: min(2, len(tfidf_terms))]
                    strict_query = build_tfidf_query(strict_terms, field="ti", joiner="AND") if strict_terms else ""
                    strict_count: int | None = None
                    if strict_query:
                        cached = query_cache.get(strict_query)
                        if cached:
                            strict_count = cached.result_count
                        else:
                            progress.update(task_id, description="TF-IDF query: tightening with AND (title-only)...")
                            strict_count = pubmed.count_results(strict_query)
                    if strict_query and strict_count is not None and strict_count <= max_count:
                        tfidf_query = strict_query
                        selected_terms = strict_terms
                        selected_count = strict_count
                        selected_field = "ti"
                        selected_joiner = "AND"
                        log.print("[dim]  TF-IDF query: tightened to title-only AND[/dim]")

                if not tfidf_query or not selected_terms:
                    log.print(f"[yellow]TF-IDF query too broad (>{max_count:,} results); skipping[/yellow]")
                    progress.advance(task_id, 1)
                else:
                    if selected_field == "ti" and selected_joiner == "OR":
                        log.print("[dim]  TF-IDF query: fell back to title-only terms[/dim]")
                    tfidf_results = fetch_or_cached(
                        tfidf_query, "TF-IDF query", max_count=max_count, known_count=selected_count,
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
                            "joiner": selected_joiner,
                            "max_results": max_count,
                            "result_count": selected_count or len(tfidf_pmids),
                            "total_pmids": len(tfidf_pmids),
                            "new_pmids": len(new_pmids),
                            "dup_pmids": len(dup_pmids),
                            "new_dois": len(set(tfidf_results.doi_map.keys()) - before_dois),
                        }

        # Augment with citation searching if enabled
        citation_stats = None
        if args.citations and seed_papers:
            from .cache.citation_cache import CitationCache
            from .citation.openalex import OpenAlexClient as OAClient

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
            seed_no_id: list[str] = []
            seed_not_found_openalex: list[str] = []
            doi_resolved_pmids: list[str] = []

            if depth == 1:
                for sp in seed_papers:
                    sp_pmid = sp.get("pmid")
                    sp_doi = sp.get("doi")
                    if not sp_pmid and not sp_doi:
                        seed_no_id.append(sp.get("title") or "unknown title")
                        continue
                    if sp_pmid:
                        progress.update(task_id, description=f"Citations for PMID {sp_pmid}...")
                        cr = oa_client.get_citations(sp_pmid, cache=citation_cache, max_forward=2000)
                        if not cr.forward_pmids and not cr.backward_pmids:
                            seed_not_found_openalex.append(sp_pmid)
                        citation_pmids |= cr.all_pmids
                        log.print(
                            f"[dim]  PMID {sp_pmid}: {len(cr.forward_pmids)} forward, "
                            f"{len(cr.backward_pmids)} backward[/dim]"
                        )
                    else:
                        progress.update(task_id, description=f"Citations for DOI {sp_doi}...")
                        cr, resolved_pmid = oa_client.get_citations_by_doi(
                            sp_doi, cache=citation_cache, max_forward=2000,
                        )
                        if not cr.forward_pmids and not cr.backward_pmids:
                            seed_not_found_openalex.append(f"doi:{sp_doi}")
                        citation_pmids |= cr.all_pmids
                        label = f"DOI {sp_doi}"
                        if resolved_pmid:
                            label += f" (PMID {resolved_pmid})"
                            doi_resolved_pmids.append(resolved_pmid)
                            seed_pmids.append(resolved_pmid)
                        else:
                            seed_missing_pmid.append(sp.get("title") or sp_doi)
                        log.print(
                            f"[dim]  {label}: {len(cr.forward_pmids)} forward, "
                            f"{len(cr.backward_pmids)} backward[/dim]"
                        )
            else:
                frontier_ids: set[str] = set()
                visited_ids: set[str] = set()
                for sp in seed_papers:
                    sp_pmid = sp.get("pmid")
                    sp_doi = sp.get("doi")
                    if not sp_pmid and not sp_doi:
                        seed_no_id.append(sp.get("title") or "unknown title")
                        continue
                    if sp_pmid:
                        progress.update(task_id, description=f"Citations for PMID {sp_pmid}...")
                        cr, work_ids, found = oa_client.get_citations_with_work_ids(
                            sp_pmid, cache=citation_cache, direction=direction,
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
                    else:
                        progress.update(task_id, description=f"Citations for DOI {sp_doi}...")
                        cr, work_ids, found, resolved_pmid = oa_client.get_citations_with_work_ids_by_doi(
                            sp_doi, cache=citation_cache, direction=direction,
                        )
                        if not found:
                            seed_not_found_openalex.append(f"doi:{sp_doi}")
                        citation_pmids |= cr.all_pmids
                        for wid in work_ids:
                            if wid:
                                frontier_ids.add(wid)
                                visited_ids.add(wid)
                        label = f"DOI {sp_doi}"
                        if resolved_pmid:
                            label += f" (PMID {resolved_pmid})"
                            doi_resolved_pmids.append(resolved_pmid)
                            seed_pmids.append(resolved_pmid)
                        else:
                            seed_missing_pmid.append(sp.get("title") or sp_doi)
                        log.print(
                            f"[dim]  {label}: {len(cr.forward_pmids)} forward, "
                            f"{len(cr.backward_pmids)} backward[/dim]"
                        )

                for level in range(2, depth + 1):
                    if not frontier_ids:
                        break
                    progress.update(task_id, description=f"Citations depth {level}...")
                    next_frontier: set[str] = set()
                    frontier_list = sorted(frontier_ids)
                    if max_frontier > 0 and len(frontier_list) > max_frontier:
                        frontier_list = frontier_list[:max_frontier]
                        log.print(f"[dim]  Depth {level}: capped frontier to {len(frontier_list)} works[/dim]")
                    for oa_id in frontier_list:
                        pmids_found, work_ids = oa_client.get_citations_for_work_id(oa_id, direction=direction)
                        citation_pmids |= pmids_found
                        for wid in work_ids:
                            if wid and wid not in visited_ids:
                                visited_ids.add(wid)
                                next_frontier.add(wid)
                    if not next_frontier:
                        break
                    frontier_ids = next_frontier

            if doi_resolved_pmids:
                log.print(
                    f"[green]  {len(doi_resolved_pmids)} DOI-only seed(s) resolved to PMID: "
                    f"{', '.join(doi_resolved_pmids)}[/green]"
                )
            if seed_no_id:
                log.print(f"[yellow]  {len(seed_no_id)} seed paper(s) have no PMID or DOI[/yellow]")
            if seed_missing_pmid:
                log.print(f"[yellow]  {len(seed_missing_pmid)} seed paper(s) could not be resolved to PMID[/yellow]")
            if seed_not_found_openalex:
                log.print(f"[yellow]  {len(seed_not_found_openalex)} seed(s) not found in OpenAlex[/yellow]")

            citation_cache.save()

            query_pmids_set = set(llm_results.pmid_map.keys())
            new_pmids = citation_pmids - query_pmids_set
            citation_overlap = citation_pmids & query_pmids_set

            log.print(
                f"[dim]  Citation pass (depth {depth}) total {len(citation_pmids)} PMIDs: "
                f"{len(new_pmids)} new, {len(citation_overlap)} already in query[/dim]"
            )
            citation_stats = {
                "total": len(citation_pmids),
                "new": len(new_pmids),
                "query_count": query_pmid_count,
                "seed_total": len(seed_papers),
                "seed_with_pmid": len(seed_pmids),
                "seed_doi_resolved": len(doi_resolved_pmids),
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
            else:
                log.print("[dim]  No new PMIDs from citations[/dim]")

        # Augment with PubMed "Similar Articles" if enabled
        similar_stats = None
        if args.similar > 0 and seed_papers:
            seed_pmids = [p["pmid"] for p in seed_papers if p.get("pmid")]
            if not args.citations:
                from .citation.openalex import OpenAlexClient as OAClient
                _oa = OAClient(
                    email=config.openalex_email or config.entrez_email,
                    api_key=config.openalex_api_key,
                )
                for sp in seed_papers:
                    if not sp.get("pmid") and sp.get("doi"):
                        resolved = _oa.resolve_doi_to_pmid(sp["doi"])
                        if resolved:
                            seed_pmids.append(resolved)
                            log.print(f"[dim]  DOI {sp['doi']} resolved to PMID {resolved}[/dim]")
            if seed_pmids:
                progress.update(task_id, description="Fetching similar articles...")
                similar_map = fetch_similar_pmids(
                    seed_pmids, email=config.entrez_email, api_key=config.entrez_api_key,
                    rate_delay=rate_delay, per_seed=args.similar,
                )
                step("Fetched similar articles")
                similar_pmids = set()
                for pmids_list in similar_map.values():
                    similar_pmids.update(pmids_list)

                before_pmids = set(llm_results.pmid_map.keys())
                new_pmids = similar_pmids - before_pmids
                dup_pmids = similar_pmids & before_pmids

                for pmid in new_pmids:
                    llm_results.pmid_map[pmid] = {"pmid": pmid, "title": "(similar)"}
                llm_results.result_count += len(new_pmids)

                log.print(
                    f"[dim]  Similar articles: {len(similar_pmids)} total PMIDs, "
                    f"{len(new_pmids)} new, {len(dup_pmids)} already in first pass[/dim]"
                )
                similar_stats = {
                    "seed_with_pmid": len(seed_pmids),
                    "per_seed": args.similar,
                    "total_pmids": len(similar_pmids),
                    "new_pmids": len(new_pmids),
                    "dup_pmids": len(dup_pmids),
                }
            else:
                log.print("[yellow]Similar articles enabled but no seed PMIDs available[/yellow]")

        # Second-round similar articles on augmentation hits
        similar_augment_stats = None
        if args.similar_augment > 0:
            augmentation_pmids = set(llm_results.pmid_map.keys()) - baseline_pmids
            if augmentation_pmids:
                sample_size = min(len(augmentation_pmids), max(1, args.similar_augment_sample))
                sampled = random.sample(sorted(augmentation_pmids), sample_size)
                log.print(
                    f"[dim]  Similar-augment: sampling {len(sampled)} of "
                    f"{len(augmentation_pmids)} augmentation-hit PMIDs[/dim]"
                )

                progress.update(task_id, description="Fetching similar articles (round 2)...")
                aug_similar_map = fetch_similar_pmids(
                    sampled, email=config.entrez_email, api_key=config.entrez_api_key,
                    rate_delay=rate_delay, per_seed=args.similar_augment,
                )
                step("Fetched similar articles (round 2)")

                aug_similar_pmids = set()
                for pmids_list in aug_similar_map.values():
                    aug_similar_pmids.update(pmids_list)

                before_pmids = set(llm_results.pmid_map.keys())
                new_pmids = aug_similar_pmids - before_pmids
                dup_pmids = aug_similar_pmids & before_pmids

                for pmid in new_pmids:
                    llm_results.pmid_map[pmid] = {"pmid": pmid, "title": "(similar-r2)"}
                llm_results.result_count += len(new_pmids)

                log.print(
                    f"[dim]  Similar-augment: {len(aug_similar_pmids)} total PMIDs, "
                    f"{len(new_pmids)} new, {len(dup_pmids)} already in results[/dim]"
                )
                similar_augment_stats = {
                    "augmentation_pool": len(augmentation_pmids),
                    "sampled": len(sampled),
                    "per_pmid": args.similar_augment,
                    "total_pmids": len(aug_similar_pmids),
                    "new_pmids": len(new_pmids),
                    "dup_pmids": len(dup_pmids),
                }
            else:
                log.print("[dim]  Similar-augment: no augmentation-hit PMIDs to sample[/dim]")

    return RunResult(
        llm_queries=generated_queries,
        merged_query=merged_query,
        executed_query=final_query,
        final_pmid_map=dict(llm_results.pmid_map),
        final_doi_map=dict(llm_results.doi_map),
        total_result_count=llm_results.result_count,
        supplement_query=supplement_query,
        supplement_stats=supplement_stats,
        citation_stats=citation_stats,
        similar_stats=similar_stats,
        similar_augment_stats=similar_augment_stats,
        mesh_entry_stats=mesh_entry_stats,
        tfidf_query=tfidf_query,
        tfidf_stats=tfidf_stats,
        block_drop_stats=block_drop_stats,
    )


# ── Output ───────────────────────────────────────────────────────────────────


def write_markdown_report(result: RunResult, args: argparse.Namespace, output_path: Path) -> None:
    """Write a markdown report with queries and augmentation stats."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Query Generation Report")
    lines.append("")
    lines.append(f"- **Date**: {datetime.now().strftime('%b %d, %Y at %I:%M %p')}")
    lines.append(f"- **Model**: {MODEL}")
    lines.append(f"- **N runs**: {args.n}")
    lines.append(f"- **Double prompt**: {args.double_prompt}")
    if args.seeds:
        lines.append(f"- **Seed PMIDs**: {args.seeds}")
    lines.append(f"- **Seed fields**: {args.seed_fields}")
    lines.append(f"- **TF-IDF**: {args.tfidf}")
    if args.tfidf:
        lines.append(f"  - Top terms: {args.tfidf_top}")
        lines.append(f"  - Max results: {args.tfidf_max_results}")
    lines.append(f"- **Block-drop**: {args.block_drop}")
    if args.block_drop:
        lines.append(f"  - Max results: {args.block_drop_max_results}")
        lines.append(f"  - Field mode: {args.block_drop_field}")
    lines.append(f"- **Citations**: {args.citations}")
    if args.citations:
        lines.append(f"  - Depth: {args.citation_depth}")
        lines.append(f"  - Direction: {args.citation_direction}")
        lines.append(f"  - Max frontier: {args.citation_max_frontier or 'none'}")
    lines.append(f"- **Two-pass**: {args.two_pass}")
    if args.two_pass:
        lines.append(f"  - Max passes: {args.two_pass_max}")
    lines.append(f"- **MeSH entry-term expansion**: {args.mesh_entry_terms}")
    if args.mesh_entry_terms:
        lines.append(f"  - Max terms per heading: {args.mesh_entry_max}")
    lines.append(f"- **Similar articles per seed**: {args.similar}")
    if args.similar_augment > 0:
        lines.append(f"- **Similar-augment per PMID**: {args.similar_augment}")
        lines.append(f"  - Sample size: {args.similar_augment_sample}")
    lines.append("")

    # Result summary
    lines.append("## Result Summary")
    lines.append("")
    lines.append(f"**Total PMIDs**: {result.total_result_count:,}")
    lines.append("")

    # Primary query
    lines.append("## Primary Query")
    lines.append("")
    if result.llm_queries:
        if len(result.llm_queries) == 1:
            lines.append("```")
            lines.append(result.llm_queries[0])
            lines.append("```")
        else:
            for i, q in enumerate(result.llm_queries, 1):
                lines.append(f"**LLM Query {i}:**")
                lines.append("```")
                lines.append(q)
                lines.append("```")
                lines.append("")
            if result.merged_query:
                lines.append("**Merged Query (OR union):**")
                lines.append("```")
                lines.append(result.merged_query)
                lines.append("```")
    lines.append("")

    if result.executed_query != (result.merged_query or (result.llm_queries[0] if result.llm_queries else "")):
        lines.append("**Executed Query (after MeSH expansion):**")
        lines.append("```")
        lines.append(result.executed_query)
        lines.append("```")
        lines.append("")

    # Augmentation details
    has_augmentation = any([
        result.mesh_entry_stats, result.supplement_stats, result.block_drop_stats,
        result.tfidf_stats, result.citation_stats, result.similar_stats, result.similar_augment_stats,
    ])

    if has_augmentation:
        lines.append("## Augmentation")
        lines.append("")

    if result.mesh_entry_stats:
        ms = result.mesh_entry_stats
        lines.append("### MeSH Entry-Term Expansion")
        lines.append("")
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
        lines.append("")

    if result.supplement_stats:
        ss = result.supplement_stats
        lines.append("### Two-Pass Supplement")
        lines.append("")
        lines.append(f"- Passes run: {ss.get('passes_run', 0)} / {ss.get('max_passes', 0)}")
        for ps in ss.get("passes", []):
            lines.append(
                f"- Pass {ps.get('pass', 0)}: missed seeds={ps.get('missed_seed_count', 0)}, "
                f"total PMIDs={ps.get('total_pmids', 0)}, new={ps.get('new_pmids', 0)}, "
                f"duplicates={ps.get('dup_pmids', 0)}"
            )
            if ps.get("query"):
                lines.append("  ```")
                lines.append(f"  {ps['query']}")
                lines.append("  ```")
        lines.append("")

    if result.block_drop_stats:
        bs = result.block_drop_stats
        lines.append("### Block-Drop Supplement")
        lines.append("")
        lines.append(
            f"- Queries: {bs.get('queries_total', 0)} "
            f"(skipped {bs.get('queries_skipped', 0)}, auto-tightened {bs.get('queries_tightened', 0)})"
        )
        lines.append(f"- Field mode: {bs.get('field_mode', 'none')} | Max results: {bs.get('max_results', 0):,}")
        lines.append(
            f"- New PMIDs: {bs.get('total_new_pmids', 0):,}, duplicates: {bs.get('total_dup_pmids', 0):,}"
        )
        for q in bs.get("queries", []):
            if q.get("skipped"):
                continue
            query_text = q.get('query', '')
            truncated = query_text[:80] + '...' if len(query_text) > 80 else query_text
            lines.append(
                f"- `{truncated}` — {q.get('result_count', 0):,} results, "
                f"{q.get('new_pmids', 0)} new [{q.get('field_level', '')}]"
            )
        lines.append("")

    if result.tfidf_stats:
        ts = result.tfidf_stats
        lines.append("### TF-IDF Term Mining")
        lines.append("")
        lines.append(f"- Docs used: {ts.get('docs_used', 0)} (skipped {ts.get('docs_skipped', 0)})")
        lines.append(f"- Terms used: {ts.get('terms_used', 0)} / {ts.get('terms_total', 0)}")
        field = ts.get("field", "tiab")
        joiner = (ts.get("joiner") or "OR").upper()
        lines.append(f"- Field: {field}" + (f" ({joiner})" if joiner != "OR" else ""))
        lines.append(
            f"- Results: {ts.get('total_pmids', 0):,} total, "
            f"{ts.get('new_pmids', 0):,} new, {ts.get('dup_pmids', 0):,} duplicates"
        )
        if ts.get("terms"):
            lines.append(f"- Terms: {', '.join(ts['terms'])}")
        if result.tfidf_query:
            lines.append("- Query:")
            lines.append("  ```")
            lines.append(f"  {result.tfidf_query}")
            lines.append("  ```")
        lines.append("")

    if result.citation_stats:
        cs = result.citation_stats
        lines.append("### Citation Expansion")
        lines.append("")
        lines.append(
            f"- Depth: {cs.get('depth', 1)}, direction: {cs.get('direction', 'both')}, "
            f"frontier cap: {cs.get('max_frontier', 0) or 'none'}"
        )
        lines.append(f"- Total citation PMIDs: {cs['total']:,}, new: {cs['new']:,}")
        lines.append(
            f"- Seeds: {cs.get('seed_with_pmid', 0)}/{cs.get('seed_total', 0)} with PMID"
            + (f", {cs['seed_doi_resolved']} resolved via DOI" if cs.get('seed_doi_resolved') else "")
        )
        lines.append("")

    if result.similar_stats:
        ss = result.similar_stats
        lines.append("### Similar Articles")
        lines.append("")
        lines.append(f"- Seeds with PMID: {ss.get('seed_with_pmid', 0)}")
        lines.append(f"- Per-seed cap: {ss.get('per_seed', 0)}")
        lines.append(
            f"- Results: {ss.get('total_pmids', 0):,} total, "
            f"{ss.get('new_pmids', 0):,} new, {ss.get('dup_pmids', 0):,} duplicates"
        )
        lines.append("")

    if result.similar_augment_stats:
        sa = result.similar_augment_stats
        lines.append("### Similar Articles (Round 2)")
        lines.append("")
        lines.append(
            f"- Augmentation pool: {sa.get('augmentation_pool', 0):,} PMIDs, sampled {sa.get('sampled', 0)}"
        )
        lines.append(f"- Per-PMID cap: {sa.get('per_pmid', 0)}")
        lines.append(
            f"- Results: {sa.get('total_pmids', 0):,} total, "
            f"{sa.get('new_pmids', 0):,} new, {sa.get('dup_pmids', 0):,} duplicates"
        )
        lines.append("")

    output_path.write_text("\n".join(lines))


def write_ris_file(result: RunResult, output_path: Path) -> None:
    """Write RIS file with PMIDs and DOIs only."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build pmid -> DOIs lookup
    pmid_dois: dict[str, list[str]] = {}
    for pmid, info in result.final_pmid_map.items():
        dois = info.get("dois", [])
        if dois:
            pmid_dois[pmid] = list(dois)

    for doi, info in result.final_doi_map.items():
        mapped_pmid = info.get("pmid")
        if mapped_pmid:
            if mapped_pmid not in pmid_dois:
                pmid_dois[mapped_pmid] = []
            if doi not in pmid_dois[mapped_pmid]:
                pmid_dois[mapped_pmid].append(doi)

    lines: list[str] = []
    for pmid in result.final_pmid_map:
        lines.append("TY  - JOUR")
        lines.append(f"ID  - {pmid}")
        for doi in pmid_dois.get(pmid, []):
            lines.append(f"DO  - {doi}")
        lines.append("ER  - ")
        lines.append("")

    output_path.write_text("\n".join(lines))


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Generate a PubMed systematic review query from a PROSPERO PDF."
    )
    parser.add_argument("prospero_pdf", type=Path, help="Path to PROSPERO protocol PDF")
    parser.add_argument(
        "--seeds", type=str, default="",
        help="Comma-separated PMIDs of seed papers (e.g., --seeds 12345,67890)",
    )
    parser.add_argument(
        "--output", type=str, default="output",
        help="Output file prefix (generates PREFIX.md and PREFIX.ris)",
    )
    parser.add_argument(
        "--extract", action="store_true",
        help="Extract the systematic review plan only (no query generation)",
    )
    parser.add_argument("-n", type=int, default=1, help="Number of LLM query runs to merge (default: 1)")
    parser.add_argument("--double-prompt", action="store_true", help="Repeat the prompt twice for emphasis")
    parser.add_argument("--seed-fields", type=str, default="tamk", help="Seed fields: t=title, a=abstract, m=MeSH, k=keywords (default: tamk)")
    parser.add_argument("--tfidf", action="store_true", help="Add TF-IDF supplemental query from seed papers")
    parser.add_argument("--tfidf-top", type=int, default=8, help="Number of TF-IDF terms (default: 8)")
    parser.add_argument("--tfidf-max-results", type=int, default=20000, help="Max results for TF-IDF query (default: 20000)")
    parser.add_argument("--block-drop", action="store_true", help="Add block-drop supplemental queries")
    parser.add_argument("--block-drop-max-results", type=int, default=20000, help="Max results for block-drop (default: 20000)")
    parser.add_argument("--block-drop-field", type=str, default="ti", help="Field tightening: none, ti, majr, ti+majr (default: ti)")
    parser.add_argument("--citations", action="store_true", help="Augment with citations via OpenAlex")
    parser.add_argument("--two-pass", action="store_true", help="Generate supplementary queries for missed seed papers")
    parser.add_argument("--two-pass-max", type=int, default=3, help="Max supplementary passes (default: 3)")
    parser.add_argument("--mesh-entry-terms", action="store_true", help="Expand MeSH terms with entry-term variants")
    parser.add_argument("--mesh-entry-max", type=int, default=6, help="Max entry terms per MeSH heading (default: 6)")
    parser.add_argument("--similar", type=int, default=0, help="Similar articles per seed (0 = disabled)")
    parser.add_argument("--similar-augment", type=int, default=0, help="Round 2 similar articles per augmentation PMID (0 = disabled)")
    parser.add_argument("--similar-augment-sample", type=int, default=10, help="Max PMIDs to sample for round 2 (default: 10)")
    parser.add_argument("--citation-depth", type=int, default=1, help="Citation expansion depth (default: 1)")
    parser.add_argument("--citation-direction", type=str, choices=["both", "forward", "backward"], default="both", help="Citation direction (default: both)")
    parser.add_argument("--citation-max-frontier", type=int, default=0, help="Cap works per depth (0 = no cap)")
    args = parser.parse_args()

    config = PipelineConfig.from_env()
    console = Console()

    if not args.prospero_pdf.exists():
        console.print(f"[red]PROSPERO PDF not found: {args.prospero_pdf}[/red]")
        sys.exit(1)

    # Extract-only mode
    if args.extract:
        client = OpenAIClient(api_key=config.openai_api_key, model=MODEL)
        response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=args.prospero_pdf)
        console.print(response.content, markup=False, highlight=False)
        sys.exit(0)

    # Fetch seed papers from PubMed if PMIDs provided
    seed_papers = None
    if args.seeds:
        seed_pmids = [p.strip() for p in args.seeds.split(",") if p.strip()]
        if seed_pmids:
            rate_delay = 0.1 if config.entrez_api_key else 0.34
            console.print(f"[dim]Fetching metadata for {len(seed_pmids)} seed paper(s)...[/dim]")
            seed_papers = fetch_seed_papers_by_pmid(
                seed_pmids, config.entrez_email, config.entrez_api_key, rate_delay,
            )
            console.print(f"[dim]Fetched {len(seed_papers)} seed paper(s)[/dim]")

    # Set up shared resources
    client = OpenAIClient(api_key=config.openai_api_key, model=MODEL)
    pubmed = PubMedExecutor(
        email=config.entrez_email, api_key=config.entrez_api_key,
        batch_size=config.pubmed_batch_size,
    )
    query_cache = QueryResultsCache(config.cache_dir)

    # Run the pipeline
    result = run_pipeline(
        prospero_pdf=args.prospero_pdf,
        seed_papers=seed_papers,
        args=args,
        config=config,
        client=client,
        pubmed=pubmed,
        query_cache=query_cache,
        console=console,
    )

    if result is None:
        console.print("[red]Pipeline produced no results[/red]")
        sys.exit(1)

    # Write outputs
    md_path = Path(f"{args.output}.md")
    ris_path = Path(f"{args.output}.ris")

    write_markdown_report(result, args, md_path)
    write_ris_file(result, ris_path)

    console.print(f"\n[bold]Results:[/bold]")
    console.print(f"  Total PMIDs: {result.total_result_count:,}")
    console.print(f"  Markdown report: {md_path}")
    console.print(f"  RIS file: {ris_path}")


if __name__ == "__main__":
    main()
