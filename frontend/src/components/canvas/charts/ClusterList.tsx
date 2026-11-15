"use client";

import { motion } from "framer-motion";
import { GitFork, MessageSquareText } from "lucide-react";
import { ClusterChip } from "@/components/ClusterChip";
import { clusterColor, pct } from "@/lib/theme";
import type { Ask, ChartSpec } from "@/lib/types";

interface Row {
  id: string;
  name: string;
  description: string;
  action: string;
  size: number;
  share: number;
  has_children: boolean;
}

export function ClusterList({ chart, onAsk }: { chart: ChartSpec; onAsk: Ask }) {
  const rows: Row[] = chart.data.clusters ?? [];
  const max = Math.max(...rows.map((r) => r.share), 0.0001);
  return (
    <ul className="divide-y divide-border/60">
      {rows.map((r, i) => {
        const color = clusterColor(r.id);
        return (
          <motion.li
            key={r.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.03 }}
            className="group grid grid-cols-[auto_1fr_auto] items-start gap-x-3 py-2.5"
          >
            <ClusterChip id={r.id} onClick={() => onAsk(`Tell me about [${r.id}]`)} className="mt-0.5" />
            <div className="min-w-0">
              <div className="flex items-baseline justify-between gap-3">
                <span className="truncate text-sm font-medium">{r.name}</span>
                <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                  {pct(r.share, 1)} · {r.size.toLocaleString()}
                </span>
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/5">
                <motion.div
                  className="h-full rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${(r.share / max) * 100}%` }}
                  transition={{ duration: 0.7, delay: 0.1 + i * 0.03, ease: "easeOut" }}
                  style={{ background: `linear-gradient(90deg, ${color}aa, ${color})`, boxShadow: `0 0 8px ${color}66` }}
                />
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                <span className="text-foreground/80">→ </span>
                {r.action}
              </p>
            </div>
            <div className="flex gap-1 opacity-60 transition group-hover:opacity-100">
              <IconBtn label="Example comments" onClick={() => onAsk(`Show me comments from [${r.id}]`)}>
                <MessageSquareText className="size-3.5" />
              </IconBtn>
              {r.has_children && (
                <IconBtn label="Split into sub-needs" onClick={() => onAsk(`Split [${r.id}] further`)}>
                  <GitFork className="size-3.5" />
                </IconBtn>
              )}
            </div>
          </motion.li>
        );
      })}
    </ul>
  );
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="rounded-md border border-border p-1.5 text-muted-foreground transition hover:border-white/20 hover:text-foreground"
    >
      {children}
    </button>
  );
}
