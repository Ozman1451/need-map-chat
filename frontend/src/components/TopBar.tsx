"use client";

import { Database, FlaskConical, Play, Square } from "lucide-react";
import { Skeleton } from "@/components/Skeleton";
import { cn } from "@/lib/utils";
import type { Filters, Manifest } from "@/lib/types";

const ALGOS = [
  { id: "kmeans", label: "K-Means" },
  { id: "ward", label: "Ward" },
  { id: "dbscan", label: "DBSCAN" },
  { id: "gmm", label: "GMM" },
];

export function TopBar({
  manifest,
  filters,
  onFilters,
  onDataset,
  demo,
  onDemo,
}: {
  manifest: Manifest | null;
  filters: Filters;
  onFilters: (f: Filters) => void;
  onDataset: (name: string) => void;
  demo: boolean;
  onDemo: () => void;
}) {
  const brands = manifest?.options.brand ?? [];
  const campaigns = manifest?.options.campaign ?? [];
  const datasets = manifest?.datasets ?? {};
  const set = (p: Partial<Filters>) => onFilters({ ...filters, ...p });

  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border bg-background/80 px-5 py-3 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="size-2.5 rounded-full shadow-[0_0_12px_#E94BA8]" style={{ backgroundImage: "var(--accent-gradient)" }} />
        <h1 className="bg-clip-text text-lg font-semibold tracking-tight text-transparent" style={{ backgroundImage: "var(--accent-gradient)" }}>
          Need Map
        </h1>
      </div>

      <div className="flex flex-wrap items-center gap-1">
        {!manifest &&
          [14, 20, 18, 24, 16].map((w, i) => <Skeleton key={i} className="h-6 rounded-full" style={{ width: `${w * 4}px` }} />)}
        {manifest && [null, ...brands].map((b) => (
          <button
            key={b ?? "all"}
            type="button"
            onClick={() => set({ brand: b })}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition",
              filters.brand === b
                ? "border-[#E94BA8]/50 bg-[#E94BA8]/15 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {b ?? "All"}
          </button>
        ))}
      </div>

      <select
        value={filters.campaign ?? ""}
        onChange={(e) => set({ campaign: e.target.value || null })}
        aria-label="Campaign"
        className="rounded-lg border border-border bg-card px-2.5 py-1 text-xs text-foreground outline-none focus:border-[#E94BA8]/50"
      >
        <option value="">All campaigns</option>
        {campaigns.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      <div className="flex rounded-lg border border-border bg-card p-0.5" role="radiogroup" aria-label="Algorithm">
        {ALGOS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="radio"
            aria-checked={filters.algo === a.id}
            onClick={() => set({ algo: a.id })}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs transition",
              filters.algo === a.id ? "bg-white/10 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {a.label}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={onDemo}
        disabled={!manifest}
        data-testid="demo-button"
        title={demo ? "Stop the demo" : "Send the five prompt chips one by one"}
        className={cn(
          "ml-auto flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition disabled:opacity-40",
          demo
            ? "border-[#E94BA8]/50 bg-[#E94BA8]/15 text-foreground"
            : "border-border bg-card text-muted-foreground hover:text-foreground",
        )}
      >
        {demo ? <Square className="size-3.5" /> : <Play className="size-3.5" />}
        {demo ? "Stop demo" : "Demo"}
      </button>

      <div className="flex rounded-lg border border-border bg-card p-0.5 text-xs">
        {[
          { id: "real", label: "Real", Icon: Database },
          { id: "synthetic", label: "Benchmark", Icon: FlaskConical },
        ].map(({ id, label, Icon }) => {
          const info = datasets[id];
          const active = manifest?.dataset === id;
          return (
            <button
              key={id}
              type="button"
              disabled={!info}
              onClick={() => !active && onDataset(id)}
              title={info ? `${info.comments ?? "?"} comments` : `no artifacts for ${id} yet`}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 transition disabled:cursor-not-allowed disabled:opacity-40",
                active ? "bg-white/10 text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {label}
              <span className="font-mono text-[10px] text-muted-foreground">{info?.comments?.toLocaleString() ?? "–"}</span>
            </button>
          );
        })}
      </div>
    </header>
  );
}
