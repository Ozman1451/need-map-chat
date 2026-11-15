"use client";

import { motion } from "framer-motion";
import { Check, Loader2, X } from "lucide-react";
import type { TraceStep } from "@/lib/types";

const LABEL: Record<string, string> = {
  get_overview: "Counting comments and posts",
  get_need_clusters: "Clustering comments",
  drill_down_cluster: "Splitting the need into sub-needs",
  sample_comments: "Pulling example comments",
  get_unusual_comments: "Finding unusual comments",
  need_share_by: "Comparing need shares",
  compare_algorithms: "Scoring clustering algorithms",
};

function argText(args: Record<string, unknown>) {
  const parts = Object.entries(args)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => (k === "cluster_id" ? `[${v}]` : k === "algo" ? String(v) : `${v}`));
  return parts.length ? parts.join(" · ") : "";
}

export function ToolTrace({ steps }: { steps: TraceStep[] }) {
  return (
    <ol className="mb-2 space-y-1" data-testid="tool-trace">
      {steps.map((s, i) => (
        <motion.li
          key={i}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-2 text-xs text-muted-foreground"
        >
          <span className="relative flex size-4 items-center justify-center">
            {s.status === "running" && <Loader2 className="size-3.5 animate-spin text-[#F5A524]" />}
            {s.status === "done" && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 500, damping: 22 }}
                className="flex size-4 items-center justify-center rounded-full bg-gradient-to-br from-[#E94BA8] to-[#F5A524]"
              >
                <Check className="size-2.5 text-black" strokeWidth={3.5} />
              </motion.span>
            )}
            {s.status === "error" && <X className="size-3.5 text-red-400" />}
          </span>
          <span className={s.status === "done" ? "text-foreground/80" : ""}>
            {LABEL[s.tool] ?? s.tool}
            {s.status === "running" ? "…" : ""}
          </span>
          {argText(s.args) && <span className="font-mono text-[10px] text-muted-foreground/70">{argText(s.args)}</span>}
        </motion.li>
      ))}
    </ol>
  );
}
