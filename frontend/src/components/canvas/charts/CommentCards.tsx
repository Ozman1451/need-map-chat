"use client";

import { ExternalLink } from "lucide-react";
import { ClusterChip } from "@/components/ClusterChip";
import { C } from "@/lib/theme";
import type { Ask, ChartSpec } from "@/lib/types";

interface Card {
  id: string;
  text: string;
  gloss?: string;
  language: string;
  sentiment: string;
  intent: string;
  brand: string;
  campaign?: string;
  post_url?: string;
  cluster: string;
  cluster_name?: string;
  reasons: string[];
  kind?: string;
  unusual_score?: number;
}

const SENT: Record<string, string> = { pos: "#7BE495", neg: "#FF7A59", neu: C.muted, mixed: C.saffron };

export function CommentCards({ chart, onAsk }: { chart: ChartSpec; onAsk: Ask }) {
  const cards: Card[] = chart.data.cards ?? [];
  if (!cards.length) return <p className="py-6 text-center text-sm text-muted-foreground">No comments here.</p>;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {cards.map((c) => (
        <article key={c.id} className="flex flex-col rounded-xl border border-border/80 bg-white/[0.02] p-3">
          <p className="text-sm leading-relaxed">{c.text}</p>
          {c.gloss && c.gloss !== c.text && (
            <p className="mt-1 text-xs italic leading-relaxed text-muted-foreground">“{c.gloss}”</p>
          )}
          {c.reasons?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {c.reasons.map((r) => (
                <span key={r} className="rounded-full bg-[#F5A524]/10 px-2 py-0.5 text-[10px] text-[#F5A524]">
                  {r.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          )}
          <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-3 text-[11px] text-muted-foreground">
            <ClusterChip id={c.cluster} onClick={() => onAsk(`Tell me about [${c.cluster}]`)} />
            <span>{c.brand}</span>
            <span>·</span>
            <span>{c.language}</span>
            <span className="flex items-center gap-1">
              <span className="size-1.5 rounded-full" style={{ background: SENT[c.sentiment] ?? C.muted }} />
              {c.sentiment}
            </span>
            {c.intent && c.intent !== "none" && <span className="text-[#E94BA8]">intent: {c.intent}</span>}
            {c.post_url && (
              <a href={c.post_url} target="_blank" rel="noreferrer" className="ml-auto hover:text-foreground" title="Open post">
                <ExternalLink className="size-3.5" />
              </a>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
