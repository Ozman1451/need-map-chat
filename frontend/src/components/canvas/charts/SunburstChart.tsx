"use client";

import { useMemo } from "react";
import { EChart } from "./EChart";
import { C, base, clusterColor, lighten, pct, tooltip } from "@/lib/theme";
import type { Ask, ChartSpec } from "@/lib/types";

interface Node {
  id: string;
  name: string;
  value: number;
  share?: number;
  children?: Node[];
}

export function SunburstChart({ chart, onAsk, height }: { chart: ChartSpec; onAsk: Ask; height?: number }) {
  const root: Node = chart.data.root;
  const option = useMemo(() => {
    const color = clusterColor(root.id);
    const kids = root.children ?? [];
    const data = [
      {
        name: root.name,
        id: root.id,
        value: root.value,
        itemStyle: { color },
        label: { color: C.bg, fontWeight: 600 },
        children: kids.map((k, i) => ({
          name: k.name,
          id: k.id,
          value: k.value,
          share: k.share,
          itemStyle: { color: lighten(color, (0.7 * i) / Math.max(1, kids.length)) },
        })),
      },
    ];
    return {
      ...base,
      animationType: "expansion",
      animationDuration: 1000,
      animationEasing: "cubicOut",
      tooltip: {
        ...tooltip,
        formatter: (p: { data: Node }) =>
          `<b>${p.data.id}</b> ${p.data.name}<br/><span style="color:${C.muted}">${p.data.value} comments` +
          (p.data.share != null ? ` · ${pct(p.data.share)} of parent` : "") +
          "</span>",
      },
      series: [
        {
          type: "sunburst",
          data,
          radius: [0, "92%"],
          nodeClick: false,
          sort: undefined,
          itemStyle: { borderColor: C.surface, borderWidth: 2, borderRadius: 6 },
          emphasis: { focus: "ancestor", itemStyle: { shadowBlur: 20, shadowColor: color } },
          levels: [
            {},
            { r0: 0, r: "36%", label: { rotate: 0, fontSize: 13, width: 110, overflow: "break" } },
            {
              r0: "38%",
              r: "92%",
              label: { rotate: 0, color: C.bg, fontSize: 11, fontWeight: 500, minAngle: 14, width: 120, overflow: "break" },
            },
          ],
        },
      ],
    };
  }, [root]);

  return (
    <EChart
      option={option}
      height={height ?? 400}
      onEvents={{
        click: (p) => p?.data?.id && p.data.id !== root.id && onAsk(`Show me comments from [${p.data.id}]`),
      }}
    />
  );
}
