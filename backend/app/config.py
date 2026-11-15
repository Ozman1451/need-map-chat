"""App settings. Reads env vars (and .env); values are never printed."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    dataset: str = "synthetic"
    gemini_chat_model: str = ""
    gemini_batch_model: str = ""
    gemini_embed_model: str = ""
    mock_llm: bool = False

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"

    @property
    def artifacts_dir(self) -> Path:
        return ROOT / "artifacts"


settings = Settings()
