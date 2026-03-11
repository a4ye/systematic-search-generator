"""Compare LLM and human search strategies."""

from dataclasses import dataclass, field
from typing import Literal

from .metrics import EvaluationMetrics


@dataclass
class ComparisonResult:
    """Result of comparing LLM and human strategies for a single study."""

    study_id: str
    study_name: str

    llm_metrics: EvaluationMetrics | None = None
    human_metrics: EvaluationMetrics | None = None

    llm_query: str | None = None
    human_query: str | None = None

    llm_error: str | None = None
    human_error: str | None = None

    @property
    def has_llm(self) -> bool:
        return self.llm_metrics is not None

    @property
    def has_human(self) -> bool:
        return self.human_metrics is not None

    @property
    def has_both(self) -> bool:
        return self.has_llm and self.has_human

    @property
    def recall_difference(self) -> float | None:
        """LLM recall minus human recall (positive = LLM better)."""
        if not self.has_both:
            return None
        return self.llm_metrics.recall_pubmed_only - self.human_metrics.recall_pubmed_only

    @property
    def precision_difference(self) -> float | None:
        """LLM precision minus human precision (positive = LLM better)."""
        if not self.has_both:
            return None
        return self.llm_metrics.precision - self.human_metrics.precision

    @property
    def precision_relative_change(self) -> float | None:
        """LLM precision / human precision (>1 = LLM better, e.g. 2.0 means 2x)."""
        if not self.has_both:
            return None
        if self.human_metrics.precision == 0:
            return None
        return self.llm_metrics.precision / self.human_metrics.precision

    @property
    def winner(self) -> Literal["llm", "human", "tie", "incomplete"] | None:
        """Determine winner based on recall (primary) and precision (secondary)."""
        if not self.has_both:
            return "incomplete"

        llm_recall = self.llm_metrics.recall_pubmed_only
        human_recall = self.human_metrics.recall_pubmed_only

        # If recalls differ by more than 5%, winner is higher recall
        if abs(llm_recall - human_recall) > 0.05:
            return "llm" if llm_recall > human_recall else "human"

        # If recalls are similar, compare precision
        llm_prec = self.llm_metrics.precision
        human_prec = self.human_metrics.precision

        if abs(llm_prec - human_prec) > 0.01:
            return "llm" if llm_prec > human_prec else "human"

        return "tie"


@dataclass
class AggregateComparison:
    """Aggregate statistics across multiple study comparisons."""

    total_studies: int
    complete_comparisons: int
    llm_only: int
    human_only: int
    failed: int

    mean_llm_recall: float
    mean_human_recall: float
    mean_llm_precision: float
    mean_human_precision: float

    llm_wins: int
    human_wins: int
    ties: int

    incomplete_studies: list[str] = field(default_factory=list)


def aggregate_comparisons(results: list[ComparisonResult]) -> AggregateComparison:
    """Calculate aggregate statistics from comparison results."""
    total = len(results)
    complete = [r for r in results if r.has_both]
    llm_only = [r for r in results if r.has_llm and not r.has_human]
    human_only = [r for r in results if r.has_human and not r.has_llm]
    failed = [r for r in results if not r.has_llm and not r.has_human]

    # Calculate means for complete comparisons
    if complete:
        mean_llm_recall = sum(r.llm_metrics.recall_pubmed_only for r in complete) / len(complete)
        mean_human_recall = sum(r.human_metrics.recall_pubmed_only for r in complete) / len(complete)
        mean_llm_precision = sum(r.llm_metrics.precision for r in complete) / len(complete)
        mean_human_precision = sum(r.human_metrics.precision for r in complete) / len(complete)
    else:
        mean_llm_recall = mean_human_recall = mean_llm_precision = mean_human_precision = 0.0

    # Count winners
    llm_wins = sum(1 for r in complete if r.winner == "llm")
    human_wins = sum(1 for r in complete if r.winner == "human")
    ties = sum(1 for r in complete if r.winner == "tie")

    # List incomplete studies
    incomplete = [
        f"{r.study_id} - {r.study_name}"
        for r in results
        if not r.has_both
    ]

    return AggregateComparison(
        total_studies=total,
        complete_comparisons=len(complete),
        llm_only=len(llm_only),
        human_only=len(human_only),
        failed=len(failed),
        mean_llm_recall=mean_llm_recall,
        mean_human_recall=mean_human_recall,
        mean_llm_precision=mean_llm_precision,
        mean_human_precision=mean_human_precision,
        llm_wins=llm_wins,
        human_wins=human_wins,
        ties=ties,
        incomplete_studies=incomplete,
    )
