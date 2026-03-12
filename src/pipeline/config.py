"""Configuration management for the pipeline."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class PipelineConfig:
    """Configuration for the testing pipeline."""

    data_dir: Path = field(default_factory=lambda: Path("data"))
    cache_dir: Path = field(default_factory=lambda: Path(".cache"))
    output_dir: Path = field(default_factory=lambda: Path("results"))

    openai_api_key: str = ""
    openai_model: str = "gpt-5.4"  # Default model for query generation

    entrez_email: str = "user@example.com"
    entrez_api_key: str | None = None

    max_pubmed_results: int = 10000
    pubmed_batch_size: int = 200

    def __post_init__(self):
        """Ensure directories exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "PipelineConfig":
        """Load configuration from environment variables."""
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            cache_dir=Path(os.getenv("CACHE_DIR", ".cache")),
            output_dir=Path(os.getenv("OUTPUT_DIR", "results")),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-2026-03-05"),
            entrez_email=os.getenv("ENTREZ_EMAIL", "user@example.com"),
            entrez_api_key=os.getenv("ENTREZ_API_KEY") or os.getenv("PUBMED_API_KEY"),
            max_pubmed_results=int(os.getenv("MAX_PUBMED_RESULTS", "10000")),
            pubmed_batch_size=int(os.getenv("PUBMED_BATCH_SIZE", "200")),
        )

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is not set")
        if not self.data_dir.exists():
            errors.append(f"Data directory does not exist: {self.data_dir}")
        return errors
