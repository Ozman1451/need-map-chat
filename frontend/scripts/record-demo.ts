// node scripts/record-demo.ts [clipName] — records the product demo with system Chrome (playwright-core).
// Needs `make dev` running (backend :8000 with real Gemini, frontend :3000). Frames come from the CDP
// screencast (Playwright's own video recorder needs a separate ffmpeg download); they are written as JPEGs
// with a timeline (captions + dead-time cuts) to docs/media/raw/<clip>/, and scripts/demo_video.py edits them.
// Quota guard: ≤10 chat turns, ≥13 s between chat requests, one retry per step.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Page } from "playwright-core";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CLIP = process.argv[2] ?? "main";
const DRY = process.argv.includes("--dry"); // empty state only, no chat calls
const FROM = Number(process.argv[process.argv.indexOf("--from") + 1]) || 1; // re-record from step 8 only
const CAPTIONS = process.argv.includes("--captions");
const HOVER = process.argv.includes("--hover"); // splice clip: hover tooltips in the expanded need map // only render caption pills for an existing clip
const OUT = join(ROOT, "docs", "media", "raw", CLIP);
const MEDIA = join(ROOT, "docs", "media");
const PAGE = "http://localhost:3000";
const MAX_CHATS = 10;
const CHAT_GAP_MS = 13_500;

type Mark = { t: number; kind: "caption" | "cut_start" | "cut_end" | "step"; text?: string };
const marks: Mark[] = [];
let t0 = 0;
const now = () => (Date.now() - t0) / 1000;
const mark = (kind: Mark["kind"], text?: string) => marks.push({ t: now(), kind, text });
const caption = (text: string) => mark("caption", text);
let chats = 0;
let lastChat = 0;
const mouse = { x: 960, y: 540 };

const CURSOR = `
addEventListener("DOMContentLoaded", () => {
  const s = document.createElement("style");
  s.textContent = \`
    #demo-cursor{position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;margin:-11px 0 0 -11px;
      border-radius:50%;background:rgba(255,255,255,.92);border:2px solid #E94BA8;
      box-shadow:0 0 0 4px rgba(233,75,168,.25),0 2px 10px rgba(0,0,0,.5);transition:transform .12s ease}
    #demo-cursor.down{transform:scale(.75)}
    .demo-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:16px;height:16px;margin:-8px 0 0 -8px;
      border-radius:50%;border:3px solid #F5A524;animation:demo-rip .55s ease-out forwards}
    @keyframes demo-rip{to{transform:scale(4.2);opacity:0}}\`;
  document.head.appendChild(s);
  const c = document.createElement("div");
  c.id = "demo-cursor";
  c.style.left = "960px"; c.style.top = "540px";
  document.body.appendChild(c);
  addEventListener("mousemove", (e) => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
  addEventListener("mousedown", (e) => {
    c.classList.add("down");
    const r = document.createElement("div");
    r.className = "demo-ripple"; r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px";
    document.body.appendChild(r); setTimeout(() => r.remove(), 600);
  }, true);
  addEventListener("mouseup", () => c.classList.remove("down"), true);
});`;

const wait = (page: Page, ms: number) => page.waitForTimeout(ms);

async function glide(page: Page, x: number, y: number) {
  const d = Math.hypot(x - mouse.x, y - mouse.y);
  await page.mouse.move(x, y, { steps: Math.max(8, Math.min(40, Math.round(d / 25))) });
  mouse.x = x;
  mouse.y = y;
}

async function clickAt(page: Page, x: number, y: number) {
  await glide(page, x, y);
  await wait(page, 180);
  await page.mouse.down();
  await wait(page, 70);
  await page.mouse.up();
}

async function clickEl(page: Page, selector: string) {
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`no box for ${selector}`);
  await clickAt(page, box.x + box.width / 2, box.y + box.height / 2);
}

const count = (page: Page, type: string) => page.locator(`[data-chart-type="${type}"]`).count();
const scrollCanvasTop = (page: Page) =>
  page.evaluate(() => document.querySelector("main > section:last-child")?.scrollTo({ top: 0, behavior: "smooth" }));

/** Wait out the RPM gap (cut in post), then send. Returns false when the reply failed. */
async function chatTurn(page: Page, send: () => Promise<void>, expect: string[], label: string): Promise<boolean> {
  for (let attempt = 0; attempt < 2; attempt++) {
    if (chats >= MAX_CHATS) throw new Error("chat budget exhausted");
    const gap = CHAT_GAP_MS - (Date.now() - lastChat);
    if (gap > 0) {
      mark("cut_start");
      await wait(page, gap);
      mark("cut_end");
    }
    const before = await Promise.all(expect.map((t) => count(page, t)));
    const msgs = await page.getByTestId("assistant-msg").count();
    lastChat = Date.now();
    chats++;
    console.log(`chat ${chats}: ${label}${attempt ? " (retry)" : ""}`);
    await send();
    await wait(page, 1400);
    mark("cut_start");
    try {
      for (let i = 0; i < expect.length; i++) {
        await page.waitForFunction(
          ([t, n]) => document.querySelectorAll(`[data-chart-type="${t}"]`).length > Number(n),
          [expect[i], before[i]] as const,
          { timeout: 90_000 },
        );
      }
      mark("cut_end");
      await wait(page, 2200); // chart entrance animation
      mark("cut_start");
      await page.locator('button[aria-label="Send"]').waitFor({ timeout: 90_000 }); // stream finished
      const last = page.getByTestId("assistant-msg").nth(msgs);
      const text = (await last.innerText()).trim();
      const bad = (await last.locator(".text-red-300").count()) > 0 || /mock reply/i.test(text) || text.length < 20;
      mark("cut_end");
      if (!bad) return true;
      console.warn(`step "${label}" reply looks wrong: ${text.slice(0, 120)}`);
    } catch (e) {
      mark("cut_end");
      console.warn(`step "${label}" failed: ${(e as Error).message.split("\n")[0]}`);
    }
  }
  return false;
}

async function typeAndSend(page: Page, text: string) {
  await clickEl(page, "textarea");
  await wait(page, 250);
  for (const ch of text) await page.keyboard.type(ch, { delay: 40 + Math.random() * 20 });
  await wait(page, 450);
  await page.keyboard.press("Enter");
}

const ask = (page: Page, text: string, expect: string[]) => chatTurn(page, () => typeAndSend(page, text), expect, text);

/** Find coloured scatter points on the first ECharts canvas (same-origin, so pixels are readable). */
async function scatterPoints(page: Page, n: number) {
  return page.evaluate((n) => {
    const card = document.querySelector('[data-chart-type="scatter_embed"]');
    const cv = card?.querySelector("canvas");
    if (!cv) return [];
    const r = cv.getBoundingClientRect();
    const sx = cv.width / r.width;
    const ctx = cv.getContext("2d")!;
    const img = ctx.getImageData(0, 0, cv.width, cv.height).data;
    const hits: { x: number; y: number }[] = [];
    const legend = 70 * sx;
    for (let y = 20; y < cv.height - legend; y += 6)
      for (let x = 20; x < cv.width - 20; x += 6) {
        const i = (y * cv.width + x) * 4;
        const [R, G, B] = [img[i], img[i + 1], img[i + 2]];
        if (Math.max(R, G, B) > 200 && Math.max(R, G, B) - Math.min(R, G, B) > 90) hits.push({ x, y });
      }
    // spread picks: left, centre and right thirds
    const picks: { x: number; y: number }[] = [];
    for (let k = 0; k < n; k++) {
      const lo = (cv.width * k) / n, hi = (cv.width * (k + 1)) / n;
      const band = hits.filter((h) => h.x > lo && h.x < hi);
      if (band.length) picks.push(band[Math.floor(band.length / 2)]);
    }
    return picks.map((p) => ({ x: r.left + p.x / sx, y: r.top + p.y / sx }));
  }, n);
}

/** Bright pixels in the expanded need map, then keep only spots that really raise a tooltip (probed in a cut). */
async function tooltipSpots(page: Page, n: number) {
  const cands = await page.evaluate(() => {
    const cv = document.querySelector(".fixed canvas") as HTMLCanvasElement;
    const r = cv.getBoundingClientRect();
    const sx = cv.width / r.width;
    const d = cv.getContext("2d")!.getImageData(0, 0, cv.width, cv.height).data;
    const seen = new Set<string>();
    const out: { x: number; y: number }[] = [];
    for (let y = 10; y < cv.height - 80 * sx; y += 2)
      for (let x = 10; x < cv.width - 10; x += 2) {
        const i = (y * cv.width + x) * 4;
        const key = `${Math.round(x / 14)}:${Math.round(y / 14)}`;
        if (Math.max(d[i], d[i + 1], d[i + 2]) > 225 && !seen.has(key)) {
          seen.add(key);
          out.push({ x: r.left + x / sx, y: r.top + y / sx });
        }
      }
    return out;
  });
  const tipShown = () =>
    page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>(".fixed div")].some(
        (d) => d.style.zIndex === "9999999" && getComputedStyle(d).display !== "none" && Number(getComputedStyle(d).opacity) > 0.5,
      ),
    );
  const picks: { x: number; y: number }[] = [];
  const order = [...cands].sort((a, b) => a.x - b.x);
  const stride = Math.max(1, Math.floor(order.length / 40));
  for (let k = 0; k < order.length && picks.length < n; k += stride) {
    const p = order[k];
    if (picks.some((q) => Math.hypot(q.x - p.x, q.y - p.y) < 180)) continue;
    await page.mouse.move(p.x - 3, p.y);
    await page.mouse.move(p.x, p.y, { steps: 2 });
    await page.waitForTimeout(250);
    if (await tipShown()) picks.push(p);
  }
  return picks;
}

async function hoverClip(page: Page) {
  // full-screen backdrop-blur drops the headless screencast to ~7 fps; a darker solid backdrop looks the same
  await page.addStyleTag({ content: ".fixed.inset-0{backdrop-filter:none!important;background:rgba(5,5,8,.9)!important}" });
  mark("cut_start");
  await clickEl(page, 'header button:text-is("All")');
  await page.locator('[data-chart-type="scatter_embed"]').first().waitFor();
  await wait(page, 1500);
  mark("cut_end");
  mark("step", "h");
  caption("Hover any point to read the real comment behind it");
  await clickEl(page, '[data-chart-type="scatter_embed"] button[aria-label="Expand"]');
  await wait(page, 1200);
  const home = { ...mouse };
  mark("cut_start");
  const spots = await tooltipSpots(page, 3);
  await page.mouse.move(home.x, home.y);
  await wait(page, 300);
  mark("cut_end");
  console.log(`tooltip spots: ${spots.length}`);
  for (const p of spots) {
    await glide(page, p.x - 2, p.y);
    await page.mouse.move(p.x, p.y, { steps: 2 });
    await wait(page, 2000);
  }
  await clickEl(page, '.fixed button[aria-label="Collapse"]');
  await wait(page, 700);
}

async function main() {
  if (existsSync(join(OUT, "timeline.json")) && !process.argv.includes("--force"))
    throw new Error(`${OUT} already has a recording; pick a new clip name or pass --force`);
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(join(OUT, "frames"), { recursive: true });
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome" });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  await context.addInitScript(CURSOR);
  const page = await context.newPage();
  t0 = Date.now();
  const frames: { f: string; t: number }[] = [];
  const cdp = await context.newCDPSession(page);
  cdp.on("Page.screencastFrame", (ev) => {
    const f = `frames/${String(frames.length).padStart(6, "0")}.jpg`;
    writeFileSync(join(OUT, f), Buffer.from(ev.data, "base64"));
    frames.push({ f, t: (ev.metadata.timestamp ?? Date.now() / 1000) - t0 / 1000 });
    cdp.send("Page.screencastFrameAck", { sessionId: ev.sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: 1920, maxHeight: 1080 });
  mark("cut_start");
  await page.goto(PAGE, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Khaadi" }).waitFor({ timeout: 60_000 });
  await page.mouse.move(mouse.x, mouse.y);
  await wait(page, 800);
  mark("cut_end");
  const ok: Record<string, boolean> = {};
  if (HOVER) {
    await hoverClip(page);
    return finish();
  }
  if (FROM >= 8) {
    // splice clip: fill the canvas with a direct tool call (cut in post), then continue at step 8
    mark("cut_start");
    await clickEl(page, 'header button:text-is("Sapphire")');
    await page.locator('[data-chart-type="scatter_embed"]').first().waitFor();
    await wait(page, 1500);
    mark("cut_end");
  } else {

  // 1. empty state
  mark("step", "1");
  caption("Clusters 600 real Instagram comments into 10 audience needs");
  await wait(page, 2000);
  await glide(page, 400, 900);
  if (DRY) return finish();

  // 2. first question
  mark("step", "2");
  caption("Ask in plain words: the agent picks a clustering tool");
  ok.overview = await ask(page, "What does my audience want?", ["scatter_embed", "cluster_list"]);
  caption("K-Means over local multilingual-e5 embeddings → need map + named needs");
  await wait(page, 3000);
  await page.screenshot({ path: join(MEDIA, "screen-overview.png") });

  // 3. hover points, click the biggest cluster in the legend
  mark("step", "3");
  caption("Hover any point to read the real comment behind it");
  for (const p of await scatterPoints(page, 3)) {
    await glide(page, p.x, p.y);
    await wait(page, 1300);
  }
  caption("Click a need to ask about it");
  const sc = await page.locator('[data-chart-type="scatter_embed"] canvas').first().boundingBox();
  ok.legend = await chatTurn(
    page,
    async () => {
      await clickAt(page, sc!.x + 90, sc!.y + sc!.height - 13);
      await wait(page, 600);
      const asked = await page.getByText(/^Tell me about \[/).count();
      if (!asked) await clickEl(page, '[data-chart-type="cluster_list"] li button'); // fallback: cluster chip
    },
    [],
    "legend click",
  ).catch(() => false);
  await wait(page, 2500);

  // 4. drill-down
  await scrollCanvasTop(page);
  mark("step", "4");
  caption("Drill down: Ward sub-clustering inside the biggest need");
  ok.drill = await ask(page, "Split the biggest need further", ["sunburst"]);
  await wait(page, 3000);
  await page.screenshot({ path: join(MEDIA, "screen-drilldown.png") });

  // 5. brand chips (direct tool calls, no chat)
  mark("step", "5");
  caption("Brand filters re-run the clustering tool directly, no LLM call");
  await scrollCanvasTop(page);
  for (const b of ["Khaadi", "Sapphire"]) {
    const n = await count(page, "scatter_embed");
    await clickEl(page, `header button:text-is("${b}")`);
    await page.waitForFunction((n) => document.querySelectorAll('[data-chart-type="scatter_embed"]').length > n, n);
    await wait(page, 2600);
  }

  // 6. brands
  mark("step", "6");
  caption("Need share per brand across all 7 brands");
  ok.brands = await ask(page, "How do needs differ between brands?", ["stacked_bar"]);
  await wait(page, 3000);

  // 7. unusual
  mark("step", "7");
  caption("Unusual comments: DBSCAN noise, centroid distance, low GMM probability");
  ok.weird = await ask(page, "Show me the weird comments", ["comment_cards"]);
  await wait(page, 3000);
  }

  // 8. metrics + algorithm switch
  mark("step", "8");
  caption("Silhouette, Davies–Bouldin, Calinski–Harabasz and stability per algorithm");
  ok.metrics = await ask(page, "Which clustering algorithm fits best?", ["metrics_table"]);
  // the agent may also re-run get_need_clusters, which pushes the table below the fold
  await page.locator('[data-chart-type="metrics_table"]').first().evaluate((el) => el.scrollIntoView({ behavior: "smooth", block: "start" }));
  await wait(page, 3500);
  await page.screenshot({ path: join(MEDIA, "screen-metrics.png") });
  await scrollCanvasTop(page);
  await wait(page, 800);
  caption("Switch algorithms in one click: DBSCAN, then back to K-Means");
  for (const a of ["DBSCAN", "K-Means"]) {
    const n = await count(page, "scatter_embed");
    await clickEl(page, `[role="radio"]:text-is("${a}")`);
    await page.waitForFunction((n) => document.querySelectorAll('[data-chart-type="scatter_embed"]').length > n, n);
    await wait(page, 2600);
  }

  // 9. final dashboard
  mark("step", "9");
  caption("Every number comes from Python tools over cached clustering results");
  await scrollCanvasTop(page);
  await glide(page, 1880, 1040);
  await wait(page, 3500);
  return finish();

  async function finish() {
    mark("step", "end");
    await cdp.send("Page.stopScreencast");
    await browser.close();
    writeFileSync(join(OUT, "timeline.json"), JSON.stringify({ marks, ok, chats, frames }, null, 1));
    console.log(`done: ${frames.length} frames, ${chats} chat calls, ok=${JSON.stringify(ok)} → ${OUT}`);
  }
}

/** Lower-third caption pills as transparent PNGs (Geist, dark pill, magenta→saffron dot). */
async function renderCaptions() {
  const { marks } = JSON.parse(readFileSync(join(OUT, "timeline.json"), "utf8")) as { marks: Mark[] };
  const font = readFileSync(join(ROOT, "frontend/node_modules/next/dist/next-devtools/server/font/geist-latin.woff2"));
  const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome" });
  const page = await browser.newPage({ viewport: { width: 1920, height: 200 }, deviceScaleFactor: 1 });
  const texts = marks.filter((m) => m.kind === "caption").map((m) => m.text!);
  for (const [i, text] of texts.entries()) {
    await page.setContent(`<style>
      @font-face{font-family:G;src:url(data:font/woff2;base64,${font.toString("base64")})}
      body{margin:0;background:transparent}
      #w{display:inline-block;padding:22px}
      #c{display:inline-flex;align-items:center;gap:16px;padding:16px 30px 16px 22px;border-radius:999px;
        background:rgba(10,10,15,.80);border:1px solid rgba(255,255,255,.10);box-shadow:0 8px 32px rgba(0,0,0,.45);
        font:500 30px/1.2 G,"Noto Sans",sans-serif;letter-spacing:-.01em;color:#fff;white-space:nowrap}
      #c i{width:14px;height:14px;border-radius:50%;background:linear-gradient(135deg,#E94BA8,#F5A524);
        box-shadow:0 0 14px rgba(233,75,168,.8)}
    </style><div id="w"><div id="c"><i></i><span></span></div></div>`);
    await page.locator("#c span").evaluate((el, t) => (el.textContent = t), text);
    await page.evaluate(() => document.fonts.ready);
    await page.locator("#w").screenshot({ path: join(OUT, `cap_${String(i).padStart(2, "0")}.png`), omitBackground: true });
  }
  await browser.close();
  console.log(`rendered ${texts.length} captions → ${OUT}`);
}

(CAPTIONS ? renderCaptions() : main()).catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
