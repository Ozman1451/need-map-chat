# Setup Guide — Need Map Chat (Ubuntu 24.04, conda, Claude Code CLI)

Everything for this project lives in **one conda env (`ccc`)** plus the project folder. Delete both and the project is gone (section 10).

---

## 0. Undo the previous setup guide
Run only the parts for things you actually installed. **Do NOT remove `python3`, `git`, `curl`, `make` or `build-essential` with apt** — Ubuntu itself depends on them (removing system python3 breaks the desktop).

```bash
# --- uv ---
uv cache clean 2>/dev/null
rm -f ~/.local/bin/uv ~/.local/bin/uvx ~/.local/bin/env ~/.local/bin/env.fish
rm -rf ~/.local/share/uv ~/.cache/uv

# --- nvm + the Node it installed ---
rm -rf ~/.nvm ~/.npm

# --- Claude Code native install (we reinstall it inside the env) ---
rm -f ~/.local/bin/claude
rm -rf ~/.local/share/claude

# --- optional: apt packages that were new for this project ---
sudo apt remove -y gh python3-venv      # skip if you use them elsewhere
# --- optional: VS Code snap ---
# sudo snap remove code
```
Then remove the lines those installers added to your shell config:
```bash
grep -n "NVM_DIR\|nvm.sh\|bash_completion\|local/bin/env" ~/.bashrc ~/.profile ~/.zshrc 2>/dev/null
nano ~/.bashrc      # delete the lines grep showed (also in ~/.profile if listed), save
```
Open a new terminal and check they're gone:
```bash
which uv node npm claude      # should print nothing
```
Keep `~/.claude/` (your Claude login) and `~/.config/gh/` (GitHub login) — they're tiny and save logging in again. Section 10 shows how to delete them at the very end.

---

## 1. What you need
| Thing | Where |
|---|---|
| Claude Pro (or higher) plan, or Claude Console credits | claude.com/pricing |
| Gemini API key (free tier) | aistudio.google.com → Get API key |
| Apify account (free, $5/month credit) — needed only in Phase 5 | apify.com |
| Your existing conda (Miniconda/Anaconda) | already installed |

---

## 2. Create the env (all tools inside it)
```bash
conda create -n ccc -c conda-forge python=3.12 nodejs=22 make gh git -y
conda activate ccc

# keep caches inside the env too, so deleting the env removes them
conda env config vars set \
  PIP_CACHE_DIR=$CONDA_PREFIX/.cache/pip \
  npm_config_cache=$CONDA_PREFIX/.cache/npm \
  PLAYWRIGHT_BROWSERS_PATH=$CONDA_PREFIX/.cache/ms-playwright
conda deactivate && conda activate ccc

# Claude Code, installed into the env (not system-wide)
npm install -g @anthropic-ai/claude-code
```
Check that everything points into the env:
```bash
which python node npm make gh claude    # every path should contain /envs/ccc/
npm prefix -g                           # should be .../envs/ccc
claude --version
```
`npm install -g` is fine *here* because conda's Node puts "global" packages inside the env. Never use `sudo npm`.

**Every time you work on the project:** `conda activate ccc` first, then `claude`.

---

## 3. Create the GitHub repo
```bash
gh auth login                       # GitHub.com → HTTPS → login with browser (skip if already logged in)
mkdir -p ~/projects && cd ~/projects
gh repo create need-map-chat --private --clone
cd need-map-chat
unzip ~/Downloads/need-map-chat-kit.zip -d .
ls -a
```
You should see: `CLAUDE.md  SETUP_GUIDE.md  .env.example  .gitignore  .claude/  config/  docs/`.
(If you already made a repo with the old kit, just delete the old kit files in it and unzip this one instead.)

## 4. Add your Gemini key
```bash
cp .env.example .env
nano .env        # paste GEMINI_API_KEY, save: Ctrl+O, Enter, Ctrl+X
```
In aistudio.google.com → **rate limits**, confirm the three model names in `.env` have a free-tier quota; swap any that don't for a Flash / Flash-Lite model that does. Leave `APIFY_TOKEN` empty until Phase 5b.

## 5. First commit
```bash
git config --global user.name "Usman"            # first time only
git config --global user.email "<your github email>"
git add -A && git commit -m "Add spec and Claude Code context" && git push
```

## 6. Start Claude Code
```bash
conda activate ccc
cd ~/projects/need-map-chat
claude
```
First run opens a browser to log in (skipped if `~/.claude` still has your login).

Playwright (Phase 4 screenshots) downloads Chromium into the env automatically. If it complains about missing system libraries, run this yourself once (it's the only system-level step, and optional):
```bash
cd frontend && sudo env PATH=$PATH npx playwright install-deps chromium
```
If you'd rather keep the system untouched, skip it and tell Claude "skip screenshots".

---

## 7. Claude Code basics
| You do | Effect |
|---|---|
| Type, Enter | Give a task |
| `Shift+Tab` (repeat) | Cycle: normal → auto-accept edits → **plan mode** |
| `Esc` | Stop Claude and redirect |
| `@docs/SPEC.md` | Attach a file |
| `/clear` | Fresh conversation (CLAUDE.md reloads) — between phases |
| `/compact` | Shrink a long conversation |
| `/model` | Pick a model — a lighter one (e.g. Sonnet) for routine phases uses less of your plan |
| `/resume` or `claude -c` | Continue a previous session |
| `/verify` | The kit's check skill: tests + build (+ ≤2 screenshots) |
| `Ctrl+V` / drag an image | Show Claude a screenshot |

The kit's `.claude/settings.json` lets Claude run make/pip/npm/pytest/git commit without asking, and **blocks** sudo, apt, conda install, global npm, uv, `rm -rf`, `git push` and reading `.env` — so it can't install anything outside your env.

---

## 8. Build loop (Phases 0 → 6)
1. `conda activate ccc` → `cd ~/projects/need-map-chat` → `claude` (or `/clear`).
2. `Shift+Tab` to **plan mode**, paste the next prompt from `docs/BUILD_PLAN.md`, Enter.
3. Read the plan; correct it if needed; approve.
4. `Shift+Tab` to auto-accept edits; let it work.
5. Check yourself: `make dev` → open http://localhost:3000.
6. `/verify`, then "commit this phase" (you run `git push`).
7. `/clear` → next phase.

| Phase | You should see |
|---|---|
| 0 | Dark placeholder page; `/api/health` ok |
| 1 | ~2,500 realistic synthetic comments (check its 12 samples) |
| 2 | Metrics table, named clusters with actions, drill-down, odd comments |
| 3 | Agent answers "What does my audience want on Khaadi posts?" in terminal |
| 4 | The app: chat left, glowing cluster map right |
| 5a | Apify scraper built with fake data, estimated cost shown, $0 spent |
| 5b | Real Sapphire/Khaadi/Gul Ahmed comments clustered; Real/Synthetic toggle |
| 6 | Demo button, polish, README |

---

## 8b. Real data with Apify (Phase 5)
1. apify.com → Settings → **API & Integrations** → copy token → `APIFY_TOKEN=` in `.env`.
2. `config/targets.yaml`: confirm each brand handle by opening it in a browser; check `since`, `caption_keywords`; on each actor's Apify page → **Pricing**, update `price_per_1k`.
3. Expect ~90 posts / 1,200–2,000 comments on the free $5 (the official comment actor returns ~15 comments per post on the free plan). Enough for clustering.
4. Phase 5a prompt (no spend) → Phase 5b prompt. Claude dry-runs first and **waits for your OK**. Watch spend at console.apify.com → Usage.
5. If Apify fails: hand-collect a few posts into CSV and use `pipeline/import_csv.py`.

---

## 9. Habits that save tokens and time
- One phase per session, `/clear` between phases.
- Plan mode first; reject plans that add things not in the spec.
- Precise feedback with a screenshot beats "make it better".
- Commit after each green phase; `git checkout .` undoes a bad attempt.
- Set `MOCK_LLM=1` in `.env` while styling the UI (no Gemini calls); back to `0` for real answers.
- Don't delete `data/cache/` — it makes pipeline re-runs free.

## 9b. Before recording
- `DATASET=real`, `MOCK_LLM=0`, run the pipeline once.
- Use the **Demo** button; browser full screen (`F11`), zoom 110%.
- Record with Loom in Chrome (nothing to install).

---

## 10. Remove everything when the project is over
```bash
conda deactivate
conda env remove -n ccc                 # removes Python, Node, Claude Code, all packages, caches
rm -rf ~/projects/need-map-chat         # the project (push to GitHub first if you want to keep it)
# optional: Claude Code + GitHub CLI settings/logins in your home folder
rm -rf ~/.claude ~/.claude.json ~/.config/gh
```

## 11. Troubleshooting
| Problem | Fix |
|---|---|
| `make` says wrong env | `conda activate ccc` |
| `claude: command not found` | `conda activate ccc` (it lives in the env) |
| `which claude` shows `~/.local/bin` | Old native install still there → section 0 |
| Gemini `429 RESOURCE_EXHAUSTED` | Free-tier limit; wait; cache keeps finished work |
| Apify returns few comments | Normal on free plan; add posts within budget |
| Port in use | `lsof -i :3000` / `lsof -i :8000` → `kill <PID>` |
| Claude asks permission repeatedly | Choose "Yes, and don't ask again" |
