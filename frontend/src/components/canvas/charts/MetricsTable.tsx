"use client";

import type { ChartSpec } from "@/lib/types";

const LABEL: Record<string, string> = {
  algo: "Algorithm",
  k: "k",
  silhouette: "Silhouette ↑",
  davies_bouldin: "Davies–Bouldin ↓",
  calinski_harabasz: "Calinski–H ↑",
  stability_ari: "Stability ARI ↑",
  ari_true: "ARI vs truth ↑",
  nmi_true: "NMI vs truth ↑",
  noise_share: "Noise",
};
const ALGO: Record<string, string> = { kmeans: "K-Means", ward: "Ward", dbscan: "DBSCAN", gmm: "GMM" };

function fmt(col: string, v: unknown) {
  if (v == null) return "–";
  if (typeof v !== "number") return ALGO[String(v)] ?? String(v);
  if (col === "k") return String(v);
  if (col === "noise_share") return `${(v * 100).toFixed(1)}%`;
  if (col === "calinski_harabasz") return v.toFixed(0);
  return v.toFixed(3);
}

export function MetricsTable({ chart }: { chart: ChartSpec }) {
  const cols: string[] = chart.data.columns ?? [];
  const rows: Record<string, unknown>[] = chart.data.rows ?? [];
  const best: Record<string, string> = chart.data.best ?? {};
  const shown = cols.filter((c) => rows.some((r) => r[c] != null));
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              {shown.map((c) => (
                <th key={c} className="whitespace-nowrap px-2 py-2 font-medium first:pl-0">
                  {LABEL[c] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r.algo)} className="border-b border-border/50 last:border-0">
                {shown.map((c) => {
                  const win = best[c] === r.algo;
                  return (
                    <td
                      key={c}
                      className={`whitespace-nowrap px-2 py-2 first:pl-0 ${c === "algo" ? "font-medium" : "font-mono tabular-nums"}`}
                    >
                      {win ? (
                        <span className="rounded-md bg-gradient-to-r from-[#E94BA8]/20 to-[#F5A524]/20 px-1.5 py-0.5 text-[#F5A524]">
                          {fmt(c, r[c])}
                        </span>
                      ) : (
                        <span className={c === "algo" ? "" : "text-foreground/80"}>{fmt(c, r[c])}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {chart.meta?.note && <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{chart.meta.note}</p>}
    </div>
  );
}
