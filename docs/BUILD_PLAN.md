# BUILD PLAN — paste one phase at a time into Claude Code

Before each phase: be inside the env (`conda activate ccc`), start `claude` in the repo root (or `/clear`), press `Shift+Tab` until **plan mode**, paste the prompt, approve the plan. After it finishes: `/verify`, commit, `/clear`.

Data rule: build and test on **synthetic** only. Real Apify data comes in Phase 5.

---

## Phase 0 — Scaffold (≈20 min)
```
Read CLAUDE.md and docs/SPEC.md. Phase 0 only: scaffold backend/ (pyproject.toml with deps from CLAUDE.md + dev extras pytest/httpx; app/main.py, config.py, llm.py stub, store.py, tools.py, agent.py, schemas.py), pipeline/ (empty step scripts with --dataset), frontend/ (Next.js App Router + TS + Tailwind + shadcn/ui + echarts-for-react + framer-motion), Makefile (env guard for CONDA_DEFAULT_ENV=ccc; targets setup, seed, scrape-dry, scrape, pipeline, dev, test, verify; DATASET default synthetic), data/ and artifacts/ folders per CLAUDE.md, .gitignore. /api/health returns ok; frontend shows a dark placeholder. Follow the Environment rules strictly. Make `make verify` pass.
```

## Phase 1 — Gemini gateway + synthetic data (≈1 h)
```
Phase 1: read the current google-genai Python SDK docs (structured output, embeddings, function calling), then implement backend/app/llm.py per CLAUDE.md (env model names, sha1 disk cache under data/cache/<dataset>/, tenacity retry, MOCK_LLM=1). Implement pipeline/seed_synthetic.py per SPEC §4.2 and data/sample/. Run with 10 posts first and show me 12 random comments to check realism; then run full size. Tests. Stop after make verify passes.
```

## Phase 2 — Pipeline (≈1.5–2 h)
```
Phase 2: implement SPEC §5 steps 1–7 as pure functions + thin CLIs, working when true_need is null. Embeddings are local (sentence-transformers multilingual-e5-base, CPU; EMBED_BACKEND=gemini optional). Run make pipeline on synthetic. Print one compact table: algo, chosen k, silhouette, DB, stability ARI, ARI vs true_need; then raw-vs-gloss result, cluster names + actions, drill-down children of the largest cluster, and 5 DBSCAN noise comments. Tests on data/sample. Stop after make verify passes.
```

## Phase 3 — Tools + agent + SSE (≈1.5 h)
```
Phase 3: implement Store (loads artifacts/<dataset>/, switchable via /api/dataset), the 7 tools in SPEC §6.2, the agent loop §6.3 with Gemini function calling, SSE §6.4, and /api/tool/{name}, /api/manifest. Tests: valid ChartSpecs per tool; mocked agent emits events in order. Then run the real agent once from a CLI script with "What does my audience want on Khaadi posts?" and show a short event summary.
```

## Phase 4 — Frontend (≈2–3 h)
```
Phase 4: build the single-page UI per SPEC §7: top bar (brands, campaign, algorithm control, Real/Synthetic toggle), chat with SSE streaming + tool-trace stepper + [C3] chips + prompt chips, canvas with one component per ChartSpec type (dark ECharts theme, glowing scatter hero, animated sunburst). Point/legend click sends a follow-up. Add `npm run shot` (Playwright, MOCK_LLM=1). Take at most 2 screenshots, review them, fix visual issues once, show me.
```

## Phase 5a — Apify scraper, no credit spent (≈1 h)
```
Phase 5a: implement scrape_apify.py, map_apify.py, import_csv.py per SPEC §4.3 using config/targets.yaml. First read apify-client docs and each actor's README (IDs in targets.yaml) for inputs, outputs and per-run item caps. Budget guard, provenance, hashing, --dry-run, idempotent resume, Gemini inference of content_type/campaign. Tests with fake Apify JSON fixtures, no network. Do NOT run a real scrape. Stop after make verify and tell me the estimated full-run cost.
```

## Phase 5b — Real run (spends Apify credit; only after I confirm)
```
Phase 5b: APIFY_TOKEN is in .env (don't read it) and I checked targets.yaml. Run make scrape-dry, show mapped rows + cost, then WAIT for my OK. Then make scrape and make pipeline DATASET=real (embeddings run locally — no embedding quota; Gemini is only used for tagging, naming and caption inference). Show counts per brand, language mix, the metrics table, cluster names + actions, 5 noise comments, and anything broken vs synthetic. Fix real-data issues (nulls, tiny clusters, few comments per campaign). Then make dev DATASET=real and take 1 screenshot.
```

## Phase 6 — Polish + README (≈1 h)
```
Phase 6: loading skeletons, error toasts, empty states, and a "Demo" button that sends the 5 prompt chips one by one with pauses (for screen recording). Default to the real dataset when artifacts/real exists. Write README.md per SPEC §9 (metrics from artifacts/real/metrics.json and artifacts/synthetic/metrics.json side by side; setup notes for the CPU torch index and the local multilingual-e5-base embedder). Run make verify.
```
