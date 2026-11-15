"use client";

import { ClusterChip } from "@/components/ClusterChip";
import { pct } from "@/lib/theme";
import type { Ask, ChartSpec } from "@/lib/types";

interface Tile {
  key: string;
  label: string;
  value: number | string;
  format?: string;
  hint?: string;
  breakdown?: Record<string, number>;
  cluster?: string;
  share?: number;
}

export function KpiTiles({ chart, onAsk }: { chart: ChartSpec; onAsk: Ask }) {
  const tiles: Tile[] = chart.data.tiles ?? [];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {tiles.map((t) => (
        <div key={t.key} className="rounded-xl border border-border/80 bg-white/[0.02] p-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{t.label}</div>
          {typeof t.value === "number" ? (
            <div className="mt-1 font-mono text-2xl font-semibold tabular-nums">
              {t.format === "percent" ? pct(t.value, 1) : t.value.toLocaleString()}
            </div>
          ) : (
            <div className="mt-1 line-clamp-2 text-sm font-medium leading-snug">{t.value}</div>
          )}
          {t.hint && <div className="mt-1 text-xs text-muted-foreground">{t.hint}</div>}
          {t.breakdown && (
            <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-white/5">
              {Object.entries(t.breakdown).map(([k, v], i) => (
                <div
                  key={k}
                  title={`${k} ${pct(v)}`}
                  style={{ width: pct(v, 2), background: ["#E94BA8", "#F5A524", "#4CC9F0", "#7BE495"][i % 4] }}
                />
              ))}
            </div>
          )}
          {t.breakdown && (
            <div className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
              {Object.entries(t.breakdown)
                .slice(0, 3)
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span>{k}</span>
                    <span className="font-mono">{pct(v)}</span>
                  </div>
                ))}
            </div>
          )}
          {t.cluster && (
            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <ClusterChip id={t.cluster} onClick={() => onAsk(`Tell me about [${t.cluster}]`)} />
              {t.share != null && <span className="font-mono">{pct(t.share)}</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
