"""Embedding gateway: local sentence-transformers (default, CPU) or Gemini (EMBED_BACKEND=gemini).

Local: LOCAL_EMBED_MODEL (multilingual-e5-base), every text prefixed "query: ", batch 64,
normalised; disk cache per 512-text chunk under data/cache/<dataset>/embed_local/.
MOCK_LLM=1 → deterministic fake vectors for both backends (no model download, no network).
"""
from __future__ import annotations

import numpy as np

from . import llm
from .config import settings

PREFIX = "query: "
BATCH = 64
CHUNK = 512

_model = None


def backend() -> str:
    return settings.embed_backend.lower()


def model_label() -> str:
    if llm.is_mock():
        return "mock"
    return settings.local_embed_model if backend() == "local" else llm.model_name("embed")


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.local_embed_model, device="cpu")
    return _model


def _encode_local(texts: list[str]) -> np.ndarray:
    return np.asarray(_load_model().encode([PREFIX + t for t in texts], batch_size=BATCH,
                                           normalize_embeddings=True, show_progress_bar=False),
                      dtype=np.float32)


def _local(texts: list[str], dataset: str) -> np.ndarray:
    model = settings.local_embed_model
    parts = []
    for i in range(0, len(texts), CHUNK):
        chunk = texts[i:i + CHUNK]
        path = llm._cache_path(dataset, "embed_local", llm.cache_key(model, PREFIX, {"texts": chunk}), "npy")
        if path.exists():
            parts.append(np.load(path))
            continue
        arr = _encode_local(chunk)
        llm._atomic_write(path, lambda p: np.save(open(p, "wb"), arr))
        parts.append(arr)
    return np.concatenate(parts)


def embed(texts: list[str], *, dataset: str, dim: int = 768) -> np.ndarray:
    """→ float32 (len(texts), d), L2-normalised."""
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)
    if llm.is_mock():
        vecs = llm.mock_vectors(texts, dim)
    elif backend() == "gemini":
        return llm.embed(texts, dataset=dataset, task_type="CLUSTERING", dim=dim)
    elif backend() == "local":
        vecs = _local(texts, dataset)
    else:
        raise ValueError(f"EMBED_BACKEND must be local or gemini, got {settings.embed_backend!r}")
    vecs = vecs.astype(np.float32)
    return vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)
