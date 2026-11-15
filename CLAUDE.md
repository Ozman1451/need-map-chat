# CLAUDE.md — Need Map Chat

Read this first in every session. Full spec: @docs/SPEC.md. Build order: @docs/BUILD_PLAN.md.

## What this is
A chat-first web app for a university Big Data course (clustering module). A marketer asks "What does my audience want?" in chat; a Gemini agent calls Python clustering tools over Pakistani lawn-suit brand Instagram comments (Sapphire, Khaadi, Gul Ahmed) and the UI renders the returned charts on a live canvas. Scope is deliberately small: **comment need clustering only** (no personas, no post anomalies, no reports).

## Golden rule
**The LLM never computes numbers.** Every number shown comes from a Python tool over cached data. Gemini only (a) tags/glosses comments offline, (b) names clusters offline, (c) routes chat to tools and explains tool output live.

## Environment (strict)
- Ubuntu 24.04, bash. Everything lives in the conda env **`ccc`** (Python 3.12, Node 22, make, gh, Claude Code). The user runs Claude Code from inside the activated env, so `python`, `pip`, `node`, `npm` already point into it.
- Install Python packages only with `pip install` into the active env (via `backend/pyproject.toml`, `pip install -e "backend[dev]"`). Install JS packages only locally in `frontend/` (`npm install`, never `-g`).
- Never use `sudo`, `apt`, `uv`, `pipx`, `npm -g`, `conda install`, or `conda create`. If something truly needs a system or conda change, stop and ask the user.
- The Makefile starts with a guard that fails unless `CONDA_DEFAULT_ENV=ccc`.

## Stack
- `backend/` — FastAPI, scikit-learn, umap-learn, pandas, pyarrow, google-genai, pydantic v2, tenacity, apify-client, pyyaml.
- `frontend/` — Next.js (App Router, TypeScript), Tailwind, shadcn/ui, echarts-for-react, framer-motion, lucide-react.
- `pipeline/` — offline scripts run by `make pipeline`.
- `data/{raw,processed,cache}/<dataset>/` and `artifacts/<dataset>/`, where `<dataset>` is `synthetic` or `real`. Git-ignored except `data/sample/`.

## Commands
- `make setup` — `pip install -e "backend[dev]"` + `npm install` in frontend
- `make seed` — synthetic dataset
- `make scrape-dry` / `make scrape` — real Instagram data via Apify (SPEC §4.3)
- `make pipeline DATASET=synthetic|real` (default synthetic)
- `make dev DATASET=...` — backend :8000 + frontend :3000
- `make test` — pytest + `npm run lint && npm run build`
- `make verify` — `make test` + pipeline smoke run on `data/sample/`

## Rules
- All Gemini calls go through `backend/app/llm.py`. Model names come from env (`GEMINI_CHAT_MODEL`, `GEMINI_BATCH_MODEL`, `GEMINI_EMBED_MODEL`).
- Before writing `llm.py`, check the current google-genai Python SDK docs (function calling, embeddings, structured output). Do not rely on memory.
- Every Gemini call: disk cache keyed by sha1(model + prompt + input), tenacity backoff on 429/5xx, batch 50 comments per tagging call.
- Tests never hit the network (mock `llm.py`, fake Apify fixtures). Build and test only on `synthetic`. Run `make scrape` only when the user asks, and always `make scrape-dry` first.
- Never read or print `.env`. Hash usernames (sha256) at ingest. Keep `is_synthetic` on every row.
- Every tool returns `{"summary": dict, "charts": [ChartSpec]}` (SPEC §6). Frontend renders by `chart.type` only.
- Keep code small: pure functions for clustering, thin CLI scripts, no extra features beyond the spec.
- After each phase: run `make verify`, fix failures, summarise in ≤8 lines, stop.

## Token discipline
- Don't re-read large generated files (parquet, JSON artifacts, lockfiles, node_modules). Inspect data with short pandas one-liners (`head`, `shape`, `value_counts`).
- Screenshots: only in UI phases, at most 2 per review round.
- Don't paste long logs back; summarise errors.
