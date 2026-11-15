"""Scrape Instagram via Apify (SPEC §4.3), configured by config/targets.yaml.

A: profile actor → followers (informational).  B: post actor on brand profiles (scan_posts_per_brand
each, newer than `since`) → keep caption-keyword matches, max_posts_per_brand.  C: comment actor, ONE
run per kept post (its output has no post link), max_comments_per_post each.

Budget guard: worst case = max chargeable items × price_per_1k + runs × start_fee_usd; abort before
any run if spent (runs.jsonl) + remaining worst case > max_budget_usd. Every run is also capped
server-side (max_items, max_total_charge_usd). Raw results are saved per step/post, so re-running
skips finished work (idempotent resume). --dry-run: 1 brand, 2 posts, 20 comments → data/raw/real/dry/.
--estimate: print the cost plan and exit (no network).
"""
import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from _cli import parser, raw_dir, setup_logging
from map_apify import build_tables, filter_posts, load_targets, read_raw, write_tables

STEPS = ("profile", "posts", "comments")


class BudgetExceeded(RuntimeError):
    pass


def dry_targets(t: dict) -> dict:
    d = copy.deepcopy(t)
    d["brands"] = t["brands"][:1]
    d["post_urls"] = (t.get("post_urls") or [])[:2]
    d.update(scan_posts_per_brand=min(12, t["scan_posts_per_brand"]), max_posts_per_brand=2,
             max_comments_per_post=10)
    return d


def plan_runs(t: dict) -> dict:
    """Worst-case runs and chargeable items per step."""
    n_brands = len(t["brands"])
    if t.get("post_urls"):
        n_scan = n_posts = len(t["post_urls"])
    else:
        n_scan, n_posts = n_brands * t["scan_posts_per_brand"], n_brands * t["max_posts_per_brand"]
    return {"profile": {"runs": 1, "items": n_brands},
            "posts": {"runs": 1, "items": n_scan},
            "comments": {"runs": n_posts, "items": n_posts * t["max_comments_per_post"]}}


def run_cost(t: dict, step: str, items: int, runs: int = 1) -> float:
    fee = float((t.get("start_fee_usd") or {}).get(step, 0) or 0)
    return items / 1000 * float(t["price_per_1k"][step]) + runs * fee


def estimate_cost(t: dict, plan: dict | None = None) -> dict:
    plan = plan or plan_runs(t)
    est = {s: round(run_cost(t, s, plan[s]["items"], plan[s]["runs"]), 4) for s in STEPS}
    est["total"] = round(sum(est[s] for s in STEPS), 4)
    return est


def check_budget(spent: float, cost: float, budget: float) -> None:
    if spent + cost > budget + 1e-9:
        raise BudgetExceeded(f"spent ${spent:.2f} + next ${cost:.2f} = ${spent + cost:.2f} > budget ${budget:.2f}")


def spent_so_far(log_path: Path) -> float:
    """Sum of real usage (else the run's cap) over runs.jsonl — dry runs count too (same credit)."""
    if not log_path.exists():
        return 0.0
    rows = [json.loads(line) for line in log_path.read_text("utf-8").splitlines() if line.strip()]
    return sum(r["usage_usd"] if r.get("usage_usd") is not None else r["est_cost"] for r in rows)


def print_plan(t: dict, label: str) -> dict:
    plan, est = plan_runs(t), estimate_cost(t)
    print(f"{label} cost plan (worst case, price per 1k results + start fees):")
    for s in STEPS:
        print(f"  {s:9s} {plan[s]['runs']:3d} run(s) × ≤{plan[s]['items']:5d} items  ${est[s]:.2f}")
    print(f"  total     ${est['total']:.2f}  (budget ${t['max_budget_usd']:.2f})")
    return est


def _status(run) -> str:
    s = getattr(run, "status", None)
    return str(getattr(s, "value", s) or "")


def run_actor(client, t: dict, step: str, run_input: dict, max_items: int, log_path: Path, *, dry: bool) -> dict:
    """One capped actor run → raw wrapper {actor, run_id, collected_at, items}; logged to runs.jsonl."""
    actor = t["actors"][step]
    cap = run_cost(t, step, max_items)
    check_budget(spent_so_far(log_path), cap, t["max_budget_usd"])
    run = client.actor(actor).call(run_input=run_input, max_items=max_items,
                                   max_total_charge_usd=Decimal(str(round(max(cap, 0.01), 4))))
    if run is None:
        raise RuntimeError(f"{actor}: no run returned")
    items = list(client.dataset(run.default_dataset_id).iterate_items()) if _status(run) == "SUCCEEDED" else []
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "step": step, "actor": actor, "run_id": run.id,
           "status": _status(run), "items": len(items), "est_cost": round(cap, 4),
           "usage_usd": getattr(run, "usage_total_usd", None), "dry": dry}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"  {step:9s} run {run.id}: {rec['status']}, {len(items)} items, ≤${cap:.3f}", flush=True)
    if rec["status"] != "SUCCEEDED":
        raise RuntimeError(f"{actor} run {run.id} ended {rec['status']}")
    return {"actor": actor, "run_id": run.id, "collected_at": rec["ts"], "items": items}


def _save(path: Path, raw: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False), "utf-8")
    tmp.replace(path)


def remaining_cost(t: dict, apify_dir: Path) -> float:
    plan = plan_runs(t)
    cost = 0.0
    if not (apify_dir / "profiles.json").exists():
        cost += run_cost(t, "profile", plan["profile"]["items"])
    if not (apify_dir / "posts.json").exists():
        cost += run_cost(t, "posts", plan["posts"]["items"])
        n_todo = plan["comments"]["runs"]
    else:
        kept = filter_posts(read_raw(apify_dir / "posts.json")["items"], t)
        n_todo = sum(not (apify_dir / "comments" / f"{i['shortCode']}.json").exists() for i in kept)
    return cost + run_cost(t, "comments", n_todo * t["max_comments_per_post"], n_todo)


def scrape(t: dict, client, base: Path, log_path: Path, *, dry: bool = False) -> tuple:
    apify_dir = base / "apify"
    print_plan(t, "dry-run" if dry else "full-run")
    spent, todo = spent_so_far(log_path), remaining_cost(t, apify_dir)
    print(f"  already spent ${spent:.2f}; remaining worst case ${todo:.2f}")
    check_budget(spent, todo, t["max_budget_usd"])

    handles = [b["instagram"] for b in t["brands"]]
    if not (apify_dir / "profiles.json").exists():
        _save(apify_dir / "profiles.json", run_actor(client, t, "profile", {"usernames": handles},
                                                     len(handles), log_path, dry=dry))
    if not (apify_dir / "posts.json").exists():
        n = plan_runs(t)["posts"]["items"]
        inp = ({"username": t["post_urls"]} if t.get("post_urls") else
               {"username": handles, "resultsLimit": t["scan_posts_per_brand"],
                "onlyPostsNewerThan": str(t["since"]), "skipPinnedPosts": True})
        _save(apify_dir / "posts.json", run_actor(client, t, "posts", inp, n, log_path, dry=dry))
    kept = filter_posts(read_raw(apify_dir / "posts.json")["items"], t)
    print(f"  kept {len(kept)} posts after since/keyword/cap filter")
    k = t["max_comments_per_post"]
    for i, post in enumerate(kept, 1):
        path = apify_dir / "comments" / f"{post['shortCode']}.json"
        if path.exists():
            continue
        print(f"  [{i}/{len(kept)}] comments for {post['url']}")
        _save(path, run_actor(client, t, "comments", {"directUrls": [post["url"]], "resultsLimit": k,
                                                      "includeNestedComments": False}, k, log_path, dry=dry))
    posts, comments, info = build_tables(apify_dir, t)
    write_tables(base, posts, comments, info)
    print(f"mapped {len(posts)} posts, {len(comments)} comments → {base}  (spent ≈ ${spent_so_far(log_path):.2f})")
    return posts, comments


def main() -> None:
    p = parser("Scrape Instagram via Apify")
    p.set_defaults(dataset="real")
    p.add_argument("--dry-run", action="store_true", help="1 brand, 2 posts, 20 comments → data/raw/real/dry/")
    p.add_argument("--estimate", action="store_true", help="print the cost plan for full and dry runs; no network")
    args = p.parse_args()
    if args.dataset != "real":
        p.error("scrape_apify only writes the real dataset")
    setup_logging()
    t = load_targets()
    base = raw_dir("real")
    log_path = base / "runs.jsonl"
    if args.estimate:
        for label, tt in (("full-run", t), ("dry-run", dry_targets(t))):
            est = print_plan(tt, label)
            print(f"  → {'OK' if est['total'] <= t['max_budget_usd'] else 'OVER BUDGET (would abort)'}\n")
        print(f"already spent (runs.jsonl): ${spent_so_far(log_path):.2f}")
        return

    from app.config import settings
    if not settings.apify_token:
        raise SystemExit("APIFY_TOKEN is not set (env or .env)")
    from apify_client import ApifyClient
    client = ApifyClient(settings.apify_token)
    if args.dry_run:
        posts, comments = scrape(dry_targets(t), client, base / "dry", log_path, dry=True)
        import pandas as pd
        with pd.option_context("display.max_colwidth", 60, "display.width", 200):
            print(posts[["post_id", "brand", "posted_at", "content_type", "campaign", "infer_method", "likes"]])
            print(comments[["comment_id", "post_id", "user_hash", "text", "created_at"]].head(20))
    else:
        scrape(t, client, base, log_path)


if __name__ == "__main__":
    main()
