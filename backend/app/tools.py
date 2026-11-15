"""Agent tools (stub; Phase 3). Each returns ToolResult {summary, charts}."""
from collections.abc import Callable

from .schemas import ToolResult

TOOLS: dict[str, Callable[..., ToolResult]] = {}
