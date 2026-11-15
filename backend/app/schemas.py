"""Shared pydantic schemas (SPEC §6.1, §6.4)."""
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ChartType = Literal[
    "kpi_tiles", "scatter_embed", "cluster_list", "sunburst",
    "comment_cards", "stacked_bar", "metrics_table", "line",
]


class ChartSpec(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ChartType
    title: str = ""
    subtitle: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    charts: list[ChartSpec] = Field(default_factory=list)


EventType = Literal["tool_start", "tool_result", "text_delta", "done", "error"]


class SSEEvent(BaseModel):
    event: EventType
    data: dict[str, Any] = Field(default_factory=dict)
