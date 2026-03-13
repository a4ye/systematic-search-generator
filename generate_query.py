"""Generate a PubMed query from a PROSPERO PDF using a single-shot prompt, then evaluate it."""

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.cache.pubmed_index_cache import PubMedIndexCache
from src.cache.query_results_cache import QueryResultsCache
from src.compare_search import extract_included_studies
from src.discovery.study_finder import StudyFinder
from src.evaluation.metrics import calculate_metrics_with_pubmed_check
from src.llm.openai_client import OpenAIClient
from src.pipeline.config import PipelineConfig
from src.pubmed.search_executor import PubMedExecutor, PubMedSearchResults

# ── Configuration ────────────────────────────────────────────────────────────
MODEL = "gpt-5.3-chat-latest"

QUERY_PROMPT = """\
Given a systematic review plan, generate a PubMed Boolean search query optimized for systematic review searching (target roughly <20,000 PubMed results).

Goal:
Maximize sensitivity while maintaining great precision.

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

Output:
Return the final PubMed Boolean query in one line only.
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


# ── End configuration ────────────────────────────────────────────────────────


@dataclass
class StudyResult:
    """Results from running the pipeline on a single study."""

    study_id: str
    study_name: str
    llm_metrics: object  # MetricsResult
    human_metrics: object | None  # MetricsResult or None
    error: str | None = None


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


def print_study_table(console: Console, llm_metrics, human_metrics):
    """Print the per-study comparison table."""
    m = llm_metrics
    h = human_metrics

    def fmt_diff_int(gen_val, human_val, higher_is_better=True):
        if h is None:
            return "[dim]—[/dim]"
        diff = gen_val - human_val
        if human_val != 0:
            pct = (diff / human_val) * 100
            s = f"{diff:+d} ({pct:+.0f}%)"
        else:
            s = f"{diff:+d}"
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
        str(m.total_results),
        str(h.total_results) if h else na,
        fmt_diff_int(m.total_results, h.total_results, higher_is_better=False) if h else na,
    )
    table.add_row(
        "Captured",
        f"{m.found} / {m.pubmed_indexed_count}",
        f"{h.found} / {h.pubmed_indexed_count}" if h else na,
        fmt_diff_int(m.found, h.found) if h else na,
    )
    table.add_row(
        "Missed (in PubMed)",
        str(m.missed_pubmed_indexed),
        str(h.missed_pubmed_indexed) if h else na,
        fmt_diff_int(m.missed_pubmed_indexed, h.missed_pubmed_indexed, higher_is_better=False) if h else na,
    )
    table.add_row(
        "Recall (overall)",
        f"{m.recall_overall * 100:.1f}%  ({m.found}/{m.total_included})",
        f"{h.recall_overall * 100:.1f}%  ({h.found}/{h.total_included})" if h else na,
        fmt_diff_pct(m.recall_overall, h.recall_overall) if h else na,
    )
    table.add_row(
        "Recall (PubMed only)",
        f"{m.recall_pubmed_only * 100:.1f}%  ({m.found}/{m.pubmed_indexed_count})",
        f"{h.recall_pubmed_only * 100:.1f}%  ({h.found}/{h.pubmed_indexed_count})" if h else na,
        fmt_diff_pct(m.recall_pubmed_only, h.recall_pubmed_only) if h else na,
    )

    precision_diff = fmt_diff_pct(m.precision, h.precision) if h else na
    if h and h.precision > 0:
        rel = m.precision / h.precision
        color = "green" if rel >= 1.0 else "red"
        precision_diff += f"  [{color}]{rel:.1f}x[/{color}]"

    table.add_row(
        "Precision",
        f"{m.precision * 100:.2f}%  ({m.found}/{m.total_results})",
        f"{h.precision * 100:.2f}%  ({h.found}/{h.total_results})" if h else na,
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

    # Extract-only mode
    if args.extract:
        console.print(f"\n[dim]Extracting plan with {MODEL}...[/dim]")
        response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=study.prospero_pdf)
        console.print(
            f"[dim]Tokens: {response.prompt_tokens} in / {response.completion_tokens} out, {response.generation_time:.1f}s[/dim]\n")
        console.print(response.content, markup=False, highlight=False)
        return None

    if not study.included_studies_xlsx:
        console.print(f"[red]Study {study_id_arg} has no included studies file[/red]")
        return None

    # Load included studies
    included_result = extract_included_studies(str(study.included_studies_xlsx))
    if not included_result.is_valid:
        console.print(f"[red]Error loading included studies: {included_result.error}[/red]")
        return None

    included_studies = included_result.studies
    console.print(f"Included studies: {len(included_studies)}")

    # Step 1: Extract plan from PROSPERO PDF
    console.print(f"\n[dim]Step 1: Extracting plan with {MODEL}...[/dim]")
    extract_response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=study.prospero_pdf)
    plan_info = extract_response.content
    console.print(
        f"[dim]  Tokens: {extract_response.prompt_tokens} in / {extract_response.completion_tokens} out, {extract_response.generation_time:.1f}s[/dim]")

    # Step 2: Generate query from extracted plan
    n_runs = args.n
    console.print(f"\n[dim]Step 2: Generating query with {MODEL} (n={n_runs})...[/dim]")
    query_prompt = QUERY_PROMPT + "\n" + plan_info
    if args.double_prompt:
        query_prompt = query_prompt + "\n\n---\n\n" + query_prompt
        console.print("[dim]  (prompt doubled)[/dim]")

    # Save the final composed prompt
    prompt_dir = Path("temp")
    prompt_dir.mkdir(exist_ok=True)
    (prompt_dir / "final-prompt.txt").write_text(query_prompt)
    console.print(f"[dim]  Saved final prompt to temp/final-prompt.txt[/dim]")

    def _generate_one(run_i: int) -> tuple[int, str, int, int, float]:
        """Generate a single query. Returns (index, query, prompt_tokens, completion_tokens, time)."""
        resp = client.generate_text(prompt=query_prompt)
        q = extract_query_from_response(resp.content)
        return run_i, q, resp.prompt_tokens, resp.completion_tokens, resp.generation_time

    if n_runs == 1:
        _, q, pt, ct, gt = _generate_one(0)
        generated_queries = [q]
        console.print(f"[dim]  Tokens: {pt} in / {ct} out, {gt:.1f}s[/dim]")
    else:
        console.print(f"[dim]  Launching {n_runs} LLM calls in parallel...[/dim]")
        generated_queries = [""] * n_runs
        with ThreadPoolExecutor(max_workers=n_runs) as executor:
            futures = {executor.submit(_generate_one, i): i for i in range(n_runs)}
            for future in as_completed(futures):
                run_i, q, pt, ct, gt = future.result()
                generated_queries[run_i] = q
                console.print(f"[dim]  Run {run_i + 1}/{n_runs} done — {pt} in / {ct} out, {gt:.1f}s[/dim]")

    def fetch_or_cached(query: str) -> PubMedSearchResults:
        cached_result = query_cache.get(query)
        if cached_result:
            console.print("[dim]Using cached PubMed results[/dim]")
            return PubMedSearchResults.from_cached(
                query=query,
                pmids=cached_result.pmids,
                result_count=cached_result.result_count,
                doi_to_pmid=cached_result.doi_to_pmid,
            )

        console.print("[dim]Counting results...[/dim]")
        result_count = pubmed.count_results(query)
        if result_count > 50000:
            console.print(f"[red]Query too broad: {result_count:,} results (max 50,000)[/red]")
            return None

        console.print(f"[dim]Fetching {result_count:,} results...[/dim]")
        search_results = pubmed.execute_query_fast(query, max_results=config.max_pubmed_results)

        pmids = list(search_results.pmid_map.keys())
        doi_to_pmid = {doi: info["pmid"] for doi, info in search_results.doi_map.items()}
        query_cache.set(query, pmids, search_results.result_count, doi_to_pmid)

        return search_results

    # Execute each generated query and merge results (union of PMIDs)
    all_results: list[PubMedSearchResults] = []
    seen_queries: dict[str, PubMedSearchResults] = {}
    for i, q in enumerate(generated_queries):
        if n_runs > 1:
            console.print(f"\n[dim]Fetching results for query {i + 1}/{n_runs}...[/dim]")
            console.print(f"[dim]  {q[:100]}{'...' if len(q) > 100 else ''}[/dim]")
        if q in seen_queries:
            console.print("[dim]  Duplicate query, reusing results[/dim]")
            all_results.append(seen_queries[q])
        else:
            result = fetch_or_cached(q)
            if result is None:
                console.print(f"[red]Skipping query {i + 1} (too broad)[/red]")
                continue
            seen_queries[q] = result
            all_results.append(result)

    if not all_results:
        console.print("[red]No valid query results[/red]")
        return None

    if n_runs == 1 or len(all_results) == 1:
        llm_results = all_results[0]
    else:
        # Merge: union of PMIDs and DOIs across all runs
        merged_pmid_map: dict[str, dict] = {}
        merged_doi_map: dict[str, dict] = {}
        for result in all_results:
            for pmid, info in result.pmid_map.items():
                if pmid not in merged_pmid_map:
                    merged_pmid_map[pmid] = info
            for doi, info in result.doi_map.items():
                if doi not in merged_doi_map:
                    merged_doi_map[doi] = info

        merged_pmids = list(merged_pmid_map.keys())
        merged_doi_to_pmid = {doi: info["pmid"] for doi, info in merged_doi_map.items()}

        llm_results = PubMedSearchResults.from_cached(
            query=f"MERGED({n_runs} runs)",
            pmids=merged_pmids,
            result_count=len(merged_pmids),
            doi_to_pmid=merged_doi_to_pmid,
        )

        per_query_counts = [r.result_count for r in all_results]
        console.print(f"\n[dim]Per-query result counts: {per_query_counts}[/dim]")
        console.print(f"[dim]Merged unique PMIDs: {len(merged_pmids):,}[/dim]")

    console.print("[dim]Checking PubMed indexing...[/dim]")
    llm_metrics = calculate_metrics_with_pubmed_check(
        llm_results,
        included_studies,
        entrez_email=config.entrez_email,
        rate_delay=rate_delay,
        index_cache=index_cache,
    )

    # Evaluate human strategy (default, skip with --no-human)
    human_metrics = None
    if not args.no_human:
        if not study.search_strategy_docx:
            console.print("[yellow]No human search strategy available for this study[/yellow]")
        else:
            from src.cache.strategy_cache import StrategyCache

            strategy_cache = StrategyCache(config.cache_dir)
            cached = strategy_cache.get(study.search_strategy_docx)

            human_query = None
            if cached:
                console.print("[dim]Using cached human strategy[/dim]")
                human_query = cached.query
            else:
                from src.llm.strategy_extractor import StrategyExtractor

                extractor = StrategyExtractor(client, strategy_cache)
                console.print("[dim]Extracting human strategy...[/dim]")
                extracted = extractor.extract_strategy(study.search_strategy_docx)
                if extracted.query:
                    human_query = extracted.query

            if human_query:
                human_results = fetch_or_cached(human_query)
                if human_results:
                    human_metrics = calculate_metrics_with_pubmed_check(
                        human_results,
                        included_studies,
                        entrez_email=config.entrez_email,
                        rate_delay=rate_delay,
                        index_cache=index_cache,
                    )
            else:
                console.print("[yellow]Failed to extract human strategy[/yellow]")

    # Print per-study results
    console.print()
    console.print("─" * 70)
    print_study_table(console, llm_metrics, human_metrics)

    return StudyResult(
        study_id=study.study_id,
        study_name=study.name,
        llm_metrics=llm_metrics,
        human_metrics=human_metrics,
    )


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

        na = "[dim]—[/dim]"

        summary = Table(show_header=True, header_style="bold")
        summary.add_column("Study", width=30)
        summary.add_column("Results", justify="right", width=10)
        summary.add_column("Recall", justify="right", width=14)
        summary.add_column("Recall (PM)", justify="right", width=14)
        summary.add_column("Precision", justify="right", width=12)
        summary.add_column("NNR", justify="right", width=8)
        summary.add_column("H-Recall", justify="right", width=14)
        summary.add_column("H-Results", justify="right", width=10)

        total_found = 0
        total_included = 0
        total_pm_indexed = 0
        total_results = 0
        h_total_found = 0
        h_total_included = 0
        h_total_results = 0
        has_any_human = False

        for r in results:
            m = r.llm_metrics
            h = r.human_metrics

            label = f"{r.study_id} - {r.study_name}"
            if len(label) > 30:
                label = label[:27] + "..."

            recall_str = f"{m.recall_overall * 100:.1f}% ({m.found}/{m.total_included})"
            recall_pm_str = f"{m.recall_pubmed_only * 100:.1f}% ({m.found}/{m.pubmed_indexed_count})"
            precision_str = f"{m.precision * 100:.2f}%"
            nnr_str = f"{m.nnr:.1f}" if m.nnr != float("inf") else "—"

            if h:
                has_any_human = True
                h_recall_str = f"{h.recall_overall * 100:.1f}% ({h.found}/{h.total_included})"
                h_results_str = str(h.total_results)
                h_total_found += h.found
                h_total_included += h.total_included
                h_total_results += h.total_results
            else:
                h_recall_str = na
                h_results_str = na

            total_found += m.found
            total_included += m.total_included
            total_pm_indexed += m.pubmed_indexed_count
            total_results += m.total_results

            summary.add_row(
                label,
                str(m.total_results),
                recall_str,
                recall_pm_str,
                precision_str,
                nnr_str,
                h_recall_str,
                h_results_str,
            )

        # Averages row
        if total_included > 0:
            avg_recall = total_found / total_included * 100
        else:
            avg_recall = 0.0
        if total_pm_indexed > 0:
            avg_recall_pm = total_found / total_pm_indexed * 100
        else:
            avg_recall_pm = 0.0
        if total_results > 0:
            avg_precision = total_found / total_results * 100
            avg_nnr = total_results / total_found if total_found > 0 else float("inf")
        else:
            avg_precision = 0.0
            avg_nnr = float("inf")

        h_avg_recall_str = na
        h_avg_results_str = na
        if has_any_human and h_total_included > 0:
            h_avg_recall_str = f"{h_total_found / h_total_included * 100:.1f}% ({h_total_found}/{h_total_included})"
            h_avg_results_str = str(h_total_results)

        summary.add_section()
        summary.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_results}[/bold]",
            f"[bold]{avg_recall:.1f}% ({total_found}/{total_included})[/bold]",
            f"[bold]{avg_recall_pm:.1f}% ({total_found}/{total_pm_indexed})[/bold]",
            f"[bold]{avg_precision:.2f}%[/bold]",
            f"[bold]{avg_nnr:.1f}[/bold]" if avg_nnr != float("inf") else "[bold]—[/bold]",
            f"[bold]{h_avg_recall_str}[/bold]" if has_any_human else na,
            f"[bold]{h_avg_results_str}[/bold]" if has_any_human else na,
        )

        console.print(summary)
        console.print()


if __name__ == "__main__":
    main()
