"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Maximize2, Minimize2, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ChartBody } from "./charts";
import type { Ask, CanvasItem } from "@/lib/types";

export function Canvas({ items, onClose, onAsk }: { items: CanvasItem[]; onClose: (id: string) => void; onAsk: Ask }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(null);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);
  const big = items.find((i) => i.chart.id === expanded);

  if (!items.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
        <div className="rounded-2xl border border-border bg-card p-4 shadow-[0_0_40px_rgba(233,75,168,0.12)]">
          <Sparkles className="size-6 text-[#E94BA8]" />
        </div>
        <p className="text-sm">Charts from your questions appear here.</p>
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-col gap-4" data-testid="canvas">
        <AnimatePresence initial={false}>
          {items.map((it) => (
            <motion.section
              key={it.chart.id}
              layout
              data-chart-type={it.chart.type}
              initial={{ opacity: 0, y: 16, scale: 0.99 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.15 } }}
              transition={{ duration: 0.35, ease: "easeOut", delay: it.index * 0.06 }}
              className={`rounded-2xl border border-border bg-card/90 p-4 ${
                it.chart.type === "scatter_embed" ? "shadow-[0_0_60px_-20px_rgba(233,75,168,0.35)]" : ""
              }`}
            >
              <Header item={it} onExpand={() => setExpanded(it.chart.id)} onClose={() => onClose(it.chart.id)} />
              <ChartBody chart={it.chart} onAsk={onAsk} />
            </motion.section>
          ))}
        </AnimatePresence>
      </div>
      <AnimatePresence>
        {big && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setExpanded(null)}
          >
            <motion.section
              initial={{ scale: 0.96 }}
              animate={{ scale: 1 }}
              className="max-h-full w-full max-w-6xl overflow-auto rounded-2xl border border-border bg-card p-5"
              onClick={(e) => e.stopPropagation()}
            >
              <Header item={big} expanded onExpand={() => setExpanded(null)} onClose={() => setExpanded(null)} />
              <ChartBody chart={big.chart} onAsk={(t) => (setExpanded(null), onAsk(t))} expanded />
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function Header({
  item,
  expanded,
  onExpand,
  onClose,
}: {
  item: CanvasItem;
  expanded?: boolean;
  onExpand: () => void;
  onClose: () => void;
}) {
  const { chart } = item;
  return (
    <header className="mb-3 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="truncate text-[15px] font-semibold tracking-tight">{chart.title}</h3>
        {chart.subtitle && <p className="truncate text-xs text-muted-foreground">{chart.subtitle}</p>}
      </div>
      <div className="flex shrink-0 gap-1 text-muted-foreground">
        <button type="button" onClick={onExpand} aria-label={expanded ? "Collapse" : "Expand"} className="rounded-md p-1.5 hover:bg-white/5 hover:text-foreground">
          {expanded ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
        </button>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 hover:bg-white/5 hover:text-foreground">
          <X className="size-3.5" />
        </button>
      </div>
    </header>
  );
}
