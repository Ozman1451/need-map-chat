"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Info, X } from "lucide-react";
import { useCallback, useState } from "react";
import { cn } from "@/lib/utils";

export interface ToastItem {
  id: string;
  kind: "error" | "info";
  text: string;
}

/** Tiny toast queue: newest last, max 4, auto-dismiss after 5 s, duplicates collapse. */
export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: string) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const toast = useCallback(
    (text: string, kind: ToastItem["kind"] = "error") => {
      const id = Math.random().toString(36).slice(2, 10);
      setToasts((ts) => [...ts.filter((t) => t.text !== text), { id, kind, text }].slice(-4));
      setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
  );
  return { toasts, toast, dismiss };
}

export function Toasts({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const Icon = t.kind === "error" ? AlertTriangle : Info;
          return (
            <motion.div
              key={t.id}
              layout
              role={t.kind === "error" ? "alert" : "status"}
              data-testid="toast"
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
              className={cn(
                "pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-card/95 px-3.5 py-2.5 text-sm shadow-lg backdrop-blur",
                t.kind === "error" ? "border-red-500/30" : "border-[#E94BA8]/30",
              )}
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", t.kind === "error" ? "text-red-400" : "text-[#E94BA8]")} />
              <p className="min-w-0 flex-1 leading-snug">{t.text}</p>
              <button type="button" onClick={() => onDismiss(t.id)} aria-label="Dismiss" className="rounded p-0.5 text-muted-foreground hover:text-foreground">
                <X className="size-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
