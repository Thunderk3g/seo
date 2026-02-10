import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API Keys
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4-turbo-preview"

    # Server Config
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Observability
    LOG_LEVEL: str = "INFO"
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_PROJECT: str = "multi-agent-backend"

settings = Settings()
