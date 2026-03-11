"""Generate PubMed queries from PROSPERO PDFs using LLM."""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .openai_client import LLMResponse, OpenAIClient
from .prompts import BALANCED_QUERY_PROMPT


@dataclass
class GeneratedQuery:
    """Result of generating a PubMed query."""

    query: str
    model: str
    prompt_version: str
    generation_time: float
    token_usage: dict
    is_valid: bool
    validation_errors: list[str]


class QueryGenerator:
    """Generate PubMed queries from PROSPERO PDFs."""

    def __init__(self, client: OpenAIClient, prompt: str = BALANCED_QUERY_PROMPT):
        self.client = client
        self.prompt = prompt

    def generate_query(self, prospero_path: Path, max_retries: int = 3) -> GeneratedQuery:
        """Generate a PubMed query from a PROSPERO protocol PDF.

        Args:
            prospero_path: Path to PROSPERO PDF
            max_retries: Number of retries if validation fails
        """
        last_result = None

        for attempt in range(max_retries):
            response: LLMResponse = self.client.generate_with_file(
                prompt=self.prompt,
                file_path=prospero_path,
            )

            # Clean up the response - extract just the query
            query = self._extract_query(response.content)

            # Try to fix unbalanced parentheses before validation
            query = self._fix_parentheses(query)

            # Validate the query
            is_valid, errors = self._validate_query(query)

            last_result = GeneratedQuery(
                query=query,
                model=response.model,
                prompt_version="balanced_v1",
                generation_time=response.generation_time,
                token_usage={
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                },
                is_valid=is_valid,
                validation_errors=errors,
            )

            if is_valid:
                return last_result

            # Retry if validation failed (e.g., unbalanced parentheses)

        return last_result  # Return last attempt even if invalid

    def _extract_query(self, content: str) -> str:
        """Extract the query from LLM response, removing any explanatory text."""
        content = content.strip()

        # If the response starts with a parenthesis, it's likely the query itself
        if content.startswith("("):
            # Find the matching closing parenthesis at the top level
            # Take everything up to the end of the boolean expression
            return self._extract_boolean_query(content)

        # Look for a query pattern in the content
        # Common patterns: starts with ( or with a MeSH term
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("(") and "[" in line:
                return self._extract_boolean_query(line)
            if re.match(r'^"[^"]+"\[(Mesh|tiab|tw)\]', line):
                return line

        # If no clear pattern, return the whole content (trimmed)
        return content.strip()

    def _extract_boolean_query(self, content: str) -> str:
        """Extract a complete boolean query from content."""
        # Simple extraction - take the first line that looks like a query
        # and continues until we have balanced parentheses
        lines = content.split("\n")
        query_parts = []
        paren_count = 0
        started = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if not started and (line.startswith("(") or "[" in line):
                started = True

            if started:
                query_parts.append(line)
                paren_count += line.count("(") - line.count(")")

                if started and paren_count <= 0:
                    break

        return " ".join(query_parts)

    def _fix_parentheses(self, query: str) -> str:
        """Attempt to fix unbalanced parentheses in a query.

        Uses a simple heuristic: if there are more ( than ), add ) at the end.
        This works for the common case where LLMs forget to close parentheses.

        For more complex issues (like ) before (), we don't attempt to fix
        and let the retry logic handle it.
        """
        open_count = query.count("(")
        close_count = query.count(")")

        if open_count == close_count:
            return query

        if open_count > close_count:
            # Missing closing parens - add them at the end
            # This is the most common LLM error
            return query + ")" * (open_count - close_count)

        # More closing than opening is harder to fix correctly
        # Don't attempt - let retry logic regenerate
        return query

    def _validate_query(self, query: str) -> tuple[bool, list[str]]:
        """Validate PubMed query syntax."""
        errors = []

        if not query:
            errors.append("Query is empty")
            return False, errors

        # Check balanced parentheses
        if query.count("(") != query.count(")"):
            errors.append(f"Unbalanced parentheses: {query.count('(')} '(' vs {query.count(')')} ')'")

        # Check balanced brackets
        if query.count("[") != query.count("]"):
            errors.append(f"Unbalanced brackets: {query.count('[')} '[' vs {query.count(']')} ']'")

        # Check for common field tags
        has_field_tags = bool(re.search(r"\[(Mesh|tiab|tw|ti|ab|pt|mh)\]", query, re.IGNORECASE))
        if not has_field_tags:
            errors.append("No field tags found (expected [Mesh], [tiab], etc.)")

        # Check for boolean operators
        has_operators = bool(re.search(r"\b(AND|OR)\b", query))
        if not has_operators:
            errors.append("No boolean operators found (expected AND, OR)")

        return len(errors) == 0, errors

    def generate_queries_batch(
        self,
        prospero_paths: list[Path],
        max_workers: int = 5,
    ) -> list[GeneratedQuery]:
        """Generate PubMed queries for multiple PROSPERO PDFs in parallel.

        Args:
            prospero_paths: List of paths to PROSPERO protocol PDFs
            max_workers: Maximum number of concurrent LLM requests

        Returns:
            List of GeneratedQuery results in the same order as input paths
        """
        results: list[GeneratedQuery | None] = [None] * len(prospero_paths)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_idx = {
                executor.submit(self.generate_query, path): idx
                for idx, path in enumerate(prospero_paths)
            }

            # Collect results as they complete
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    # Create an error result for failed generations
                    results[idx] = GeneratedQuery(
                        query="",
                        model="",
                        prompt_version="balanced_v1",
                        generation_time=0.0,
                        token_usage={},
                        is_valid=False,
                        validation_errors=[f"Generation failed: {e}"],
                    )

        return results  # type: ignore
