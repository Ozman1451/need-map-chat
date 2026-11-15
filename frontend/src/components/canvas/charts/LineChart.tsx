"use client";

import { useMemo } from "react";
import { EChart } from "./EChart";
import { C, axis, base, tooltip } from "@/lib/theme";
import type { ChartSpec } from "@/lib/types";

const COLORS = [C.magenta, C.saffron, "#4CC9F0"];

export function LineChart({ chart, height }: { chart: ChartSpec; height?: number }) {
  const d = chart.data;
  const option = useMemo(() => {
    const xs: number[] = d.x ?? [];
    const marks: { series: string; x: number | null }[] = d.marks ?? [];
    return {
      ...base,
      grid: { left: 8, right: 16, top: 28, bottom: 36, containLabel: true },
      tooltip: { ...tooltip, trigger: "axis", valueFormatter: (v: number) => (v == null ? "–" : v.toFixed(3)) },
      legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 10, itemHeight: 3, textStyle: { color: C.muted, fontSize: 11 } },
      xAxis: { ...axis, type: "category", data: xs.map(String), name: d.x_label, nameLocation: "middle", nameGap: 26, boundaryGap: false },
      yAxis: { ...axis, type: "value", name: d.y_label, scale: true, nameTextStyle: { ...axis.nameTextStyle, align: "left" } },
      series: (d.series ?? []).map((s: { name: string; values: (number | null)[] }, i: number) => {
        const color = COLORS[i % COLORS.length];
        const mark = marks.find((m) => m.series === s.name && m.x != null);
        return {
          type: "line",
          name: s.name,
          data: s.values,
          smooth: 0.3,
          connectNulls: true,
          symbol: "circle",
          symbolSize: 5,
          lineStyle: { width: 2.5, color, shadowBlur: 10, shadowColor: color },
          itemStyle: { color },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: `${color}33` }, { offset: 1, color: `${color}00` }],
            },
          },
          markLine: mark
            ? {
                symbol: "none",
                silent: true,
                lineStyle: { color, type: "dashed", opacity: 0.7 },
                label: { color, formatter: `chosen ${mark.x}`, fontSize: 10 },
                data: [{ xAxis: String(mark.x) }],
              }
            : undefined,
        };
      }),
    };
  }, [d]);
  return <EChart option={option} height={height ?? 260} />;
}
