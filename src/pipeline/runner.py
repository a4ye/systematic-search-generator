"""Main pipeline orchestrator for testing LLM-generated search queries."""

import argparse
import json
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, MofNCompleteColumn

from src.cache.pubmed_index_cache import PubMedIndexCache
from src.cache.query_results_cache import QueryResultsCache
from src.cache.strategy_cache import StrategyCache
from src.compare_search import IncludedStudy, extract_included_studies
from src.discovery.study_finder import StudyFinder, StudyInfo
from src.evaluation.comparator import ComparisonResult, aggregate_comparisons
from src.evaluation.metrics import calculate_metrics_with_pubmed_check
from src.evaluation.reporter import Reporter
from src.llm.openai_client import OpenAIClient
from src.llm.query_generator import GeneratedQuery, QueryGenerator
from src.llm.strategy_extractor import StrategyExtractor
from src.pipeline.config import PipelineConfig
from src.pubmed.search_executor import PubMedExecutor, PubMedSearchResults


class PipelineRunner:
    """Main orchestrator for the testing pipeline."""

    def __init__(self, config: PipelineConfig, max_seeds: int | None = 3, rng_seed: int | None = None, concise: bool = False):
        self.config = config
        self.max_seeds = max_seeds
        self.rng_seed = rng_seed
        self.concise = concise
        self.console = Console()
        self.reporter = Reporter(self.console)

        # Initialize components
        self.study_finder = StudyFinder(config.data_dir)
        self.strategy_cache = StrategyCache(config.cache_dir)
        self.index_cache = PubMedIndexCache(config.cache_dir)
        self.query_cache = QueryResultsCache(config.cache_dir)
        self.pubmed = PubMedExecutor(
            email=config.entrez_email,
            api_key=config.entrez_api_key,
            batch_size=config.pubmed_batch_size,
        )

        # Verbose logging helper
        self._log = self.console.print if not concise else lambda *a, **kw: None

        # LLM components (initialized lazily to allow human-only mode)
        self._openai_client: OpenAIClient | None = None
        self._query_generator: QueryGenerator | None = None
        self._strategy_extractor: StrategyExtractor | None = None

    @property
    def openai_client(self) -> OpenAIClient:
        if self._openai_client is None:
            self._openai_client = OpenAIClient(
                api_key=self.config.openai_api_key,
                model=self.config.openai_model,
            )
        return self._openai_client

    @property
    def query_generator(self) -> QueryGenerator:
        if self._query_generator is None:
            self._query_generator = QueryGenerator(
                self.openai_client,
                max_seeds=self.max_seeds,
                rng_seed=self.rng_seed,
                cache_dir=self.config.cache_dir,
                entrez_email=self.config.entrez_email,
                entrez_api_key=self.config.entrez_api_key,
            )
        return self._query_generator

    @property
    def strategy_extractor(self) -> StrategyExtractor:
        if self._strategy_extractor is None:
            self._strategy_extractor = StrategyExtractor(
                self.openai_client,
                self.strategy_cache,
            )
        return self._strategy_extractor

    def run_single_study(
        self,
        study: StudyInfo,
        llm_only: bool = False,
        human_only: bool = False,
        refresh_cache: bool = False,
        pregenerated_query: GeneratedQuery | None = None,
    ) -> ComparisonResult:
        """Run pipeline for a single study.

        Args:
            study: Study info
            llm_only: Only run LLM evaluation
            human_only: Only run human evaluation
            refresh_cache: Force refresh of cached data
            pregenerated_query: Optional pre-generated LLM query (for parallel batch processing)
        """
        result = ComparisonResult(
            study_id=study.study_id,
            study_name=study.name,
        )

        # Load included studies
        if not study.included_studies_xlsx:
            result.llm_error = "Missing included studies file"
            result.human_error = "Missing included studies file"
            return result

        included_result = extract_included_studies(str(study.included_studies_xlsx))
        if not included_result.is_valid:
            result.llm_error = included_result.error
            result.human_error = included_result.error
            return result

        included_studies = included_result.studies

        # Run LLM evaluation
        if not human_only:
            result = self._run_llm_evaluation(
                study, included_studies, result, pregenerated_query
            )

        # Run human evaluation
        if not llm_only:
            result = self._run_human_evaluation(
                study, included_studies, result, refresh_cache
            )

        return result

    def _run_llm_evaluation(
        self,
        study: StudyInfo,
        included_studies: list[IncludedStudy],
        result: ComparisonResult,
        pregenerated_query: "GeneratedQuery | None" = None,
    ) -> ComparisonResult:
        """Generate and evaluate LLM query.

        Args:
            study: Study info
            included_studies: List of included studies for comparison
            result: ComparisonResult to update
            pregenerated_query: Optional pre-generated query (for parallel batch processing)
        """
        if not study.prospero_pdf:
            result.llm_error = "Missing PROSPERO PDF"
            return result

        try:
            # Use pre-generated query or generate new one
            if pregenerated_query is not None:
                generated = pregenerated_query
                self._log(f"  [dim]Using pre-generated LLM query...[/dim]")
            else:
                t0 = time.time()
                self._log(f"  [dim]Generating LLM query (Extract → Compose → Refine)...[/dim]")
                generated = self.query_generator.generate_query(
                    study.prospero_pdf
                )
                self._log(f"  [dim]  -> LLM generation: {time.time() - t0:.1f}s[/dim]")

            result.llm_query = generated.query

            # Print pipeline output
            if generated.extracted_json is not None:
                self._log(f"\n  [bold]Step 1 — Extracted JSON:[/bold]")
                self._log(json.dumps(generated.extracted_json, indent=2, ensure_ascii=False))
            self._log(f"\n  [bold]Steps 2+3 — Composed & Refined Query:[/bold]")
            self._log(generated.query, markup=False, highlight=False)
            self._log()

            if not generated.is_valid:
                result.llm_error = f"Invalid query: {', '.join(generated.validation_errors)}"
                self.console.print(f"  [red]LLM Error: {result.llm_error}[/red]")
                return result

            # Check result count first
            t0 = time.time()
            self._log(f"  [dim]Executing LLM query on PubMed...[/dim]")
            result_count = self.pubmed.count_results(generated.query)

            if result_count > 50000:
                result.llm_error = f"Query too broad: {result_count:,} results (max 50,000)"
                self.console.print(f"  [dim]  -> Skipped: {result_count:,} results exceeds limit[/dim]")
                return result

            # Execute query with fast method (esummary instead of full MEDLINE)
            search_results = self.pubmed.execute_query_fast(
                generated.query,
                max_results=self.config.max_pubmed_results,
            )
            self._log(f"  [dim]  -> PubMed fetch ({search_results.result_count} results): {time.time() - t0:.1f}s[/dim]")

            # Calculate metrics with PubMed indexing check
            t0 = time.time()
            self._log(f"  [dim]Checking PubMed indexing for missed studies...[/dim]")
            result.llm_metrics = calculate_metrics_with_pubmed_check(
                search_results,
                included_studies,
                entrez_email=self.config.entrez_email,
                rate_delay=0.1 if self.config.entrez_api_key else 0.34,
                index_cache=self.index_cache,
            )
            self._log(f"  [dim]  -> Indexing check: {time.time() - t0:.1f}s[/dim]")

        except Exception as e:
            result.llm_error = str(e)
            self.console.print(f"  [red]LLM Error: {result.llm_error}[/red]")

        return result

    def _run_human_evaluation(
        self,
        study: StudyInfo,
        included_studies: list[IncludedStudy],
        result: ComparisonResult,
        refresh_cache: bool = False,
    ) -> ComparisonResult:
        """Extract and evaluate human query."""
        if not study.search_strategy_docx:
            result.human_error = "Missing search strategy document"
            return result

        try:
            # Extract strategy
            t0 = time.time()
            self._log(f"  [dim]Extracting human strategy...[/dim]")
            extracted = self.strategy_extractor.extract_strategy(
                study.search_strategy_docx,
                force_refresh=refresh_cache,
            )

            if extracted.from_cache:
                self._log(f"  [dim](using cached strategy)[/dim]")
            else:
                self._log(f"  [dim]  -> Strategy extraction: {time.time() - t0:.1f}s[/dim]")

            if not extracted.query:
                result.human_error = extracted.error or "Failed to extract query"
                return result

            result.human_query = extracted.query

            # Check query cache first
            cached_result = self.query_cache.get(extracted.query)
            if cached_result and not refresh_cache:
                self._log(f"  [dim]Using cached PubMed results...[/dim]")
                search_results = PubMedSearchResults.from_cached(
                    query=extracted.query,
                    pmids=cached_result.pmids,
                    result_count=cached_result.result_count,
                    doi_to_pmid=cached_result.doi_to_pmid,
                )
            else:
                # Execute on PubMed with fast method
                t0 = time.time()
                self._log(f"  [dim]Executing human query on PubMed...[/dim]")
                search_results = self.pubmed.execute_query_fast(
                    extracted.query,
                    max_results=self.config.max_pubmed_results,
                )
                self._log(f"  [dim]  -> PubMed fetch ({search_results.result_count} results): {time.time() - t0:.1f}s[/dim]")
                # Cache the results
                pmids = list(search_results.pmid_map.keys())
                doi_to_pmid = {
                    doi: info["pmid"] for doi, info in search_results.doi_map.items()
                }
                self.query_cache.set(
                    extracted.query, pmids, search_results.result_count, doi_to_pmid
                )

            # Calculate metrics with PubMed indexing check
            t0 = time.time()
            self._log(f"  [dim]Checking PubMed indexing for missed studies...[/dim]")
            result.human_metrics = calculate_metrics_with_pubmed_check(
                search_results,
                included_studies,
                entrez_email=self.config.entrez_email,
                rate_delay=0.1 if self.config.entrez_api_key else 0.34,
                index_cache=self.index_cache,
            )
            self._log(f"  [dim]  -> Indexing check: {time.time() - t0:.1f}s[/dim]")

        except Exception as e:
            result.human_error = str(e)

        return result

    def run_batch(
        self,
        studies: list[StudyInfo],
        llm_only: bool = False,
        human_only: bool = False,
        refresh_cache: bool = False,
        max_llm_workers: int = 5,
    ) -> list[ComparisonResult]:
        """Run pipeline for multiple studies.

        Args:
            studies: List of studies to process
            llm_only: Only run LLM evaluation
            human_only: Only run human evaluation
            refresh_cache: Force refresh of cached data
            max_llm_workers: Max parallel LLM query generation workers
        """
        results = []

        # Pre-generate LLM queries in parallel (if not human_only)
        pregenerated_queries: dict[str, GeneratedQuery] = {}
        if not human_only:
            studies_with_prospero = [s for s in studies if s.prospero_pdf]
            if studies_with_prospero:
                t0 = time.time()
                self._log(
                    f"[dim]Generating {len(studies_with_prospero)} LLM queries "
                    f"(Extract → Compose → Refine, max {max_llm_workers} workers)...[/dim]"
                )
                prospero_paths = [s.prospero_pdf for s in studies_with_prospero]
                generated = self.query_generator.generate_queries_batch(
                    prospero_paths,
                    max_workers=max_llm_workers,
                )
                for study, query in zip(studies_with_prospero, generated):
                    pregenerated_queries[study.study_id] = query
                    if not query.is_valid:
                        self.console.print(f"[red]  {study.study_id}: {', '.join(query.validation_errors)}[/red]")
                self._log(f"[dim]LLM query generation complete in {time.time() - t0:.1f}s[/dim]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task("Processing studies...", total=len(studies))

            for study in studies:
                progress.update(task, description=f"Processing {study.study_id} - {study.name}")

                result = self.run_single_study(
                    study,
                    llm_only=llm_only,
                    human_only=human_only,
                    refresh_cache=refresh_cache,
                    pregenerated_query=pregenerated_queries.get(study.study_id),
                )
                results.append(result)

                progress.advance(task)

        return results

    def list_studies(self) -> None:
        """List all discovered studies and their status."""
        studies = self.study_finder.discover_all()

        self.console.print(f"\n[bold]Found {len(studies)} studies[/bold]\n")

        complete = [s for s in studies if s.is_complete]
        incomplete = [s for s in studies if not s.is_complete]

        if complete:
            self.console.print("[green]Complete studies:[/green]")
            for s in complete:
                self.console.print(f"  {s.study_id} - {s.name}")

        if incomplete:
            self.console.print("\n[yellow]Incomplete studies:[/yellow]")
            for s in incomplete:
                self.console.print(f"  {s.study_id} - {s.name}")
                for missing in s.missing_files:
                    self.console.print(f"    [dim]Missing: {missing}[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Run automated testing pipeline for PubMed search queries."
    )

    # Study selection
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--study",
        type=str,
        help="Run a single study by ID (e.g., 34)",
    )
    group.add_argument(
        "--studies",
        type=str,
        help="Run multiple studies by ID, comma-separated (e.g., 34,92,101)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all complete studies",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List all discovered studies",
    )

    # Evaluation options
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="Only run LLM evaluation (skip human comparison)",
    )
    parser.add_argument(
        "--human-only",
        action="store_true",
        help="Only run human evaluation (skip LLM generation)",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Force re-extraction of human strategies (ignore cache)",
    )

    # Output options
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory for reports (default: results/)",
    )
    parser.add_argument(
        "--concise",
        action="store_true",
        help="Only show final results and query comparison (suppress progress details)",
    )

    # Seed paper options
    parser.add_argument(
        "--max-seeds",
        type=int,
        default=3,
        help="Max number of seed papers to sample per study (default: 3). "
             "Simulates realistic scenario where reviewers only have a few "
             "known papers. Use 0 or -1 for all (not recommended).",
    )
    parser.add_argument(
        "--rng-seed",
        type=int,
        default=None,
        help="Random seed for reproducible seed-paper sampling.",
    )

    args = parser.parse_args()

    # Load configuration
    config = PipelineConfig.from_env()

    if args.output:
        config.output_dir = args.output

    # Validate configuration
    if not args.list and not args.human_only:
        errors = config.validate()
        if errors:
            print("Configuration errors:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)

    # Initialize runner
    max_seeds = args.max_seeds if args.max_seeds > 0 else None
    runner = PipelineRunner(config, max_seeds=max_seeds, rng_seed=args.rng_seed, concise=args.concise)
    console = runner.console

    # Handle list command
    if args.list:
        runner.list_studies()
        return

    # Determine which studies to run
    if args.study:
        study = runner.study_finder.get_study(args.study)
        if not study:
            console.print(f"[red]Study {args.study} not found[/red]")
            sys.exit(1)
        studies = [study]
    elif args.studies:
        study_ids = [s.strip() for s in args.studies.split(",")]
        studies = runner.study_finder.get_studies(study_ids)
        if not studies:
            console.print(f"[red]No studies found for IDs: {args.studies}[/red]")
            sys.exit(1)
    elif args.all:
        studies = runner.study_finder.get_complete_studies()
        if not studies:
            console.print("[red]No complete studies found[/red]")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    if not args.concise:
        console.print(f"\n[bold]Running pipeline on {len(studies)} study/studies[/bold]\n")

    # Run pipeline
    if len(studies) == 1:
        # Single study - detailed output
        result = runner.run_single_study(
            studies[0],
            llm_only=args.llm_only,
            human_only=args.human_only,
            refresh_cache=args.refresh_cache,
        )
        runner.reporter.print_single_study(result)
    else:
        # Batch - summary output
        results = runner.run_batch(
            studies,
            llm_only=args.llm_only,
            human_only=args.human_only,
            refresh_cache=args.refresh_cache,
        )

        runner.reporter.print_summary_table(results)
        agg = aggregate_comparisons(results)
        runner.reporter.print_aggregate(agg)

        # Save reports
        runner.reporter.generate_markdown_report(
            results,
            agg,
            config.output_dir / "comparison_report.md",
        )
        runner.reporter.generate_csv(
            results,
            config.output_dir / "comparison_results.csv",
        )
        console.print(f"\n[dim]Reports saved to {config.output_dir}/[/dim]")


if __name__ == "__main__":
    main()
