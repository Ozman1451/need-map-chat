"""Map raw Apify JSON (data/raw/real/apify/) → data/raw/real/{posts,comments}.parquet (SPEC §4.3).

Raw files are wrappers {actor, run_id, collected_at, items}. Usernames are sha256-hashed here and
every other user field is dropped. content_type = Apify media type, then Gemini (llm.infer_posts)
assigns campaign and may upgrade content_type to Influencer / Sale Announcement; `infer_method` says which.
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

from _cli import ROOT, parser, raw_dir, setup_logging
from app import llm

POST_COLS = ["post_id", "brand", "url", "posted_at", "collected_at", "campaign", "content_type", "caption",
             "likes", "comments_count", "source", "is_synthetic", "apify_actor", "apify_run_id", "infer_method"]
COMMENT_COLS = ["comment_id", "post_id", "user_hash", "text", "created_at", "is_synthetic", "true_need",
                "url", "collected_at", "source", "apify_actor", "apify_run_id"]


def load_targets(path: Path = ROOT / "config" / "targets.yaml") -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text("utf-8"))


def utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def hash_user(name) -> str | None:
    return hashlib.sha256(str(name).strip().lower().encode("utf-8")).hexdigest() if name else None


def media_content_type(item: dict) -> str:
    """Apify post `type` / `productType` → content_type base (Gemini may refine later)."""
    if item.get("productType") == "clips" or item.get("type") == "Video":
        return "Reel"
    return {"Sidecar": "Carousel", "Image": "Product Photo"}.get(item.get("type"), "Other")


def filter_posts(items: list[dict], targets: dict) -> list[dict]:
    """Step B filter: exact post_urls → keep all; else posts after `since` whose caption matches any
    keyword, newest first, capped per brand (owner)."""
    items = [i for i in items if i.get("shortCode") and i.get("url")]
    if targets.get("post_urls"):
        return items
    since = pd.Timestamp(targets["since"], tz="UTC")
    kws = [k.lower() for k in targets.get("caption_keywords") or []]
    keep = [i for i in items if i.get("timestamp") and utc(i["timestamp"]) >= since
            and (not kws or any(k in (i.get("caption") or "").lower() for k in kws))]
    keep.sort(key=lambda i: utc(i["timestamp"]), reverse=True)
    per: dict[str, int] = {}
    out = []
    for i in keep:
        owner = (i.get("ownerUsername") or "").lower()
        if per.get(owner, 0) < targets["max_posts_per_brand"]:
            per[owner] = per.get(owner, 0) + 1
            out.append(i)
    return out


def brand_map(targets: dict) -> dict[str, str]:
    return {b["instagram"].lower(): b["name"] for b in targets["brands"]}


def map_posts(raw: dict, items: list[dict], brands: dict[str, str]) -> pd.DataFrame:
    rows = []
    for i in items:
        likes = i.get("likesCount")
        rows.append({
            "post_id": i["shortCode"], "brand": brands.get((i.get("ownerUsername") or "").lower(),
                                                           i.get("ownerUsername") or "unknown"),
            "url": i["url"], "posted_at": utc(i["timestamp"]),
            "collected_at": utc(raw["collected_at"]), "campaign": None,
            "content_type": media_content_type(i), "caption": i.get("caption") or "",
            "likes": float(likes) if likes is not None and likes >= 0 else float("nan"),
            "comments_count": i.get("commentsCount"), "source": "apify", "is_synthetic": 0,
            "apify_actor": raw["actor"], "apify_run_id": raw["run_id"], "infer_method": "media_type"})
    return pd.DataFrame(rows, columns=POST_COLS)


def map_comments(raw: dict, post: dict) -> pd.DataFrame:
    """One comment-actor run per post → rows; top-level comments only (replies dropped)."""
    rows, seen = [], set()
    for c in raw["items"]:
        cid = str(c.get("id") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ts = c.get("timestamp")
        rows.append({"comment_id": cid, "post_id": post["post_id"], "user_hash": hash_user(c.get("ownerUsername")),
                     "text": c.get("text") or "", "created_at": utc(ts) if ts else pd.NaT,
                     "is_synthetic": 0, "true_need": None, "url": post["url"],
                     "collected_at": utc(raw["collected_at"]), "source": "apify",
                     "apify_actor": raw["actor"], "apify_run_id": raw["run_id"]})
    return pd.DataFrame(rows, columns=COMMENT_COLS)


def infer_columns(posts: pd.DataFrame, *, dataset: str = "real") -> pd.DataFrame:
    """Fill missing campaign / refine content_type via llm.infer_posts. Rows that already have both
    (manual CSV) are left alone. `infer_method`: <content_type source>+<campaign source>."""
    posts = posts.copy()
    todo = posts["campaign"].isna() | posts["content_type"].isna()
    if not todo.any():
        return posts
    who = "rules" if llm.is_mock() else "gemini"
    sub = posts[todo]
    got = llm.infer_posts([{"post_id": r.post_id, "caption": r.caption, "posted_at": r.posted_at,
                            "media": r.content_type or ""} for r in sub.itertuples()], dataset=dataset)
    for idx, g in zip(sub.index, got):
        base, base_src = posts.at[idx, "content_type"], posts.at[idx, "infer_method"] or "media_type"
        ct_src = base_src if isinstance(base, str) and base else who
        if g.get("content_type") and ct_src != "given":  # never override a hand-entered type
            posts.at[idx, "content_type"], ct_src = g["content_type"], who
        elif ct_src == who:
            posts.at[idx, "content_type"] = "Other"
        camp_src = "given" if isinstance(posts.at[idx, "campaign"], str) else who
        if camp_src == who:
            posts.at[idx, "campaign"] = g["campaign"]
        posts.at[idx, "infer_method"] = ct_src if ct_src == camp_src else f"{ct_src}+{camp_src}"
    return posts


def read_raw(path: Path) -> dict:
    return json.loads(Path(path).read_text("utf-8"))


def build_tables(apify_dir: Path, targets: dict, *, dataset: str = "real") -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """Raw JSON → (posts, comments, brands). Only kept posts that have a comments file are mapped."""
    apify_dir = Path(apify_dir)
    brands = brand_map(targets)
    info = []
    if (apify_dir / "profiles.json").exists():
        for p in read_raw(apify_dir / "profiles.json")["items"]:
            h = (p.get("username") or "").lower()
            info.append({"brand": brands.get(h, h), "instagram": h, "followers": p.get("followersCount")})
    raw_posts = read_raw(apify_dir / "posts.json")
    kept = [i for i in filter_posts(raw_posts["items"], targets)
            if (apify_dir / "comments" / f"{i['shortCode']}.json").exists()]
    posts = infer_columns(map_posts(raw_posts, kept, brands), dataset=dataset)
    frames = [map_comments(read_raw(apify_dir / "comments" / f"{p['post_id']}.json"), p)
              for p in posts.to_dict("records")]
    comments = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COMMENT_COLS)
    comments = comments.drop_duplicates("comment_id").reset_index(drop=True)
    posts["comments_count"] = posts["comments_count"].astype("Int64")
    return posts, comments, info


def write_tables(out_dir: Path, posts: pd.DataFrame, comments: pd.DataFrame, info: list) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    posts.to_parquet(out_dir / "posts.parquet", index=False)
    comments.to_parquet(out_dir / "comments.parquet", index=False)
    (out_dir / "brands.json").write_text(json.dumps(info, indent=1), "utf-8")


def main() -> None:
    p = parser("Map raw Apify JSON → posts/comments parquet")
    p.set_defaults(dataset="real")
    p.add_argument("--dry", action="store_true", help="map the dry-run folder (data/raw/real/dry/)")
    args = p.parse_args()
    if args.dataset != "real":
        p.error("map_apify only writes the real dataset")
    setup_logging()
    base = raw_dir("real") / ("dry" if args.dry else "")
    posts, comments, info = build_tables(base / "apify", load_targets())
    write_tables(base, posts, comments, info)
    print(f"map_apify: {len(posts)} posts, {len(comments)} comments → {base}")


if __name__ == "__main__":
    main()
