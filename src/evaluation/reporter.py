"""Generate reports for evaluation results."""

import csv
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .comparator import AggregateComparison, ComparisonResult
from .metrics import EvaluationMetrics


class Reporter:
    """Generate comparison reports."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def print_single_study(self, result: ComparisonResult) -> None:
        """Print detailed results for a single study."""
        self.console.print()
        self.console.print(f"[bold]Study: {result.study_id} - {result.study_name}[/bold]")
        self.console.print("─" * 70)

        llm = result.llm_metrics
        human = result.human_metrics

        # Use LLM metrics as reference for study counts (they should be the same)
        ref = llm or human
        if ref:
            self.console.print(f"Included studies:       {ref.total_included}")
            self.console.print(f"Not indexed in PubMed:  {ref.not_in_pubmed}")
            self.console.print(f"PubMed-indexed:         {ref.pubmed_indexed_count}")
            self.console.print()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Metric", style="dim", width=22)
        table.add_column("LLM", justify="right", width=18)
        table.add_column("Human", justify="right", width=18)
        table.add_column("Diff", justify="right", width=18)

        def fmt_val(m: EvaluationMetrics | None, attr: str, fmt: str = "{}") -> str:
            if m is None:
                return "[dim]N/A[/dim]"
            val = getattr(m, attr)
            if isinstance(val, float):
                if val == float("inf"):
                    return "∞"
                if "%" in fmt:
                    return fmt.format(val * 100)
                return fmt.format(val)
            return fmt.format(val)

        def fmt_diff(attr: str, higher_is_better: bool = True, is_pct: bool = False) -> str:
            if not llm or not human:
                return "[dim]—[/dim]"
            llm_val = getattr(llm, attr)
            human_val = getattr(human, attr)
            if isinstance(llm_val, float) and isinstance(human_val, float):
                if llm_val == float("inf") or human_val == float("inf"):
                    return "[dim]—[/dim]"
                diff = llm_val - human_val
                if is_pct:
                    diff_str = f"{diff * 100:+.1f}%"
                else:
                    diff_str = f"{diff:+.1f}"
                if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
                    return f"[green]{diff_str}[/green]"
                elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
                    return f"[red]{diff_str}[/red]"
                return diff_str
            return "[dim]—[/dim]"

        def fmt_int_diff(attr: str, higher_is_better: bool = True) -> str:
            if not llm or not human:
                return "[dim]—[/dim]"
            llm_val = getattr(llm, attr)
            human_val = getattr(human, attr)
            diff = llm_val - human_val
            diff_str = f"{diff:+d}"
            if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
                return f"[green]{diff_str}[/green]"
            elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
                return f"[red]{diff_str}[/red]"
            return diff_str

        def fmt_int_diff_pct(attr: str, higher_is_better: bool = True) -> str:
            """Format integer diff with percentage change."""
            if not llm or not human:
                return "[dim]—[/dim]"
            llm_val = getattr(llm, attr)
            human_val = getattr(human, attr)
            diff = llm_val - human_val
            if human_val != 0:
                pct = (diff / human_val) * 100
                diff_str = f"{diff:+d} ({pct:+.0f}%)"
            else:
                diff_str = f"{diff:+d}"
            if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
                return f"[green]{diff_str}[/green]"
            elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
                return f"[red]{diff_str}[/red]"
            return diff_str

        def fmt_float_diff_pct(attr: str, higher_is_better: bool = True) -> str:
            """Format float diff with percentage change."""
            if not llm or not human:
                return "[dim]—[/dim]"
            llm_val = getattr(llm, attr)
            human_val = getattr(human, attr)
            if isinstance(llm_val, float) and isinstance(human_val, float):
                if llm_val == float("inf") or human_val == float("inf"):
                    return "[dim]—[/dim]"
                diff = llm_val - human_val
                if human_val != 0:
                    pct = (diff / human_val) * 100
                    diff_str = f"{diff:+.1f} ({pct:+.0f}%)"
                else:
                    diff_str = f"{diff:+.1f}"
                if (diff > 0 and higher_is_better) or (diff < 0 and not higher_is_better):
                    return f"[green]{diff_str}[/green]"
                elif (diff < 0 and higher_is_better) or (diff > 0 and not higher_is_better):
                    return f"[red]{diff_str}[/red]"
                return diff_str
            return "[dim]—[/dim]"

        table.add_row(
            "Search results",
            fmt_val(llm, "total_results"),
            fmt_val(human, "total_results"),
            fmt_int_diff_pct("total_results", higher_is_better=False),
        )
        table.add_row(
            "Captured",
            f"{llm.found_pubmed} / {llm.pubmed_indexed_count}" if llm else "N/A",
            f"{human.found_pubmed} / {human.pubmed_indexed_count}" if human else "N/A",
            fmt_int_diff("found_pubmed", higher_is_better=True),
        )
        table.add_row(
            "Missed (in PubMed)",
            str(llm.missed_pubmed_indexed) if llm else "N/A",
            str(human.missed_pubmed_indexed) if human else "N/A",
            fmt_int_diff("missed_pubmed_indexed", higher_is_better=False),
        )
        table.add_row(
            "Recall (overall)",
            f"{llm.recall_overall*100:.1f}%  ({llm.found}/{llm.total_included})" if llm else "N/A",
            f"{human.recall_overall*100:.1f}%  ({human.found}/{human.total_included})" if human else "N/A",
            fmt_diff("recall_overall", is_pct=True),
        )
        table.add_row(
            "Recall (PubMed only)",
            f"{llm.recall_pubmed_only*100:.1f}%  ({llm.found_pubmed}/{llm.pubmed_indexed_count})" if llm else "N/A",
            f"{human.recall_pubmed_only*100:.1f}%  ({human.found_pubmed}/{human.pubmed_indexed_count})" if human else "N/A",
            fmt_diff("recall_pubmed_only", is_pct=True),
        )
        # Precision diff with relative change
        precision_diff_str = fmt_diff("precision", is_pct=True)
        rel = result.precision_relative_change
        if rel is not None:
            color = "green" if rel >= 1.0 else "red"
            precision_diff_str += f"  [{color}]{rel:.1f}x[/{color}]"

        table.add_row(
            "Precision",
            f"{llm.precision*100:.2f}%  ({llm.found}/{llm.total_results})" if llm else "N/A",
            f"{human.precision*100:.2f}%  ({human.found}/{human.total_results})" if human else "N/A",
            precision_diff_str,
        )
        table.add_row(
            "NNR",
            fmt_val(llm, "nnr", "{:.1f}"),
            fmt_val(human, "nnr", "{:.1f}"),
            fmt_float_diff_pct("nnr", higher_is_better=False),
        )

        self.console.print(table)

        if result.llm_error:
            self.console.print(f"[red]LLM Error: {result.llm_error}[/red]")
        if result.human_error:
            self.console.print(f"[red]Human Error: {result.human_error}[/red]")

        # Print both queries
        if result.llm_query:
            self.console.print(f"\n[bold]LLM Query:[/bold]")
            self.console.print(result.llm_query, markup=False, highlight=False)
        if result.human_query:
            self.console.print(f"\n[bold]Human Query:[/bold]")
            self.console.print(result.human_query, markup=False, highlight=False)

        self.console.print()

    def print_summary_table(self, results: list[ComparisonResult]) -> None:
        """Print a summary table of all results."""
        table = Table(title="Study Comparison Summary", show_header=True, header_style="bold")
        table.add_column("Study", style="dim")
        table.add_column("LLM Results", justify="right")
        table.add_column("LLM Recall", justify="right")
        table.add_column("Human Results", justify="right")
        table.add_column("Human Recall", justify="right")
        table.add_column("Winner", justify="center")

        for r in results:
            llm = r.llm_metrics
            human = r.human_metrics

            winner_style = {
                "llm": "[green]LLM[/green]",
                "human": "[yellow]Human[/yellow]",
                "tie": "[blue]Tie[/blue]",
                "incomplete": "[dim]—[/dim]",
            }.get(r.winner or "incomplete", "—")

            table.add_row(
                f"{r.study_id} - {r.study_name[:20]}",
                str(llm.total_results) if llm else "—",
                f"{llm.recall_pubmed_only*100:.1f}%" if llm else "—",
                str(human.total_results) if human else "—",
                f"{human.recall_pubmed_only*100:.1f}%" if human else "—",
                winner_style,
            )

        self.console.print(table)

    def print_aggregate(self, agg: AggregateComparison) -> None:
        """Print aggregate comparison statistics."""
        self.console.print()
        self.console.print("[bold]═" * 60 + "[/bold]")
        self.console.print(f"[bold]AGGREGATE COMPARISON ({agg.total_studies} studies)[/bold]")
        self.console.print("[bold]═" * 60 + "[/bold]")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Metric")
        table.add_column("LLM", justify="right")
        table.add_column("Human", justify="right")

        table.add_row(
            "Mean Recall (PubMed)",
            f"{agg.mean_llm_recall*100:.1f}%",
            f"{agg.mean_human_recall*100:.1f}%",
        )
        table.add_row(
            "Mean Precision",
            f"{agg.mean_llm_precision*100:.2f}%",
            f"{agg.mean_human_precision*100:.2f}%",
        )

        self.console.print(table)
        self.console.print()

        self.console.print(f"Studies where LLM wins:   [green]{agg.llm_wins}[/green] ({agg.llm_wins/agg.complete_comparisons*100:.1f}%)" if agg.complete_comparisons else "")
        self.console.print(f"Studies where Human wins: [yellow]{agg.human_wins}[/yellow] ({agg.human_wins/agg.complete_comparisons*100:.1f}%)" if agg.complete_comparisons else "")
        self.console.print(f"Ties:                     [blue]{agg.ties}[/blue]")
        self.console.print()

        if agg.incomplete_studies:
            self.console.print(f"[dim]Incomplete comparisons: {len(agg.incomplete_studies)}[/dim]")
            for study in agg.incomplete_studies[:5]:
                self.console.print(f"[dim]  - {study}[/dim]")
            if len(agg.incomplete_studies) > 5:
                self.console.print(f"[dim]  ... and {len(agg.incomplete_studies) - 5} more[/dim]")

        self.console.print("[bold]═" * 60 + "[/bold]")

    def generate_markdown_report(
        self,
        results: list[ComparisonResult],
        agg: AggregateComparison,
        output_path: Path,
    ) -> None:
        """Generate a detailed markdown report."""
        lines = [
            "# Search Strategy Comparison Report",
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"- Total studies: {agg.total_studies}",
            f"- Complete comparisons: {agg.complete_comparisons}",
            f"- LLM wins: {agg.llm_wins}",
            f"- Human wins: {agg.human_wins}",
            f"- Ties: {agg.ties}",
            "",
            "## Aggregate Metrics",
            "",
            "| Metric | LLM | Human |",
            "|--------|-----|-------|",
            f"| Mean Recall (PubMed) | {agg.mean_llm_recall*100:.1f}% | {agg.mean_human_recall*100:.1f}% |",
            f"| Mean Precision | {agg.mean_llm_precision*100:.2f}% | {agg.mean_human_precision*100:.2f}% |",
            "",
            "## Individual Studies",
            "",
        ]

        for r in results:
            llm = r.llm_metrics
            human = r.human_metrics

            rel = r.precision_relative_change
            rel_str = f" ({rel:.1f}x)" if rel is not None else ""
            lines.extend([
                f"### {r.study_id} - {r.study_name}",
                "",
                "| Metric | LLM | Human |",
                "|--------|-----|-------|",
                f"| Results | {llm.total_results if llm else 'N/A'} | {human.total_results if human else 'N/A'} |",
                f"| Recall (PubMed) | {llm.recall_pubmed_only*100:.1f}% | {human.recall_pubmed_only*100:.1f}% |" if llm and human else "",
                f"| Precision | {llm.precision*100:.2f}%{rel_str} | {human.precision*100:.2f}% |" if llm and human else "",
                f"| Winner | {r.winner} |" if r.has_both else "",
                "",
            ])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write("\n".join(lines))

    def generate_csv(
        self,
        results: list[ComparisonResult],
        output_path: Path,
    ) -> None:
        """Generate CSV summary for further analysis."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "study_id",
                "study_name",
                "llm_results",
                "llm_recall_overall",
                "llm_recall_pubmed",
                "llm_precision",
                "llm_nnr",
                "human_results",
                "human_recall_overall",
                "human_recall_pubmed",
                "human_precision",
                "human_nnr",
                "precision_diff",
                "precision_relative_change",
                "winner",
            ])

            for r in results:
                llm = r.llm_metrics
                human = r.human_metrics
                writer.writerow([
                    r.study_id,
                    r.study_name,
                    llm.total_results if llm else "",
                    f"{llm.recall_overall:.4f}" if llm else "",
                    f"{llm.recall_pubmed_only:.4f}" if llm else "",
                    f"{llm.precision:.4f}" if llm else "",
                    f"{llm.nnr:.2f}" if llm else "",
                    human.total_results if human else "",
                    f"{human.recall_overall:.4f}" if human else "",
                    f"{human.recall_pubmed_only:.4f}" if human else "",
                    f"{human.precision:.4f}" if human else "",
                    f"{human.nnr:.2f}" if human else "",
                    f"{r.precision_difference:.4f}" if r.precision_difference is not None else "",
                    f"{r.precision_relative_change:.2f}" if r.precision_relative_change is not None else "",
                    r.winner or "",
                ])
