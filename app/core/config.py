"""Application configuration."""
import os
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Underwriting Intelligence Agent"
    app_env: str = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = "postgresql://postgres:postgres@localhost:5433/underwriting_agent"
    upload_dir: str = "data/uploads"

    # auto prefers OpenAI when OPENAI_API_KEY is set, then xAI, then a local hashing embedding.
    embedding_provider: str = "auto"
    embedding_model: str = "v1"
    embedding_dimensions: int = 256
    openai_embedding_model: str = "text-embedding-3-small"
    # Character window used when one policy section is longer than one chunk.
    # Overlap must stay smaller than the window. boundary_margin of 0 cuts on
    # the exact character; a positive margin prefers the nearest space.
    chunk_window_size: int = 900
    chunk_overlap: int = 150
    chunk_boundary_margin: int = 40
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    # Retrieval judge only. The investigation supervisor and specialists stay on OpenAI.
    xai_eval_model: str = "grok-4.7"
    retrieval_semantic_weight: float = 0.7
    retrieval_lexical_weight: float = 0.3

    # Agent chat completions. OpenAI only. These ids are not the embedding model.
    # gpt-5.6-sol reasoning effort defaults to medium on the OpenAI side.
    # gpt-5.4-mini reasoning effort defaults to none. Do not pass reasoning_effort
    # unless the installed client requires the parameter, and do not raise the
    # supervisor above medium.
    llm_provider: str = "openai"
    llm_model: str = "gpt-5.6-sol"
    llm_specialist_model: str = "gpt-5.4-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    investigation_agent_enabled: bool = False

    # Host port 5001: macOS AirPlay already listens on 5000.
    mlflow_tracking_uri: str = "http://127.0.0.1:5001"
    mlflow_experiment: str = "underwriting-intelligence-agent"
    mlflow_tracing_enabled: bool = True

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "underwriting-intelligence-agent"


settings = Settings()


def _under_pytest() -> bool:
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def reload_settings() -> Settings:
    """Re-read `.env` and the process environment into the shared settings object.

    Modules keep `from app.core.config import settings`, so this updates that
    object in place. Pytest keeps the values a fixture already set.
    """
    if _under_pytest():
        return settings
    fresh = Settings()
    for name in Settings.model_fields:
        setattr(settings, name, getattr(fresh, name))
    return settings
