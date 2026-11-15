"use client";

import { motion } from "framer-motion";
import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MessageText } from "./MessageText";
import { ToolTrace } from "./ToolTrace";
import type { Ask, ChatMessage } from "@/lib/types";

export const PROMPTS = [
  "What does my audience want?",
  "Split the biggest need further",
  "Show me the weird comments",
  "How do needs change in 12.12 vs Eid?",
  "Which clustering algorithm fits best?",
];

export function Chat({
  messages,
  busy,
  onAsk,
  onStop,
}: {
  messages: ChatMessage[];
  busy: boolean;
  onAsk: Ask;
  onStop: () => void;
}) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const submit = () => {
    const t = draft.trim();
    if (!t || busy) return;
    setDraft("");
    onAsk(t);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {messages.length === 0 ? (
          <Empty onAsk={onAsk} />
        ) : (
          <div className="space-y-5">
            {messages.map((m) =>
              m.role === "user" ? (
                <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md border border-[#E94BA8]/25 bg-gradient-to-br from-[#E94BA8]/15 to-[#F5A524]/10 px-3.5 py-2 text-sm">
                    {m.content}
                  </div>
                </motion.div>
              ) : (
                <motion.div key={m.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="pr-6" data-testid="assistant-msg">
                  {m.steps && m.steps.length > 0 && <ToolTrace steps={m.steps} />}
                  {m.content ? (
                    <MessageText text={m.content} onAsk={onAsk} />
                  ) : (
                    m.pending && !m.steps?.length && <Dots />
                  )}
                  {m.error && (
                    <p className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{m.error}</p>
                  )}
                </motion.div>
              ),
            )}
            {messages.length > 0 && !busy && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {PROMPTS.filter((p) => !messages.some((m) => m.content === p))
                  .slice(0, 3)
                  .map((p) => (
                    <PromptChip key={p} text={p} onClick={() => onAsk(p)} small />
                  ))}
              </div>
            )}
          </div>
        )}
        <div ref={end} />
      </div>
      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2 focus-within:border-[#E94BA8]/50 focus-within:shadow-[0_0_0_3px_rgba(233,75,168,0.12)]">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Ask about your audience… (English or Roman Urdu)"
            className="max-h-32 min-h-6 flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {busy ? (
            <button type="button" onClick={onStop} aria-label="Stop" className="rounded-lg bg-white/10 p-1.5 hover:bg-white/15">
              <Square className="size-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!draft.trim()}
              aria-label="Send"
              className="rounded-lg p-1.5 text-black transition disabled:opacity-30"
              style={{ backgroundImage: "var(--accent-gradient)" }}
            >
              <ArrowUp className="size-4" strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Empty({ onAsk }: { onAsk: Ask }) {
  return (
    <div className="flex h-full flex-col justify-center gap-6 py-10">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">
          What does your{" "}
          <span className="bg-clip-text text-transparent" style={{ backgroundImage: "var(--accent-gradient)" }}>
            audience
          </span>{" "}
          want?
        </h2>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          Ask in plain words. I cluster Instagram comments on Sapphire, Khaadi and Gul Ahmed lawn posts and show you the
          needs behind them.
        </p>
      </div>
      <div className="flex flex-col items-start gap-2">
        {PROMPTS.map((p, i) => (
          <motion.div key={p} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + i * 0.06 }}>
            <PromptChip text={p} onClick={() => onAsk(p)} />
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function PromptChip({ text, onClick, small }: { text: string; onClick: () => void; small?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="prompt-chip"
      className={`rounded-full border border-border bg-card text-left text-foreground/90 transition hover:border-[#E94BA8]/50 hover:text-foreground hover:shadow-[0_0_20px_-6px_rgba(233,75,168,0.6)] ${
        small ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm"
      }`}
    >
      {text}
    </button>
  );
}

function Dots() {
  return (
    <div className="flex gap-1 py-2">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-1.5 rounded-full bg-muted-foreground"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </div>
  );
}
