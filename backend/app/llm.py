"""Sole Gemini gateway (stub). Phase 1: check current google-genai SDK docs first;
add sha1 disk cache, tenacity retry on 429/5xx, MOCK_LLM support."""


def tag_batch(comments: list[dict]) -> list[dict]:
    raise NotImplementedError


def embed(texts: list[str]) -> list[list[float]]:
    raise NotImplementedError


def name_cluster(payload: dict) -> dict:
    raise NotImplementedError


def chat(messages: list[dict], tools: list[dict]) -> dict:
    raise NotImplementedError
