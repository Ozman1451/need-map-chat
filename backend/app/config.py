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
    gemini_api_key: str = ""
    gemini_rpm: int = 12  # client-side requests/min per model (free tier is 15)
    mock_llm: bool = False
    cache_root: str = ""  # override (tests); default data/cache

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"

    @property
    def cache_dir(self) -> Path:
        return Path(self.cache_root) if self.cache_root else self.data_dir / "cache"

    @property
    def artifacts_dir(self) -> Path:
        return ROOT / "artifacts"


settings = Settings()
