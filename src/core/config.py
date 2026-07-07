"""Configuration management — loads .env and providers.yaml, exposes typed settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Provider API keys ---
    gemini_api_key: str = ""
    nvidia_nim_api_key: str = ""
    groq_api_key: str = ""
    ocr_space_api_key: str = ""
    jina_api_key: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    openrouter_api_key: str = ""

    # --- Live data / Text-to-SQL ---
    # "sqlite" (default, uses the local live_data.db file) or "mysql".
    db_engine: str = "sqlite"
    db_host: str = ""
    db_port: int = 3306
    db_name: str = ""
    db_readonly_user: str = ""
    db_readonly_password: str = ""

    # --- Runtime paths ---
    upload_dir: Path = Field(default_factory=lambda: DATA_DIR / "uploads")
    processed_dir: Path = Field(default_factory=lambda: DATA_DIR / "processed")

    # --- Pipeline defaults ---
    ocr_confidence_threshold: float = 0.75
    chunk_target_tokens: int = 500
    chunk_overlap_fraction: float = 0.12
    retrieval_top_k: int = 50
    rerank_top_k: int = 25

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "env_file_encoding": "utf-8"}

    def ensure_dirs(self) -> None:
        """Create runtime directories if they don't exist."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)


def load_provider_config() -> dict[str, Any]:
    """Load the provider routing configuration from providers.yaml."""
    config_path = CONFIG_DIR / "providers.yaml"
    if not config_path.exists():
        logger.warning("providers.yaml not found at %s — using empty config", config_path)
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


# Module-level singleton — import this wherever config is needed.
settings = Settings()
