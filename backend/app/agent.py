"""Gemini function-calling agent loop (stub; Phase 3)."""
from collections.abc import Iterator

from .schemas import SSEEvent


def run_agent(history: list[dict]) -> Iterator[SSEEvent]:
    raise NotImplementedError
