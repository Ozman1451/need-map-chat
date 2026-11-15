# SPEC — Need Map Chat
*"What does my audience want?" — comment need clustering for Pakistani lawn-suit brands*

## 1. Product in one paragraph
A Lahore lawn brand gets thousands of Instagram comments ("Price please?", "Karachi delivery?", "Price bohat zyada hai", "Inbox kar dein"). The marketer **chats** with an agent that clusters those comments into audience needs, splits big needs into sub-needs, surfaces unusual comments, compares clustering algorithms, and attaches one recommended action per need. Chat on the left; a **live canvas** on the right fills with charts as the agent calls tools.

## 2. What the app answers
| Question | Tool | Method |
|---|---|---|
| What does my audience want? | `get_need_clusters` | K-Means / Ward / DBSCAN / GMM on comment embeddings |
| Split a need further | `drill_down_cluster` | Ward sub-clustering inside one cluster |
| Show me real examples | `sample_comments` | nearest-to-centroid + random |
| Anything unusual? | `get_unusual_comments` | DBSCAN noise points (+ GMM low probability) |
| How do needs differ by campaign / brand / content type? | `need_share_by` | cluster share per group |
| What should we do about each need? | included in every cluster (`action`) | Gemini wording from cluster stats (offline) |
| Which algorithm is best and why? | `compare_algorithms` | silhouette, Davies–Bouldin, Calinski–Harabasz, bootstrap ARI, ARI vs ground truth (synthetic) |
| Quick numbers | `get_overview` | counts, language mix, top needs |

## 3. Architecture
```
frontend (Next.js) ── SSE POST /api/chat ──> backend (FastAPI)
  chat panel                                  agent loop: Gemini function calling, ≤4 tool steps
  canvas (ECharts) <──── chart specs ───────  tools.py → in-memory Store (parquet/json artifacts)
                                              llm.py   → only Gemini gateway (cache + retry)
offline: pipeline/*.py → data/processed/<dataset>/*.parquet + artifacts/<dataset>/*.json
```
Only live Gemini calls: the chat agent (1–3 per user turn).

## 4. Data

### 4.1 Tables (`data/processed/<dataset>/`)
- **posts**: `post_id, brand, url, posted_at, collected_at, campaign (Eid|11.11|12.12|Summer Lawn|Winter|Regular), content_type (Reel|Product Photo|Carousel|Influencer|Sale Announcement|Other), caption, likes, comments_count, source (synthetic|apify|manual), is_synthetic`
- **comments**: `comment_id, post_id, user_hash, text, created_at, is_synthetic, true_need (synthetic only, else null)`
- **comment_tags** (Gemini): `comment_id, sentiment (pos|neu|neg), purchase_intent (none|possible|strong), language_type (English|Roman Urdu|Urdu|Mixed), city (nullable), gloss (≤15-word English paraphrase of intent)`
- **comment_clusters**: `comment_id, x, y (UMAP 2D), kmeans, ward, dbscan, gmm, gmm_prob, primary, sub (drill-down label or null)`
- **clusters** (json): `cluster_id ("C3", "C3.1"), algo, parent_id, name, description, action, size, share, top_terms, exemplar_ids, sentiment_mix, intent_mix, language_mix, top_cities`

### 4.2 Synthetic dataset (`make seed`) — for building and all tests
`pipeline/seed_synthetic.py`:
- 3 brands, ~60 posts across campaigns/content types, **~2,500 comments**.
- Gemini (`GEMINI_BATCH_MODEL`) writes comments in batches: input = post metadata + a hidden need from {price_inquiry, discount_request, delivery_time, availability_city, size_fit, fabric_quality, compliment, order_complaint, inbox_request, purchase_intent}; output = 25 realistic comments mixing English / Roman Urdu / Urdu script with typos and emojis. Hidden need stored as `true_need`.
- Need mix varies by campaign (e.g. 12.12 posts → more discount_request) so `need_share_by` shows real differences.
- Also inject ~40 off-topic/odd comments (spam-like, other-language, questions about unrelated products) so DBSCAN has something unusual to find.
- `data/sample/`: 200-comment fixture for tests (committed).

### 4.3 Real dataset (`make scrape`) — final demo, built last
`pipeline/scrape_apify.py` + `map_apify.py`, configured by `config/targets.yaml`:
- Step A: profile actor → brand followers (stored, informational). Step B: post actor on brand profiles → keep posts after `since` whose caption matches a keyword, cap per brand. Step C: comment actor on kept posts, cap per post.
- Read each actor's README on apify.com and current apify-client docs before coding (exact inputs, outputs, per-run item cap).
- **Budget guard:** estimate cost = expected results × `price_per_1k`; print; abort if total would exceed `max_budget_usd`. Log each run (actor, run id, items, est. cost) to `data/raw/real/runs.jsonl`.
- `content_type` and `campaign` inferred from Apify media type + Gemini classification of the caption; store `infer_method`.
- Provenance on each row: `url, collected_at, source=apify, apify_actor, apify_run_id, is_synthetic=0`. Hash usernames; drop all other user fields.
- `--dry-run`: 1 brand, 2 posts, 20 comments, print mapped rows. Idempotent resume.
- Expected size on Apify's free plan: ~90 posts, ~1,200–2,000 comments (official comment actor gives ≈15 comments/post on free plan). README must state comments are the first visible page, not a random sample.
- Fallback: `pipeline/import_csv.py` for hand-collected posts/comments into `real`.

UI: Real/Synthetic toggle with counts; a "Synthetic data" banner when synthetic is active; default to `real` if `artifacts/real/` exists.

## 5. Offline pipeline (`make pipeline DATASET=...`)
1. **clean** — dedupe, drop empty/emoji-only/URL-only, normalize whitespace, keep emojis in text.
2. **tag** — Gemini structured output (pydantic schema = comment_tags), 50 comments/call, cached, resume-safe.
3. **embed** — `GEMINI_EMBED_MODEL`, task type CLUSTERING, 768 dims; embed `gloss` and raw `text` separately → `emb_gloss.npy`, `emb_raw.npy`; L2-normalize.
4. **cluster** — on PCA(50) of gloss embeddings:
   - K-Means k=4..14 → pick by silhouette; save the curve.
   - Ward (Agglomerative) same k range; save linkage of cluster centroids for a small dendrogram.
   - DBSCAN: eps from k-distance knee (min_samples=10); −1 = unusual.
   - GMM n=4..14 by BIC; save BIC curve and max prob.
   - `primary` = K-Means. UMAP(2D, cosine) for display only.
   - Drill-down precompute: every primary cluster with ≥80 members → Ward k=2..4 by silhouette → `C3.1`, `C3.2`…
5. **name** — per cluster: c-TF-IDF top terms + 8 comments nearest the centroid + stats → Gemini returns `{name ≤4 words, description 1 sentence, action 1 imperative sentence}`. Cached.
6. **metrics** — per algorithm: silhouette, Davies–Bouldin, Calinski–Harabasz, stability (mean ARI over 10 bootstrap 80% resamples); ARI + NMI vs `true_need` if present; raw-vs-gloss comparison (silhouette + ARI). → `artifacts/<dataset>/metrics.json`.
7. **artifacts** — write tables + `manifest.json` (counts, k choices, model names, timestamps, dataset).

## 6. Agent and tools

### 6.1 ChartSpec
```json
{ "id": "uuid", "type": "kpi_tiles|scatter_embed|cluster_list|sunburst|comment_cards|stacked_bar|metrics_table|line", "title": "", "subtitle": "", "data": {}, "meta": {} }
```

### 6.2 Tools
| Tool | Args | Charts |
|---|---|---|
| `get_overview` | brand?, campaign? | kpi_tiles (comments, posts, % purchase intent, language mix, top need) |
| `get_need_clusters` | brand?, campaign?, content_type?, algo=kmeans\|ward\|dbscan\|gmm | scatter_embed (x, y, cluster, short text; ≤3k points sampled) + cluster_list (name, share, action) |
| `drill_down_cluster` | cluster_id | sunburst (parent → children with shares) + cluster_list of children |
| `sample_comments` | cluster_id, n=8, language? | comment_cards (text, language, sentiment, brand, post link) |
| `get_unusual_comments` | brand?, n=12 | comment_cards + scatter_embed highlighting noise points |
| `need_share_by` | group_by=campaign\|brand\|content_type | stacked_bar (100% share per group) |
| `compare_algorithms` | — | metrics_table + line (silhouette vs k, BIC vs n) |

Filters apply to the precomputed labels; nothing is re-clustered at request time. Cluster ids in summaries use `[C3]` format.

### 6.3 Agent loop (`backend/app/agent.py`)
- System prompt: marketing analyst for Pakistani fashion brands; must call a tool for any number; reply ≤4 sentences + up to 3 bullet actions; cite clusters as `[C3]`; reply in the user's language (English or Roman Urdu); with ambiguous asks use defaults (all brands, K-Means) and say so in one line.
- Loop: history + tool declarations → execute function calls → stream `tool_start` / `tool_result` → feed back only `summary` (compact, ≤1.5k tokens) → repeat ≤4 → stream final text.
- Keep the last 10 messages of history.

### 6.4 SSE events (`POST /api/chat`)
`tool_start {tool,args}` · `tool_result {tool, summary, charts}` · `text_delta {text}` · `done` · `error {message}`.
Also: `GET /api/health`, `GET /api/manifest`, `POST /api/dataset {name}`, `POST /api/tool/{name}` (direct call for canvas clicks + tests).

## 7. UI
**Feel:** dark, premium, calm (Linear/Vercel style) with a magenta→saffron accent.
- Palette: bg `#0A0A0F`, surface `#12121A`, border `#23232F`, text `#EDEDF2`, muted `#8A8A9A`, accent gradient `#E94BA8 → #F5A524`; 12-color cluster palette readable on dark.
- Font: Geist Sans; Geist Mono for numbers.
- Single route `/`:
  - **Top bar:** title "Need Map", brand chips (All / Sapphire / Khaadi / Gul Ahmed), campaign select, algorithm segmented control (K-Means / Ward / DBSCAN / GMM), Real/Synthetic toggle with counts.
  - **Left (~38%) chat:** streaming messages, tool-trace stepper ("Clustering comments… ✓"), clickable `[C3]` chips, empty state with 5 prompt chips: "What does my audience want?", "Split the biggest need further", "Show me the weird comments", "How do needs change in 12.12 vs Eid?", "Which clustering algorithm fits best?".
  - **Right (~62%) canvas:** stack of chart cards (newest on top, close/expand). The scatter is the hero: glowing points (ECharts scatter with blur/shadow), hover shows comment text, clicking a point or legend item sends "Tell me about [C3]". Sunburst animates on drill-down.
- Motion: cards fade/slide in (framer-motion, 60ms stagger); tool steps tick to ✓.
- Top-bar filter changes trigger a direct `/api/tool/get_need_clusters` call (no LLM).

## 8. Testing
- pytest on `data/sample/`: cleaning; each clustering function returns valid labels; k-selection picks within range; drill-down creates children; every tool returns valid ChartSpecs; agent loop with mocked LLM emits events in order; Apify mapper on saved fake JSON; budget guard aborts over budget.
- Frontend: `npm run lint`, `npm run build`, `npm run shot` (Playwright; `/` after one canned chat with `MOCK_LLM=1`; saves to `shots/`).

## 9. Definition of done
- Clean clone in env `ccc`: `make setup && make seed && make pipeline && make dev` works (synthetic).
- "What does my audience want?" → scatter + named clusters with actions in ≤10 s; "split the biggest need" → sunburst; "show me weird comments" → noise comments.
- `make scrape && make pipeline DATASET=real` works within the $4.50 budget guard; toggle switches datasets.
- README: pitch, screenshots/Loom placeholders, mermaid architecture, methods + metrics (real and synthetic side by side), data provenance + synthetic disclosure + sampling limitation, setup, tech stack.
