"use client";

import { useMemo } from "react";
import { EChart } from "./EChart";
import { C, base, clusterColor, tooltip } from "@/lib/theme";
import type { Ask, ChartSpec } from "@/lib/types";

interface Pt {
  id: string;
  x: number;
  y: number;
  cluster: string;
  text: string;
  highlight?: boolean;
}

const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);

export function ScatterEmbed({ chart, onAsk, height }: { chart: ChartSpec; onAsk: Ask; height?: number }) {
  const unusual = chart.meta?.highlight === "unusual";
  const option = useMemo(() => {
    const clusters: { id: string; name: string }[] = chart.data.clusters ?? [];
    const points: Pt[] = chart.data.points ?? [];
    const names = new Map(clusters.map((c) => [c.id, c.name]));
    const label = (id: string) => (names.has(id) ? `${id} · ${names.get(id)}` : id === "noise" ? "noise" : id);
    const groups = new Map<string, Pt[]>();
    for (const p of points) {
      const key = unusual && p.highlight ? "__unusual" : p.cluster;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(p);
    }
    const order = [...clusters.map((c) => c.id), ...[...groups.keys()].filter((k) => !names.has(k))];
    const series = order
      .filter((k) => groups.has(k))
      .map((k) => {
        const hot = k === "__unusual";
        const color = hot ? C.saffron : unusual ? "#3A3A4A" : clusterColor(k);
        return {
          type: "scatter",
          name: hot ? "Unusual" : label(k),
          clusterId: hot ? null : k,
          data: groups.get(k)!.map((p) => ({ value: [p.x, p.y], id: p.id, cluster: p.cluster, text: p.text })),
          symbolSize: hot ? 10 : unusual ? 4 : 6,
          z: hot ? 5 : 2,
          itemStyle: {
            color,
            opacity: hot ? 1 : unusual ? 0.55 : 0.9,
            shadowBlur: hot ? 16 : unusual ? 0 : 7,
            shadowColor: color,
          },
          emphasis: { scale: 1.8, itemStyle: { shadowBlur: 24, opacity: 1 } },
          large: false,
          animationDelay: (i: number) => Math.min(i * 0.4, 600),
        };
      });
    return {
      ...base,
      grid: { left: 8, right: 8, top: 8, bottom: 56 },
      xAxis: { show: false, scale: true },
      yAxis: { show: false, scale: true },
      tooltip: {
        ...tooltip,
        trigger: "item",
        formatter: (p: { data: { cluster: string; text: string }; color: string }) =>
          `<div style="display:flex;gap:6px;align-items:center;margin-bottom:4px;color:${C.muted};font-size:11px">` +
          `<span style="width:8px;height:8px;border-radius:9px;background:${clusterColor(p.data.cluster)}"></span>` +
          `${esc(label(p.data.cluster))}</div><div>${esc(p.data.text)}</div>`,
      },
      legend: {
        type: "scroll",
        bottom: 0,
        left: 0,
        right: 0,
        icon: "circle",
        itemWidth: 8,
        itemHeight: 8,
        itemGap: 14,
        textStyle: { color: C.muted, fontSize: 11 },
        pageTextStyle: { color: C.muted },
        pageIconColor: C.muted,
        pageIconInactiveColor: C.border,
        inactiveColor: C.muted,
      },
      series,
    };
  }, [chart.data, unusual]);

  const clusterFromName = (name: string) => /^([A-Z]\d+(?:\.\d+)?)/.exec(name)?.[1];

  return (
    <EChart
      option={option}
      height={height ?? 440}
      onEvents={{
        click: (p) => p?.data?.cluster && p.data.cluster !== "noise" && onAsk(`Tell me about [${p.data.cluster}]`),
        legendselectchanged: (p, ec) => {
          ec.dispatchAction({ type: "legendSelect", name: p.name }); // keep every series visible
          const id = clusterFromName(p.name);
          if (id) onAsk(`Tell me about [${id}]`);
        },
      }}
    />
  );
}
