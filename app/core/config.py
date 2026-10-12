"""Application configuration."""
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

    # auto uses xAI when XAI_API_KEY is set, and a local hashing embedding otherwise.
    embedding_provider: str = "auto"
    embedding_model: str = "v1"
    embedding_dimensions: int = 256
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"

    llm_provider: str = "xai"
    llm_model: str = "grok-4.7"
    openai_api_key: str = ""

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "underwriting-intelligence-agent"


settings = Settings()
