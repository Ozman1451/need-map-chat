import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No network in tests: mock LLM + throwaway cache dir."""
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(settings, "cache_root", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "gemini_batch_model", "test-batch")
    monkeypatch.setattr(settings, "gemini_embed_model", "test-embed")
