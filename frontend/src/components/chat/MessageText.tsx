"use client";

import { Fragment, type ReactNode } from "react";
import { ClusterChip } from "@/components/ClusterChip";
import type { Ask } from "@/lib/types";

const TOKEN = /\[([CWGD]\d+(?:\.\d+)?)\]|\*\*(.+?)\*\*/g;

function inline(text: string, onAsk: Ask): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(<ClusterChip key={m.index} id={m[1]} onClick={() => onAsk(`Tell me about [${m[1]}]`)} />);
    else out.push(<strong key={m.index} className="font-semibold text-foreground">{m[2]}</strong>);
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Plain text + "- " / "* " bullets, with [C3] cluster refs as clickable chips. */
export function MessageText({ text, onAsk }: { text: string; onAsk: Ask }) {
  const blocks: { bullets?: string[]; para?: string }[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const b = /^[-*•]\s+(.*)/.exec(line);
    if (b) {
      const prev = blocks.at(-1);
      if (prev?.bullets) prev.bullets.push(b[1]);
      else blocks.push({ bullets: [b[1]] });
    } else blocks.push({ para: line });
  }
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((b, i) =>
        b.bullets ? (
          <ul key={i} className="space-y-1.5">
            {b.bullets.map((t, j) => (
              <li key={j} className="flex gap-2">
                <span className="mt-2 size-1 shrink-0 rounded-full bg-[#F5A524]" />
                <span>{inline(t, onAsk)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p key={i}>
            {inline(b.para!, onAsk).map((n, j) => (
              <Fragment key={j}>{n}</Fragment>
            ))}
          </p>
        ),
      )}
    </div>
  );
}
