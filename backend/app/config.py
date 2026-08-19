from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_vision_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_dimension: int = 1024
    embedding_mode: str = "standard"
    llm_mock_mode: bool = True
    llm_disable_thinking: bool = True
    llm_timeout_seconds: float = 90.0
    image_generation_base_url: str = ""
    image_generation_api_key: str = ""
    image_generation_model: str = ""
    image_generation_timeout_seconds: float = 240.0
    image_generation_watermark: bool = False
    generation_max_attempts: int = 3
    max_upload_mb: int = 25
    auth_secret: str = "change-this-secret-in-production"
    access_token_hours: int = 24

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    upload_dir: str = "./uploads"
    database_url: str = "sqlite:///./commerce_agent.db"

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        path.mkdir(parents=True, exist_ok=True)
        (path / "images").mkdir(exist_ok=True)
        (path / "documents").mkdir(exist_ok=True)
        (path / "generated").mkdir(exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
