export type ChartType =
  | "kpi_tiles"
  | "scatter_embed"
  | "cluster_list"
  | "sunburst"
  | "comment_cards"
  | "stacked_bar"
  | "metrics_table"
  | "line";

/* eslint-disable @typescript-eslint/no-explicit-any */
export interface ChartSpec {
  id: string;
  type: ChartType;
  title: string;
  subtitle: string;
  data: Record<string, any>;
  meta: Record<string, any>;
}

export interface ToolResult {
  summary: Record<string, any>;
  charts: ChartSpec[];
}

export type SSEEvent =
  | { event: "tool_start"; data: { tool: string; args: Record<string, unknown> } }
  | { event: "tool_result"; data: { tool: string; summary: Record<string, unknown>; charts: ChartSpec[] } }
  | { event: "text_delta"; data: { text: string } }
  | { event: "done"; data: Record<string, never> }
  | { event: "error"; data: { message: string } };

export interface TraceStep {
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: TraceStep[];
  error?: string;
  pending?: boolean;
}

export interface Manifest {
  dataset: string;
  manifest: Record<string, any>;
  datasets: Record<string, { comments?: number; is_synthetic?: boolean }>;
  options: { brand: string[]; campaign: string[]; content_type: string[] };
  algos: string[];
}

export interface Filters {
  brand: string | null;
  campaign: string | null;
  algo: string;
}

/** Canvas item: a chart plus a batch key so cards from one tool call stagger together. */
export interface CanvasItem {
  chart: ChartSpec;
  batch: number;
  index: number;
}

export type Ask = (text: string) => void;
