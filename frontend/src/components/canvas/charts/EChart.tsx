"use client";

import dynamic from "next/dynamic";
import type { CSSProperties } from "react";

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse rounded-lg bg-white/[0.02]" />,
});

/* eslint-disable @typescript-eslint/no-explicit-any */
export function EChart({
  option,
  height = 320,
  onEvents,
  style,
}: {
  option: any;
  height?: number | string;
  onEvents?: Record<string, (p: any, chart: any) => void>;
  style?: CSSProperties;
}) {
  return (
    <ReactECharts
      option={option}
      onEvents={onEvents}
      notMerge
      opts={{ renderer: "canvas" }}
      style={{ height, width: "100%", ...style }}
    />
  );
}
