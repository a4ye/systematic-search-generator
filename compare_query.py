"""Compare your own PubMed query against a study's included papers."""

import argparse
import sys

from rich.console import Console

from src.cache.pubmed_index_cache import PubMedIndexCache
from src.cache.query_results_cache import QueryResultsCache
from src.compare_search import extract_included_studies
from src.discovery.study_finder import StudyFinder
from src.evaluation.metrics import calculate_metrics_with_pubmed_check
from src.pipeline.config import PipelineConfig
from src.pubmed.search_executor import PubMedExecutor, PubMedSearchResults


def main():
    parser = argparse.ArgumentParser(
        description="Compare your own PubMed query against a study's included papers."
    )
    parser.add_argument("study", type=str, help="Study ID (e.g., 34)")
    parser.add_argument(
        "--show-human",
        action="store_true",
        help="Also evaluate and compare the human search strategy",
    )
    args = parser.parse_args()

    config = PipelineConfig.from_env()
    console = Console()

    # Find study
    finder = StudyFinder(config.data_dir)
    study = finder.get_study(args.study)
    if not study:
        console.print(f"[red]Study {args.study} not found[/red]")
        sys.exit(1)

    if not study.included_studies_xlsx:
        console.print(f"[red]Study {args.study} has no included studies file[/red]")
        sys.exit(1)

    console.print(f"\n[bold]Study: {study.study_id} - {study.name}[/bold]")

    # Load included studies
    included_result = extract_included_studies(str(study.included_studies_xlsx))
    if not included_result.is_valid:
        console.print(f"[red]Error loading included studies: {included_result.error}[/red]")
        sys.exit(1)

    included_studies = included_result.studies
    console.print(f"Included studies: {len(included_studies)}")

    # Prompt for query
    console.print("\n[bold]Paste your PubMed query below.[/bold]")
    console.print("[dim]Enter a blank line when done.[/dim]\n")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)

    user_query = "\n".join(lines).strip()
    if not user_query:
        console.print("[red]No query provided.[/red]")
        sys.exit(1)

    console.print(f"\n[dim]Query ({len(user_query)} chars)[/dim]")

    # Set up PubMed
    pubmed = PubMedExecutor(
        email=config.entrez_email,
        api_key=config.entrez_api_key,
        batch_size=config.pubmed_batch_size,
    )
    index_cache = PubMedIndexCache(config.cache_dir)
    query_cache = QueryResultsCache(config.cache_dir)
    rate_delay = 0.1 if config.entrez_api_key else 0.34

    def fetch_or_cached(query: str) -> PubMedSearchResults:
        """Fetch query results from cache or PubMed."""
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
            sys.exit(1)

        console.print(f"[dim]Fetching {result_count:,} results...[/dim]")
        search_results = pubmed.execute_query_fast(query, max_results=config.max_pubmed_results)

        # Cache the results
        pmids = list(search_results.pmid_map.keys())
        doi_to_pmid = {doi: info["pmid"] for doi, info in search_results.doi_map.items()}
        query_cache.set(query, pmids, search_results.result_count, doi_to_pmid)

        return search_results

    # Execute user query
    user_results = fetch_or_cached(user_query)

    console.print("[dim]Checking PubMed indexing...[/dim]")
    user_metrics = calculate_metrics_with_pubmed_check(
        user_results,
        included_studies,
        entrez_email=config.entrez_email,
        rate_delay=rate_delay,
        index_cache=index_cache,
    )

    # Optionally evaluate human strategy
    human_metrics = None
    human_query = None
    if args.show_human:
        if not study.search_strategy_docx:
            console.print("[yellow]No human search strategy available for this study[/yellow]")
        else:
            from src.cache.strategy_cache import StrategyCache

            strategy_cache = StrategyCache(config.cache_dir)
            cached = strategy_cache.get(study.search_strategy_docx)

            if cached:
                console.print("[dim]Using cached human strategy[/dim]")
                human_query = cached.query
            else:
                from src.llm.openai_client import OpenAIClient
                from src.llm.strategy_extractor import StrategyExtractor

                client = OpenAIClient(api_key=config.openai_api_key, model=config.openai_model)
                extractor = StrategyExtractor(client, strategy_cache)

                console.print("[dim]Extracting human strategy...[/dim]")
                extracted = extractor.extract_strategy(study.search_strategy_docx)
                if extracted.query:
                    human_query = extracted.query

            if human_query:
                human_results = fetch_or_cached(human_query)
                human_metrics = calculate_metrics_with_pubmed_check(
                    human_results,
                    included_studies,
                    entrez_email=config.entrez_email,
                    rate_delay=rate_delay,
                    index_cache=index_cache,
                )
            else:
                console.print("[yellow]Failed to extract human strategy[/yellow]")

    # Print results
    console.print()
    console.print("─" * 70)

    from rich.table import Table

    console.print(f"Included studies:       {user_metrics.total_included}")
    console.print(f"Not indexed in PubMed:  {user_metrics.not_in_pubmed}")
    console.print(f"PubMed-indexed:         {user_metrics.pubmed_indexed_count}")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric", style="dim", width=22)
    table.add_column("Your Query", justify="right", width=20)
    if human_metrics:
        table.add_column("Human", justify="right", width=20)

    def row(label, user_val, human_val=None):
        cols = [label, user_val]
        if human_metrics:
            cols.append(human_val or "[dim]—[/dim]")
        table.add_row(*cols)

    m = user_metrics
    h = human_metrics

    row("Search results", str(m.total_results), str(h.total_results) if h else None)
    row(
        "Captured",
        f"{m.found} / {m.pubmed_indexed_count}",
        f"{h.found} / {h.pubmed_indexed_count}" if h else None,
    )
    row(
        "Missed (in PubMed)",
        str(m.missed_pubmed_indexed),
        str(h.missed_pubmed_indexed) if h else None,
    )
    row(
        "Recall (overall)",
        f"{m.recall_overall*100:.1f}%  ({m.found}/{m.total_included})",
        f"{h.recall_overall*100:.1f}%  ({h.found}/{h.total_included})" if h else None,
    )
    row(
        "Recall (PubMed only)",
        f"{m.recall_pubmed_only*100:.1f}%  ({m.found}/{m.pubmed_indexed_count})",
        f"{h.recall_pubmed_only*100:.1f}%  ({h.found}/{h.pubmed_indexed_count})" if h else None,
    )
    row(
        "Precision",
        f"{m.precision*100:.2f}%  ({m.found}/{m.total_results})",
        f"{h.precision*100:.2f}%  ({h.found}/{h.total_results})" if h else None,
    )
    row(
        "NNR",
        f"{m.nnr:.1f}",
        f"{h.nnr:.1f}" if h else None,
    )

    console.print(table)

    # Print queries
    console.print(f"\n[bold]Your Query:[/bold]")
    console.print(user_query, markup=False, highlight=False)
    if human_query:
        console.print(f"\n[bold]Human Query:[/bold]")
        console.print(human_query, markup=False, highlight=False)

    console.print()


if __name__ == "__main__":
    main()
