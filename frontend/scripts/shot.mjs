// npm run shot — Playwright screenshots of `/` after canned chats (SPEC §8).
// Starts backend (MOCK_LLM=1, synthetic) and Next dev if they are not already up; uses system Chrome
// (CHROME_PATH or channel "chrome") so no browser download is needed. Saves to frontend/shots/.
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const FRONT = join(dirname(fileURLToPath(import.meta.url)), "..");
const API = "http://127.0.0.1:8000";
const WEB = "http://127.0.0.1:3000";
const OUT = join(FRONT, "shots");
const PAGE = "http://localhost:3000"; // must match the backend CORS origin
const procs = [];
let browser;

const up = (url) => fetch(url).then((r) => r.ok, () => false);

async function waitFor(url, ms = 90_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (await up(url)) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`timeout waiting for ${url}`);
}

function start(cmd, args, cwd, env = {}) {
  const p = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, stdio: "ignore", detached: true });
  procs.push(p);
}

function cleanup() {
  for (const p of procs) {
    try {
      process.kill(-p.pid, "SIGTERM");
    } catch {}
  }
}

async function main() {
  if (!(await up(`${API}/api/health`))) {
    start("uvicorn", ["app.main:app", "--port", "8000", "--app-dir", "backend"], join(FRONT, ".."), {
      MOCK_LLM: "1",
      DATASET: process.env.DATASET ?? "synthetic",
    });
  }
  if (!(await up(WEB))) start("npx", ["next", "dev", "--port", "3000"], FRONT);
  await waitFor(`${API}/api/health`);
  await waitFor(WEB);
  console.log("servers up");
  mkdirSync(OUT, { recursive: true });

  browser = await chromium.launch(
    process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: "chrome" },
  );
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("requestfailed", (r) => errors.push(`${r.url()} ${r.failure()?.errorText}`));
  process.on("exit", () => errors.length && console.warn("page errors:", errors.slice(0, 8)));
  await page.goto(PAGE, { waitUntil: "networkidle" });

  const ask = async (text, chartType) => {
    await page.getByTestId("prompt-chip").filter({ hasText: text }).first().click();
    await page.locator(`[data-chart-type="${chartType}"]`).first().waitFor({ timeout: 60_000 });
    await page.getByPlaceholder(/Ask about your audience/).waitFor();
    await page.locator('button[aria-label="Send"]').waitFor({ timeout: 60_000 }); // stream done
    await page.waitForTimeout(1600); // let ECharts / framer-motion settle
  };

  await ask("What does my audience want?", "scatter_embed");
  console.log("chat 1 done");
  await page.screenshot({ path: join(OUT, "home.png") });
  await ask("Split the biggest need further", "sunburst");
  await page.screenshot({ path: join(OUT, "drill.png") });

  await browser.close();
  if (errors.length) console.warn("page errors:", errors);
  console.log(`saved ${join(OUT, "home.png")} and ${join(OUT, "drill.png")}`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(async () => {
    await browser?.close().catch(() => {});
    cleanup();
  });
