"""Generate the synthetic dataset (SPEC §4.2): posts + Gemini-written comments with a hidden need.

python pipeline/seed_synthetic.py [--posts 60 --comments 2500 --odd 40] [--show 12] [--make-sample]
"""
from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from _cli import ROOT, parser, raw_dir
from app import llm

BRANDS = ["Sapphire", "Khaadi", "Gul Ahmed"]
CAMPAIGNS = ["Eid", "11.11", "12.12", "Summer Lawn", "Winter", "Regular"]
CAMPAIGN_P = [0.2, 0.12, 0.13, 0.22, 0.11, 0.22]
CONTENT_TYPES = ["Reel", "Product Photo", "Carousel", "Influencer", "Sale Announcement", "Other"]
BATCH = 25

BASE = {"price_inquiry": 14, "discount_request": 6, "delivery_time": 9, "availability_city": 8,
        "size_fit": 8, "fabric_quality": 8, "compliment": 18, "order_complaint": 6,
        "inbox_request": 12, "purchase_intent": 11}
CAMPAIGN_BOOST = {
    "12.12": {"discount_request": 3.5, "price_inquiry": 1.5},
    "11.11": {"discount_request": 3.0, "price_inquiry": 1.5, "order_complaint": 1.4},
    "Eid": {"delivery_time": 2.5, "availability_city": 1.8, "purchase_intent": 1.6, "order_complaint": 1.5},
    "Summer Lawn": {"fabric_quality": 2.2, "size_fit": 1.6, "price_inquiry": 1.2},
    "Winter": {"fabric_quality": 2.0, "size_fit": 1.4},
}
CONTENT_BOOST = {
    "Influencer": {"compliment": 2.0, "purchase_intent": 1.3},
    "Sale Announcement": {"discount_request": 1.8, "price_inquiry": 1.3},
    "Product Photo": {"fabric_quality": 1.3, "size_fit": 1.3, "price_inquiry": 1.2},
    "Reel": {"compliment": 1.4},
}
CAPTIONS = {
    "Eid": ["Eid Collection '25 is live — festive lawn in jewel tones ✨", "Celebrate Eid in hand-embellished luxe lawn"],
    "11.11": ["11.11 Sale: flat 30% off sitewide, today only!", "The 11.11 drop you waited for — prices slashed"],
    "12.12": ["12.12 MEGA SALE up to 50% off 🛍️", "12.12 is here: unstitched 3-piece suits from Rs 2,990"],
    "Summer Lawn": ["Summer Lawn Vol 2 — breathable digital-print 3-piece", "Florals for the Lahore heat 🌸 New lawn"],
    "Winter": ["Winter Khaddar & Karandi collection out now", "Cosy embroidered linen for chilly evenings"],
    "Regular": ["New arrivals in-store and online", "Pret essentials: everyday kurtas you'll love"],
}
CAMPAIGN_MONTH = {"Eid": (3, 6), "11.11": (11, 11), "12.12": (12, 12), "Summer Lawn": (2, 5),
                  "Winter": (10, 12), "Regular": (1, 12)}


def need_weights(campaign: str, content_type: str) -> dict[str, float]:
    w = dict(BASE)
    for boost in (CAMPAIGN_BOOST.get(campaign, {}), CONTENT_BOOST.get(content_type, {})):
        for k, f in boost.items():
            w[k] *= f
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}


def make_posts(n: int, rng: np.random.Generator) -> pd.DataFrame:
    collected = datetime.now(timezone.utc).replace(microsecond=0)
    rows = []
    for i in range(n):
        campaign = CAMPAIGNS[i % len(CAMPAIGNS)] if i < len(CAMPAIGNS) else rng.choice(CAMPAIGNS, p=CAMPAIGN_P)
        ct_p = np.array([0.25, 0.22, 0.18, 0.13, 0.12, 0.10])
        if campaign in ("11.11", "12.12"):
            ct_p[4] += 0.35
        content_type = rng.choice(CONTENT_TYPES, p=ct_p / ct_p.sum())
        lo, hi = CAMPAIGN_MONTH[campaign]
        posted = datetime(2025, int(rng.integers(lo, hi + 1)), int(rng.integers(1, 28)), int(rng.integers(9, 23)),
                          tzinfo=timezone.utc)
        if campaign in ("11.11", "12.12"):
            posted = posted.replace(day=int(campaign.split(".")[0]))
        pid = f"P{i:03d}"
        rows.append({"post_id": pid, "brand": BRANDS[i % 3], "url": f"https://www.instagram.com/p/SYN{pid}/",
                     "posted_at": posted, "collected_at": collected, "campaign": campaign,
                     "content_type": content_type, "caption": str(rng.choice(CAPTIONS[campaign])),
                     "likes": int(rng.lognormal(8.0, 0.7)), "comments_count": 0,
                     "source": "synthetic", "is_synthetic": 1})
    return pd.DataFrame(rows)


def plan_calls(posts: pd.DataFrame, total: int, n_odd: int, rng: np.random.Generator) -> list[tuple[str, list[dict]]]:
    """→ [(need, slots≤25)], each slot = post metadata + count."""
    w = np.sqrt(posts["likes"].to_numpy(float))
    counts = np.maximum(rng.multinomial(total, w / w.sum()), 8)
    demand: dict[str, list[tuple[dict, int]]] = {n: [] for n in llm.NEEDS + ["off_topic"]}
    meta = posts[["post_id", "brand", "campaign", "content_type", "caption"]].to_dict("records")
    for m, c in zip(meta, counts):
        nw = need_weights(m["campaign"], m["content_type"])
        for need, k in zip(nw, rng.multinomial(c, list(nw.values()))):
            if k:
                demand[need].append((m, int(k)))
    for m, k in zip(meta, rng.multinomial(n_odd, [1 / len(meta)] * len(meta))):
        if k:
            demand["off_topic"].append((m, int(k)))
    calls = []
    for need, items in demand.items():
        order = rng.permutation(len(items))
        slots, room = [], BATCH
        for j in order:
            m, k = items[j]
            while k:
                take = min(k, room)
                slots.append({**m, "count": take})
                k, room = k - take, room - take
                if room == 0:
                    calls.append((need, slots))
                    slots, room = [], BATCH
        if slots:
            calls.append((need, slots))
    return calls


def run_calls(calls, dataset: str, workers: int) -> list[dict]:
    def one(i_call):
        i, (need, slots) = i_call
        wanted = {s["post_id"]: s["count"] for s in slots}
        got = llm.generate_comments(need, slots, dataset=dataset)
        rows = []
        for c in got:
            pid, text = c.get("post_id"), " ".join(str(c.get("text", "")).split())
            if text and wanted.get(pid, 0) > 0:
                wanted[pid] -= 1
                rows.append({"post_id": pid, "text": text, "true_need": need})
        print(f"  [{i + 1}/{len(calls)}] {need:18s} {len(rows)}/{sum(s['count'] for s in slots)}", flush=True)
        return rows
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return [r for rows in ex.map(one, enumerate(calls)) for r in rows]


def build_comments(rows: list[dict], posts: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df[~df.assign(t=df["text"].str.lower()).duplicated(["post_id", "t"])].reset_index(drop=True)
    posted = posts.set_index("post_id")["posted_at"]
    n = len(df)
    handles = [f"user_{x}" for x in rng.integers(0, max(n * 0.8, 1), size=n)]
    df["comment_id"] = [f"c{i:05d}" for i in range(n)]
    df["user_hash"] = [hashlib.sha256(h.encode()).hexdigest() for h in handles]
    df["created_at"] = [posted[p] + timedelta(hours=float(h)) for p, h in zip(df["post_id"], rng.exponential(30, n))]
    df["is_synthetic"] = 1
    return df[["comment_id", "post_id", "user_hash", "text", "created_at", "is_synthetic", "true_need"]]


def make_sample(src: Path, dst: Path, n: int = 200, seed: int = 0) -> None:
    comments, posts = pd.read_parquet(src / "comments.parquet"), pd.read_parquet(src / "posts.parquet")
    odd = comments[comments["true_need"] == "off_topic"]
    n_odd = min(len(odd), 12)
    rest = comments[comments["true_need"] != "off_topic"]
    picked = rest.groupby("true_need").sample(frac=(n - n_odd) / len(rest), random_state=seed)
    picked = pd.concat([picked, odd.sample(n_odd, random_state=seed)])
    short = n - len(picked)  # frac rounding per group → top up / trim to exactly n
    if short > 0:
        picked = pd.concat([picked, rest.drop(picked.index, errors="ignore").sample(short, random_state=seed)])
    picked = picked.sample(n, random_state=seed)
    picked = picked.sort_values("comment_id").reset_index(drop=True)
    p = posts[posts["post_id"].isin(picked["post_id"])].copy()
    p["comments_count"] = p["post_id"].map(picked["post_id"].value_counts()).astype(int)
    dst.mkdir(parents=True, exist_ok=True)
    picked.to_parquet(dst / "comments.parquet", index=False)
    p.to_parquet(dst / "posts.parquet", index=False)
    print(f"sample → {dst}: {len(picked)} comments, {len(p)} posts")


def main() -> None:
    ap = parser("Generate synthetic dataset")
    ap.add_argument("--posts", type=int, default=60)
    ap.add_argument("--comments", type=int, default=2500)
    ap.add_argument("--odd", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--show", type=int, default=0, help="print N random comments")
    ap.add_argument("--make-sample", action="store_true", help="write data/sample/ from existing synthetic data")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "google_genai", "google.genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    out = args.out or raw_dir(args.dataset)

    if args.make_sample:
        make_sample(out, ROOT / "data" / "sample")
        return

    rng = np.random.default_rng(args.seed)
    posts = make_posts(args.posts, rng)
    calls = plan_calls(posts, args.comments, args.odd, rng)
    print(f"seed_synthetic [{args.dataset}]: {len(posts)} posts, {len(calls)} generation calls"
          f"{' (MOCK_LLM)' if llm.is_mock() else ''}")
    comments = build_comments(run_calls(calls, args.dataset, args.workers), posts, rng)
    posts["comments_count"] = posts["post_id"].map(comments["post_id"].value_counts()).fillna(0).astype(int)

    out.mkdir(parents=True, exist_ok=True)
    posts.to_parquet(out / "posts.parquet", index=False)
    comments.to_parquet(out / "comments.parquet", index=False)
    print(f"wrote {len(posts)} posts, {len(comments)} comments → {out}")

    share = pd.crosstab(comments["post_id"].map(posts.set_index("post_id")["campaign"]).rename("campaign"),
                        comments["true_need"], normalize="index").round(2)
    print(share.to_string())
    if args.show:
        s = comments.sample(min(args.show, len(comments)), random_state=args.seed)
        s = s.merge(posts[["post_id", "brand", "campaign"]], on="post_id")
        for r in s.itertuples():
            print(f"- [{r.brand} | {r.campaign} | {r.true_need}] {r.text}")


if __name__ == "__main__":
    main()
