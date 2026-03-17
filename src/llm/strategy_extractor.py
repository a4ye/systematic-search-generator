"""Extract human search strategies from .docx files using LLM."""

from dataclasses import dataclass
from pathlib import Path

from ..cache.strategy_cache import CachedStrategy, StrategyCache

from .openai_client import LLMResponse, OpenAIClient
from .prompts import STRATEGY_EXTRACTION_PROMPT


@dataclass
class ExtractedStrategy:
    """Result of extracting a human search strategy."""

    query: str | None
    database: str
    source_file: Path
    extraction_time: float
    from_cache: bool
    error: str | None = None


class StrategyExtractor:
    """Extract human search strategies from .docx files."""

    def __init__(
        self,
        client: OpenAIClient,
        cache: StrategyCache,
        prompt: str = STRATEGY_EXTRACTION_PROMPT,
    ):
        self.client = client
        self.cache = cache
        self.prompt = prompt

    def extract_strategy(
        self,
        docx_path: Path,
        force_refresh: bool = False,
    ) -> ExtractedStrategy:
        """Extract PubMed search query from strategy document."""
        # Check cache first (unless force refresh)
        if not force_refresh:
            cached = self.cache.get(docx_path)
            if cached:
                return ExtractedStrategy(
                    query=cached.query,
                    database=cached.database,
                    source_file=docx_path,
                    extraction_time=0.0,
                    from_cache=True,
                )

        # Extract using LLM
        try:
            response: LLMResponse = self.client.generate_with_file(
                prompt=self.prompt,
                file_path=docx_path,
            )

            query = self._parse_response(response.content)

            if query:
                # Cache the result
                self.cache.set(
                    docx_path=docx_path,
                    query=query,
                    database="PubMed",
                    model_version=self.client.model,
                )

            return ExtractedStrategy(
                query=query,
                database="PubMed",
                source_file=docx_path,
                extraction_time=response.generation_time,
                from_cache=False,
            )

        except Exception as e:
            return ExtractedStrategy(
                query=None,
                database="PubMed",
                source_file=docx_path,
                extraction_time=0.0,
                from_cache=False,
                error=str(e),
            )

    def _parse_response(self, content: str) -> str | None:
        """Parse LLM response to extract the query."""
        content = content.strip()

        # Check for NOT_FOUND
        if content.upper() == "NOT_FOUND":
            return None

        # Clean up common prefixes
        prefixes_to_remove = [
            "Here is the PubMed search query:",
            "The PubMed search query is:",
            "PubMed Query:",
            "Query:",
        ]
        for prefix in prefixes_to_remove:
            if content.lower().startswith(prefix.lower()):
                content = content[len(prefix):].strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines if they're code block markers
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        # If empty after cleanup, return None
        if not content:
            return None

        return content
