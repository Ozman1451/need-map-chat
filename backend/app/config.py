"""App settings. Reads env vars (and .env); values are never printed."""
import os
from pathlib import Path

# Keep Hugging Face model downloads inside the conda env (must run before any HF import).
if os.environ.get("CONDA_PREFIX"):
    os.environ.setdefault("HF_HOME", f"{os.environ['CONDA_PREFIX']}/.cache/huggingface")

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    dataset: str = "synthetic"
    gemini_chat_model: str = ""
    gemini_batch_model: str = ""
    gemini_embed_model: str = ""
    gemini_api_key: str = ""
    embed_backend: str = "local"  # local (sentence-transformers, CPU) | gemini
    local_embed_model: str = "intfloat/multilingual-e5-base"
    gemini_rpm: int = 12  # client-side requests/min per generate model (free tier is 15)
    gemini_embed_rpm: int = 100  # embedding model: free tier 100 RPM, counted per text
    gemini_embed_tpm: int = 25000  # embedding model: free tier 30K TPM; stay under
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
