"""
Configuration loaded from environment variables.

Uses pydantic-settings so a .env file is auto-loaded and every value is
type-checked at startup. If a required var is missing the service refuses
to start — no silent runtime surprises.
"""

from functools import lru_cache
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- LLM configuration -------------------------------------------------
    # We use the OpenAI SDK because it works with OpenAI, Groq (free), Together,
    # DeepSeek, and any provider offering an OpenAI-compatible endpoint.
    llm_api_key: str = Field(..., description="LLM provider API key")
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible base URL. Use https://api.groq.com/openai/v1 for Groq.",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model name. e.g. llama-3.3-70b-versatile for Groq.",
    )
    llm_max_iterations: int = Field(
        default=8,
        description="Max agent tool-call loops before giving up. Prevents runaway costs.",
    )
    llm_timeout_seconds: int = Field(
        default=25,
        description="Per-LLM-call timeout. Total agent budget is roughly max_iterations * timeout.",
    )

    # ---- Backends the agent queries ---------------------------------------
    prometheus_url: str = Field(
        default="http://prometheus:9090",
        description="Prometheus base URL. Use host.docker.internal when running outside compose.",
    )
    loki_url: str = Field(
        default="http://loki:3100",
        description="Loki base URL.",
    )

    # ---- Slack output ------------------------------------------------------
    slack_webhook_url: str = Field(..., description="Slack incoming webhook URL")

    # ---- Runbook RAG -------------------------------------------------------
    runbook_dir: str = Field(
        default="/app/runbooks",
        description="Filesystem path holding runbook markdown files.",
    )
    embeddings_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformer model for local embeddings. Free, no API.",
    )
    chroma_persist_dir: str = Field(
        default="/data/chroma",
        description="Where Chroma persists the vector store.",
    )

    # ---- Self-monitoring ---------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ---- Operational guards -----------------------------------------------
    max_incidents_per_minute: int = Field(
        default=30,
        description="Rate limit — beyond this alerts are forwarded raw with a note.",
    )
    fallback_on_llm_failure: bool = Field(
        default=True,
        description="If True, LLM failures still forward the raw alert to Slack.",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
