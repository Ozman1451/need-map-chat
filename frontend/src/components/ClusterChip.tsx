"use client";

import { clusterColor } from "@/lib/theme";
import { cn } from "@/lib/utils";

export function ClusterChip({ id, onClick, className }: { id: string; onClick?: () => void; className?: string }) {
  const color = clusterColor(id);
  return (
    <button
      type="button"
      onClick={onClick}
      title={`Tell me about [${id}]`}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-px align-baseline font-mono text-[11px] font-medium leading-4 transition hover:brightness-125",
        className,
      )}
      style={{ color, borderColor: `${color}55`, background: `${color}14`, boxShadow: `0 0 10px ${color}22` }}
    >
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {id}
    </button>
  );
}
