"""Top-up scrape for the real dataset (config/targets.yaml → `topup`).

--verify H [H ...]  profile actor only → print handle table (exists, followers, verified, name, bio).
--plan              print scan + comment plan and cost estimate (no actor runs).
(no flag)           scan `topup.brands` (scan_posts_per_brand each, newer than topup.since) once →
                    posts_topup.json; then fetch comments for posts from ALL posts*.json, highest
                    commentsCount first (≥ min_comments_count, not fetched yet), until max_budget_usd;
                    then re-map everything → data/raw/real/{posts,comments}.parquet.
Spend = real Apify usage re-fetched per run (refresh_usage), the run's cap until it is reported.
"""
from pathlib import Path

import pandas as pd

from _cli import parser, raw_dir, setup_logging
from map_apify import build_tables, load_targets, read_raw, utc, write_tables
from scrape_apify import BudgetExceeded, _save, check_budget, refresh_usage, run_actor, run_cost, spent_so_far


def candidates(apify_dir: Path, tu: dict) -> list[dict]:
    """Unfetched posts from all posts*.json since topup.since with commentsCount ≥ min, most-commented first."""
    since, seen, out = pd.Timestamp(tu["since"], tz="UTC"), set(), []
    for f in sorted(apify_dir.glob("posts*.json")):
        for i in read_raw(f)["items"]:
            code = i.get("shortCode")
            if (not code or code in seen or not i.get("url") or not i.get("timestamp")
                    or utc(i["timestamp"]) < since or (i.get("commentsCount") or 0) < tu["min_comments_count"]
                    or (apify_dir / "comments" / f"{code}.json").exists()):
                continue
            seen.add(code)
            out.append(i)
    return sorted(out, key=lambda i: -(i.get("commentsCount") or 0))


def verify(client, t: dict, handles: list[str], apify_dir: Path, log_path: Path) -> None:
    refresh_usage(client, log_path, min_age_s=0)
    n = len(list(apify_dir.glob("profiles_verify*.json"))) + 1
    raw = run_actor(client, t, "profile", {"usernames": handles}, len(handles), log_path, dry=False)
    _save(apify_dir / f"profiles_verify{n}.json", raw)
    got = {(p.get("username") or "").lower(): p for p in raw["items"]}
    rows = []
    for h in handles:
        p = got.get(h.lower(), {})
        rows.append({"handle": h, "found": bool(p) and not p.get("error"), "fullName": p.get("fullName"),
                     "followers": p.get("followersCount"), "verified": p.get("verified"),
                     "bio": (p.get("biography") or "").replace("\n", " ")[:60]})
    with pd.option_context("display.width", 220, "display.max_colwidth", 60):
        print(pd.DataFrame(rows).to_string(index=False))


def plan(t: dict, apify_dir: Path, log_path: Path) -> None:
    tu, k = t["topup"], t["max_comments_per_post"]
    spent = spent_so_far(log_path)
    scan = 0.0 if (apify_dir / "posts_topup.json").exists() else run_cost(
        t, "posts", len(tu["brands"]) * tu["scan_posts_per_brand"])
    per = run_cost(t, "comments", k)
    left = t["max_budget_usd"] - spent - scan
    cands = candidates(apify_dir, tu)
    print(f"spent so far ${spent:.3f} | budget ${t['max_budget_usd']:.2f} | scan {len(tu['brands'])} brands × "
          f"{tu['scan_posts_per_brand']} ≤ ${scan:.3f} | left for comments ${left:.3f} → ≤{int(left // per)} posts "
          f"× {k} (≤${per:.3f} each)")
    print(f"known candidates now (commentsCount ≥ {tu['min_comments_count']}): {len(cands)}")


def topup(client, t: dict, apify_dir: Path, log_path: Path) -> None:
    tu, k = t["topup"], t["max_comments_per_post"]
    refresh_usage(client, log_path, min_age_s=0)
    if not (apify_dir / "posts_topup.json").exists():
        n = len(tu["brands"]) * tu["scan_posts_per_brand"]
        _save(apify_dir / "posts_topup.json", run_actor(
            client, t, "posts", {"username": tu["brands"], "resultsLimit": tu["scan_posts_per_brand"],
                                 "onlyPostsNewerThan": str(tu["since"]), "skipPinnedPosts": True},
            n, log_path, dry=False))
    cands = candidates(apify_dir, tu)
    print(f"  {len(cands)} candidate posts (commentsCount ≥ {tu['min_comments_count']})")
    cap = run_cost(t, "comments", k)
    for i, post in enumerate(cands, 1):
        refresh_usage(client, log_path)
        try:
            check_budget(spent_so_far(log_path), cap, t["max_budget_usd"])
        except BudgetExceeded as e:  # budget used up → stop selecting, keep what we have
            print(f"  stop: {e}")
            break
        print(f"  [{i}/{len(cands)}] {post['ownerUsername']} cc={post.get('commentsCount')} {post['url']}")
        _save(apify_dir / "comments" / f"{post['shortCode']}.json", run_actor(
            client, t, "comments", {"directUrls": [post["url"]], "resultsLimit": k,
                                    "includeNestedComments": False}, k, log_path, dry=False))
    posts, comments, info = build_tables(apify_dir, t)
    write_tables(apify_dir.parent, posts, comments, info)
    refresh_usage(client, log_path, min_age_s=0)
    print(f"mapped {len(posts)} posts, {len(comments)} comments (spent ≈ ${spent_so_far(log_path):.3f})")


def main() -> None:
    p = parser("Top-up Apify scrape for the real dataset")
    p.set_defaults(dataset="real")
    p.add_argument("--verify", nargs="+", metavar="HANDLE", help="profile actor only: check these handles")
    p.add_argument("--plan", action="store_true", help="print the top-up plan and estimate (no actor runs)")
    args = p.parse_args()
    if args.dataset != "real":
        p.error("topup_apify only writes the real dataset")
    setup_logging()
    t = load_targets()
    base = raw_dir("real")
    apify_dir, log_path = base / "apify", base / "runs.jsonl"
    if args.plan:
        return plan(t, apify_dir, log_path)
    from app.config import settings
    from apify_client import ApifyClient
    client = ApifyClient(settings.apify_token)
    if args.verify:
        verify(client, t, args.verify, apify_dir, log_path)
    else:
        topup(client, t, apify_dir, log_path)


if __name__ == "__main__":
    main()
