"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Canvas } from "@/components/canvas/Canvas";
import { Chat } from "@/components/chat/Chat";
import { TopBar } from "@/components/TopBar";
import { callTool, getManifest, setDataset, streamChat } from "@/lib/api";
import type { CanvasItem, ChartSpec, ChatMessage, Filters, Manifest } from "@/lib/types";

const uid = () => Math.random().toString(36).slice(2, 10);

export default function Home() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [filters, setFilters] = useState<Filters>({ brand: null, campaign: null, algo: "kmeans" });
  const [items, setItems] = useState<CanvasItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const batch = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const history = useRef<ChatMessage[]>([]);
  history.current = messages;

  useEffect(() => {
    getManifest()
      .then(setManifest)
      .catch((e) => setNotice(`Backend not reachable (${e.message}). Run make dev.`));
  }, []);

  const push = useCallback((charts: ChartSpec[]) => {
    if (!charts?.length) return;
    const b = ++batch.current;
    setItems((prev) => [...charts.map((chart, index) => ({ chart, batch: b, index })), ...prev].slice(0, 24));
  }, []);

  const patchLast = (fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => (ms.length ? [...ms.slice(0, -1), fn(ms[ms.length - 1])] : ms));

  const ask = useCallback(
    async (text: string) => {
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      const user: ChatMessage = { id: uid(), role: "user", content: text };
      const reply: ChatMessage = { id: uid(), role: "assistant", content: "", steps: [], pending: true };
      const sent = [...history.current.filter((m) => !m.pending), user]
        .slice(-10)
        .map(({ role, content }) => ({ role, content }));
      setMessages((ms) => [...ms.map((m) => ({ ...m, pending: false })), user, reply]);
      setBusy(true);
      try {
        await streamChat(
          sent,
          (ev) => {
            switch (ev.event) {
              case "tool_start":
                patchLast((m) => ({ ...m, steps: [...(m.steps ?? []), { tool: ev.data.tool, args: ev.data.args, status: "running" }] }));
                break;
              case "tool_result": {
                const failed = "error" in (ev.data.summary ?? {});
                patchLast((m) => {
                  const steps = [...(m.steps ?? [])];
                  const i = steps.findLastIndex((s) => s.tool === ev.data.tool && s.status === "running");
                  if (i >= 0) steps[i] = { ...steps[i], status: failed ? "error" : "done" };
                  return { ...m, steps };
                });
                push(ev.data.charts);
                break;
              }
              case "text_delta":
                patchLast((m) => ({ ...m, content: m.content + ev.data.text }));
                break;
              case "error":
                patchLast((m) => ({ ...m, error: ev.data.message }));
                break;
            }
          },
          ctl.signal,
        );
      } catch (e) {
        if (!ctl.signal.aborted) patchLast((m) => ({ ...m, error: (e as Error).message }));
      } finally {
        if (abort.current === ctl) {
          patchLast((m) => ({ ...m, pending: false }));
          setBusy(false);
        }
      }
    },
    [push],
  );

  const runClusters = useCallback(
    (f: Filters) =>
      callTool("get_need_clusters", { brand: f.brand, campaign: f.campaign, algo: f.algo })
        .then((r) => (r.charts.length ? push(r.charts) : setNotice(String(r.summary.note ?? "No comments match."))))
        .catch((e) => setNotice(e.message)),
    [push],
  );

  const onFilters = (f: Filters) => {
    setFilters(f);
    setNotice(null);
    runClusters(f);
  };

  const onDataset = (name: string) =>
    setDataset(name)
      .then((m) => {
        setManifest(m);
        const f = { brand: null, campaign: null, algo: filters.algo };
        setFilters(f);
        setItems([]);
        runClusters(f);
      })
      .catch((e) => setNotice(e.message));

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar manifest={manifest} filters={filters} onFilters={onFilters} onDataset={onDataset} />
      {notice && (
        <div className="flex items-center justify-between border-b border-[#F5A524]/20 bg-[#F5A524]/10 px-5 py-1.5 text-xs text-[#F5A524]">
          {notice}
          <button type="button" onClick={() => setNotice(null)} className="opacity-70 hover:opacity-100">
            dismiss
          </button>
        </div>
      )}
      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[38fr_62fr]">
        <section className="min-h-0 border-border lg:border-r">
          <Chat messages={messages} busy={busy} onAsk={ask} onStop={() => abort.current?.abort()} />
        </section>
        <section className="min-h-0 overflow-y-auto bg-[radial-gradient(ellipse_at_top_right,rgba(233,75,168,0.06),transparent_55%)] p-5">
          <Canvas items={items} onAsk={ask} onClose={(id) => setItems((xs) => xs.filter((x) => x.chart.id !== id))} />
        </section>
      </main>
    </div>
  );
}
