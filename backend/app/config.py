from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives in the project root, two levels above this file
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    database_url: str = ""


settings = Settings()