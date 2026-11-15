"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Canvas } from "@/components/canvas/Canvas";
import { Chat, PROMPTS } from "@/components/chat/Chat";
import { Toasts, useToasts } from "@/components/Toast";
import { TopBar } from "@/components/TopBar";
import { callTool, getManifest, setDataset, streamChat } from "@/lib/api";
import type { CanvasItem, ChartSpec, ChatMessage, Filters, Manifest } from "@/lib/types";

const uid = () => Math.random().toString(36).slice(2, 10);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const DEMO_PAUSE_MS = 3000;

export default function Home() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [filters, setFilters] = useState<Filters>({ brand: null, campaign: null, algo: "kmeans" });
  const [items, setItems] = useState<CanvasItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [pendingTools, setPendingTools] = useState(0);
  const [noMatch, setNoMatch] = useState(false);
  const [demo, setDemo] = useState(false);
  const { toasts, toast, dismiss } = useToasts();
  const demoRun = useRef(0);
  const batch = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const history = useRef<ChatMessage[]>([]);
  history.current = messages;

  useEffect(() => {
    getManifest()
      .then(setManifest)
      .catch((e) => toast(`Backend not reachable (${e.message}). Start it with make dev.`));
  }, [toast]);

  const push = useCallback((charts: ChartSpec[]) => {
    if (!charts?.length) return;
    setNoMatch(false);
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
                toast(ev.data.message);
                break;
            }
          },
          ctl.signal,
        );
      } catch (e) {
        if (!ctl.signal.aborted) {
          patchLast((m) => ({ ...m, error: (e as Error).message }));
          toast((e as Error).message);
        }
      } finally {
        if (abort.current === ctl) {
          patchLast((m) => ({ ...m, pending: false }));
          setBusy(false);
        }
      }
    },
    [push, toast],
  );

  const stopDemo = useCallback(() => {
    demoRun.current = 0;
    setDemo(false);
  }, []);

  /** Demo mode (for screen recording): send each prompt chip in turn, pausing between answers. */
  const runDemo = useCallback(async () => {
    if (demoRun.current) {
      stopDemo();
      abort.current?.abort();
      return;
    }
    const run = Date.now();
    demoRun.current = run;
    setDemo(true);
    for (const p of PROMPTS) {
      if (demoRun.current !== run) return;
      await ask(p);
      if (demoRun.current !== run) return;
      await sleep(DEMO_PAUSE_MS);
    }
    if (demoRun.current === run) stopDemo();
  }, [ask, stopDemo]);

  const userAsk = useCallback(
    (text: string) => {
      stopDemo();
      ask(text);
    },
    [ask, stopDemo],
  );

  const tool = useCallback(
    async <T,>(p: Promise<T>): Promise<T | undefined> => {
      setPendingTools((n) => n + 1);
      try {
        return await p;
      } catch (e) {
        toast((e as Error).message);
      } finally {
        setPendingTools((n) => n - 1);
      }
    },
    [toast],
  );

  const runClusters = useCallback(
    (f: Filters) =>
      tool(callTool("get_need_clusters", { brand: f.brand, campaign: f.campaign, algo: f.algo })).then((r) => {
        if (!r) return;
        if (r.charts.length) push(r.charts);
        else {
          setNoMatch(true);
          toast(String(r.summary.note ?? "No comments match these filters."), "info");
        }
      }),
    [push, tool, toast],
  );

  const onFilters = (f: Filters) => {
    setFilters(f);
    runClusters(f);
  };

  const onDataset = (name: string) =>
    tool(setDataset(name)).then((m) => {
      if (!m) return;
      setManifest(m);
      const f = { brand: null, campaign: null, algo: filters.algo };
      setFilters(f);
      setItems([]);
      setNoMatch(false);
      runClusters(f);
    });

  const last = messages[messages.length - 1];
  const loading = pendingTools > 0 || Boolean(last?.pending && (last.steps ?? []).some((s) => s.status === "running"));
  const counts = manifest?.manifest?.counts;
  const datasetLine = counts
    ? `${Number(counts.clustered ?? counts.comments ?? 0).toLocaleString()} comments · ${
        Object.keys(counts.by_brand ?? {}).length
      } brands · ${manifest?.manifest?.is_synthetic ? "benchmark" : "real Instagram data"}`
    : null;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar manifest={manifest} filters={filters} onFilters={onFilters} onDataset={onDataset} demo={demo} onDemo={runDemo} />
      {manifest?.manifest?.is_synthetic && (
        <div className="border-b border-[#F5A524]/20 bg-[#F5A524]/10 px-5 py-1.5 text-xs text-[#F5A524]" data-testid="benchmark-banner">
          Benchmark dataset: synthetic comments with known ground-truth needs, used to score clustering accuracy (ARI/NMI).
        </div>
      )}
      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[38fr_62fr]">
        <section className="min-h-0 border-border lg:border-r">
          <Chat
            messages={messages}
            busy={busy}
            onAsk={userAsk}
            onTyping={stopDemo}
            onStop={() => {
              stopDemo();
              abort.current?.abort();
            }}
          />
        </section>
        <section className="min-h-0 overflow-y-auto bg-[radial-gradient(ellipse_at_top_right,rgba(233,75,168,0.06),transparent_55%)] p-5">
          <Canvas
            items={items}
            loading={loading}
            noMatch={noMatch}
            datasetLine={datasetLine}
            demo={demo}
            onDemo={runDemo}
            onClearFilters={() => onFilters({ brand: null, campaign: null, algo: filters.algo })}
            onAsk={userAsk}
            onClose={(id) => setItems((xs) => xs.filter((x) => x.chart.id !== id))}
          />
        </section>
      </main>
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
