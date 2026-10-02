"""Core configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, loaded from .env or environment variables."""

    # Database
    database_url: str = "postgresql+asyncpg://northvaine:northvaine@localhost:5432/northvaine"

    # Nebius Token Factory (OpenAI-compatible)
    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"

    # Nemotron model routing
    model_fast: str = "nvidia/nvidia/Nemotron-3_5-Lightning"
    model_mid: str = "nvidia/nemotron-3-super-120b-a12b"
    model_deep: str = "nvidia/Nemotron-3-Ultra-550b-a55b"
    model_embed: str = "nvidia/NV-Embed-QA"
    embed_dim: int = 1024

    # Tavily
    tavily_api_key: str = ""

    # Budget
    daily_budget_usd: float = 5.00

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


settings = Settings()
