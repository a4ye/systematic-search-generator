"""Generate a PubMed query from a PROSPERO PDF using a single-shot prompt, then evaluate it."""

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from src.cache.pubmed_index_cache import PubMedIndexCache
from src.cache.query_results_cache import QueryResultsCache
from src.compare_search import extract_included_studies
from src.discovery.study_finder import StudyFinder
from src.evaluation.metrics import EvaluationMetrics, calculate_metrics_with_pubmed_check
from src.llm.openai_client import OpenAIClient
from src.pipeline.config import PipelineConfig
from src.pubmed.search_executor import PubMedExecutor, PubMedSearchResults

# ── Configuration ────────────────────────────────────────────────────────────
MODEL = "gpt-5.3-chat-latest"

QUERY_PROMPT = """\
Given a systematic review plan, generate a PubMed Boolean search query optimized for systematic review searching (target roughly <20,000 PubMed results).

Goal:
Maximize sensitivity while great reasonable precision.

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
    llm_queries: list[str] | None = None
    merged_query: str | None = None
    human_query: str | None = None
    error: str | None = None


def _calculate_total_steps(n_runs: int, include_human: bool) -> int:
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
    total_steps = _calculate_total_steps(n_runs, include_human)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )

    with progress:
        task_id = progress.add_task("Loading included studies...", total=total_steps)
        log = progress.console

        def step(description: str) -> None:
            progress.update(task_id, description=description, advance=1)

        # Load included studies
        included_result = extract_included_studies(str(study.included_studies_xlsx))
        step("Loading included studies")
        if not included_result.is_valid:
            log.print(f"[red]Error loading included studies: {included_result.error}[/red]")
            return None

        included_studies = included_result.studies
        log.print(f"Included studies: {len(included_studies)}")

        # Step 1: Extract plan from PROSPERO PDF
        progress.update(task_id, description=f"Extracting plan with {MODEL}...")
        extract_response = client.generate_with_file(prompt=EXTRACT_PROMPT, file_path=study.prospero_pdf)
        step("Extracted plan")
        plan_info = extract_response.content
        log.print(
            f"[dim]  Tokens: {extract_response.prompt_tokens} in / {extract_response.completion_tokens} out, "
            f"{extract_response.generation_time:.1f}s[/dim]"
        )

        # Step 2: Generate query from extracted plan
        query_prompt = QUERY_PROMPT + "\n" + plan_info
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

        def fetch_or_cached(query: str, label: str) -> PubMedSearchResults | None:
            cached_result = query_cache.get(query)
            if cached_result:
                log.print(f"[dim]{label}: using cached PubMed results[/dim]")
                step(f"{label}: cached")
                return PubMedSearchResults.from_cached(
                    query=query,
                    pmids=cached_result.pmids,
                    result_count=cached_result.result_count,
                    doi_to_pmid=cached_result.doi_to_pmid,
                )

            progress.update(task_id, description=f"{label}: counting results...")
            result_count = pubmed.count_results(query)
            if result_count > 50000:
                log.print(f"[red]Query too broad: {result_count:,} results (max 50,000)[/red]")
                step(f"{label}: too broad")
                return None

            progress.update(task_id, description=f"{label}: fetching {result_count:,} results...")
            search_results = pubmed.execute_query_fast(query, max_results=config.max_pubmed_results)
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

        # Execute the single (possibly merged) query against PubMed
        llm_results = fetch_or_cached(final_query, "LLM query")
        if llm_results is None:
            log.print("[red]No valid query results[/red]")
            return None

        progress.update(task_id, description="Checking PubMed indexing (LLM)...")
        llm_metrics = calculate_metrics_with_pubmed_check(
            llm_results,
            included_studies,
            entrez_email=config.entrez_email,
            rate_delay=rate_delay,
            index_cache=index_cache,
        )
        step("Checked PubMed indexing (LLM)")

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
                        included_studies,
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
        human_query=human_query,
    )


def save_results_md(results: list[StudyResult], args: argparse.Namespace) -> Path:
    """Save results to a markdown file in results/."""
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    study_ids = "_".join(r.study_id for r in results)
    filename = f"results_{study_ids}_{timestamp}.md"
    filepath = results_dir / filename

    lines: list[str] = []
    lines.append(f"# Query Generation Results")
    lines.append(f"")
    lines.append(f"- **Date**: {datetime.now().strftime('%b %d, %Y at %I:%M %p')}")
    lines.append(f"- **Model**: {MODEL}")
    lines.append(f"- **N runs**: {args.n}")
    lines.append(f"- **Double prompt**: {args.double_prompt}")
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
        lines.append(f"| Captured | {m.found}/{m.pubmed_indexed_count} | {h.found}/{h.pubmed_indexed_count} |" if h else f"| Captured | {m.found}/{m.pubmed_indexed_count} | — |")
        lines.append(f"| Missed (in PubMed) | {m.missed_pubmed_indexed} | {h.missed_pubmed_indexed if h else '—'} |")
        lines.append(f"| Recall (overall) | {m.recall_overall * 100:.1f}% ({m.found}/{m.total_included}) | {h.recall_overall * 100:.1f}% ({h.found}/{h.total_included}) |" if h else f"| Recall (overall) | {m.recall_overall * 100:.1f}% ({m.found}/{m.total_included}) | — |")
        lines.append(f"| Recall (PubMed only) | {m.recall_pubmed_only * 100:.1f}% ({m.found}/{m.pubmed_indexed_count}) | {h.recall_pubmed_only * 100:.1f}% ({h.found}/{h.pubmed_indexed_count}) |" if h else f"| Recall (PubMed only) | {m.recall_pubmed_only * 100:.1f}% ({m.found}/{m.pubmed_indexed_count}) | — |")
        lines.append(f"| Precision | {m.precision * 100:.2f}% ({m.found}/{m.total_results}) | {h.precision * 100:.2f}% ({h.found}/{h.total_results}) |" if h else f"| Precision | {m.precision * 100:.2f}% ({m.found}/{m.total_results}) | — |")
        nnr_str = f"{m.nnr:.1f}" if m.nnr != float("inf") else "—"
        h_nnr_str = f"{h.nnr:.1f}" if h and h.nnr != float("inf") else "—"
        lines.append(f"| NNR | {nnr_str} | {h_nnr_str} |")
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
        if r.human_query:
            lines.append(f"**Human Query:**")
            lines.append(f"```")
            lines.append(r.human_query)
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
