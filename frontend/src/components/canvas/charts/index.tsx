"use client";

import type { Ask, ChartSpec } from "@/lib/types";
import { ClusterList } from "./ClusterList";
import { CommentCards } from "./CommentCards";
import { KpiTiles } from "./KpiTiles";
import { LineChart } from "./LineChart";
import { MetricsTable } from "./MetricsTable";
import { ScatterEmbed } from "./ScatterEmbed";
import { StackedBar } from "./StackedBar";
import { SunburstChart } from "./SunburstChart";

/** Render by chart.type only (SPEC §6.1). `expanded` gives ECharts cards more height. */
export function ChartBody({ chart, onAsk, expanded }: { chart: ChartSpec; onAsk: Ask; expanded?: boolean }) {
  const h = expanded ? 680 : undefined;
  switch (chart.type) {
    case "kpi_tiles":
      return <KpiTiles chart={chart} onAsk={onAsk} />;
    case "scatter_embed":
      return <ScatterEmbed chart={chart} onAsk={onAsk} height={h} />;
    case "cluster_list":
      return <ClusterList chart={chart} onAsk={onAsk} />;
    case "sunburst":
      return <SunburstChart chart={chart} onAsk={onAsk} height={h} />;
    case "comment_cards":
      return <CommentCards chart={chart} onAsk={onAsk} />;
    case "stacked_bar":
      return <StackedBar chart={chart} onAsk={onAsk} height={h} />;
    case "metrics_table":
      return <MetricsTable chart={chart} />;
    case "line":
      return <LineChart chart={chart} height={h} />;
    default:
      return <pre className="text-xs text-muted-foreground">unsupported chart: {String((chart as ChartSpec).type)}</pre>;
  }
}
