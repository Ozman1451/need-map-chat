import numpy as np
import pytest

from app import embeddings, llm
from app.config import settings


class FakeST:
    def __init__(self):
        self.calls = []

    def encode(self, texts, batch_size, normalize_embeddings, show_progress_bar):
        self.calls.append({"texts": texts, "batch_size": batch_size, "norm": normalize_embeddings})
        rng = np.random.default_rng(len(texts))
        v = rng.standard_normal((len(texts), 768))
        return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setattr(settings, "mock_llm", False)


def test_local_backend_prefix_batch_norm_and_cache(live, monkeypatch):
    fake = FakeST()
    monkeypatch.setattr(settings, "embed_backend", "local")
    monkeypatch.setattr(embeddings, "_load_model", lambda: fake)
    texts = [f"price plz {i}" for i in range(600)]
    v = embeddings.embed(texts, dataset="t")
    assert v.shape == (600, 768) and v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    assert [len(c["texts"]) for c in fake.calls] == [512, 88]  # cached per 512-text chunk
    assert all(t.startswith("query: ") for c in fake.calls for t in c["texts"])
    assert all(c["batch_size"] == 64 and c["norm"] for c in fake.calls)
    again = embeddings.embed(texts, dataset="t")
    assert len(fake.calls) == 2 and np.array_equal(v, again)  # second run: cache only


def test_gemini_backend_delegates_to_llm(live, monkeypatch):
    monkeypatch.setattr(settings, "embed_backend", "gemini")
    seen = []
    monkeypatch.setattr(llm, "embed", lambda texts, **kw: seen.append(kw) or np.ones((len(texts), 768), np.float32))
    monkeypatch.setattr(embeddings, "_load_model", lambda: pytest.fail("local model must not load"))
    assert embeddings.embed(["a", "b"], dataset="t").shape == (2, 768)
    assert seen == [{"dataset": "t", "task_type": "CLUSTERING", "dim": 768}]


def test_mock_mode_never_loads_model(monkeypatch):
    monkeypatch.setattr(embeddings, "_load_model", lambda: pytest.fail("no model in mock mode"))
    v = embeddings.embed(["x", "y", "x"], dataset="t")
    assert np.allclose(np.linalg.norm(v, axis=1), 1) and np.array_equal(v[0], v[2])


def test_unknown_backend_rejected(live, monkeypatch):
    monkeypatch.setattr(settings, "embed_backend", "openai")
    with pytest.raises(ValueError):
        embeddings.embed(["a"], dataset="t")
