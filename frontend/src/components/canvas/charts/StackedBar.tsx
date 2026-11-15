"use client";

import { useMemo } from "react";
import { EChart } from "./EChart";
import { C, axis, base, clusterColor, pct, tooltip } from "@/lib/theme";
import type { Ask, ChartSpec } from "@/lib/types";

export function StackedBar({ chart, onAsk, height }: { chart: ChartSpec; onAsk: Ask; height?: number }) {
  const groups: string[] = chart.data.groups ?? [];
  const option = useMemo(() => {
    const series: { id: string; name: string; values: number[] }[] = chart.data.series ?? [];
    const counts: Record<string, number> = chart.data.counts ?? {};
    const groups: string[] = chart.data.groups ?? [];
    return {
      ...base,
      grid: { left: 8, right: 16, top: 8, bottom: 64, containLabel: true },
      tooltip: {
        ...tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow", shadowStyle: { color: "rgba(255,255,255,0.03)" } },
        valueFormatter: (v: number) => pct(v, 1),
      },
      legend: {
        type: "scroll",
        bottom: 0,
        icon: "circle",
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { color: C.muted, fontSize: 11 },
        pageIconColor: C.muted,
        pageTextStyle: { color: C.muted },
      },
      xAxis: { ...axis, type: "value", max: 1, axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v) } },
      yAxis: {
        ...axis,
        type: "category",
        inverse: true,
        data: groups,
        axisLabel: {
          ...axis.axisLabel,
          color: C.text,
          formatter: (g: string) => `${g}\n{n|${counts[g] ?? ""} comments}`,
          rich: { n: { color: C.muted, fontSize: 10, padding: [3, 0, 0, 0] } },
        },
      },
      series: series.map((s) => ({
        type: "bar",
        stack: "share",
        name: `${s.id} · ${s.name}`,
        clusterId: s.id,
        data: s.values,
        barWidth: "62%",
        itemStyle: { color: clusterColor(s.id), borderColor: C.surface, borderWidth: 1 },
        emphasis: { focus: "series" },
      })),
    };
  }, [chart.data]);
  return (
    <EChart
      option={option}
      height={height ?? Math.max(260, groups.length * 46 + 90)}
      onEvents={{
        click: (p) => {
          const id = /^([A-Z]\d+)/.exec(p?.seriesName ?? "")?.[1];
          if (id) onAsk(`Tell me about [${id}] in ${p.name}`);
        },
        legendselectchanged: (p, ec) => {
          ec.dispatchAction({ type: "legendSelect", name: p.name });
          const id = /^([A-Z]\d+)/.exec(p.name)?.[1];
          if (id) onAsk(`Tell me about [${id}]`);
        },
      }}
    />
  );
}
