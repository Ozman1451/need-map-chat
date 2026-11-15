"""Fallback (SPEC §4.3): import hand-collected posts/comments CSVs into data/raw/real/.

posts.csv    required: post_id, brand, url, posted_at, caption
             optional: likes, comments_count, content_type, campaign, collected_at
comments.csv required: comment_id, post_id, username (hashed, then dropped) or user_hash, text
             optional: created_at, collected_at
Missing content_type / campaign are inferred (llm.infer_posts). Rows merge into any existing real
tables (same id → the CSV row wins). source=manual, is_synthetic=0.
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from _cli import parser, raw_dir, setup_logging
from map_apify import COMMENT_COLS, POST_COLS, hash_user, infer_columns, utc

POST_REQ = ["post_id", "brand", "url", "posted_at", "caption"]
COMMENT_REQ = ["comment_id", "post_id", "text"]


def _require(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df]
    if missing:
        raise ValueError(f"{name}: missing required columns {missing}")


def _ts(series: pd.Series, default) -> pd.Series:
    return series.map(lambda v: utc(v) if pd.notna(v) and str(v).strip() else default)


def prepare_posts(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    _require(df, POST_REQ, "posts.csv")
    df = df.copy()
    df["post_id"] = df["post_id"].astype(str)
    for c in POST_COLS:
        if c not in df:
            df[c] = None
    df["posted_at"] = _ts(df["posted_at"], pd.NaT)
    df["collected_at"] = _ts(df["collected_at"], now)
    df["likes"] = pd.to_numeric(df["likes"], errors="coerce").astype(float)
    df["comments_count"] = pd.to_numeric(df["comments_count"], errors="coerce").astype("Int64")
    df["caption"] = df["caption"].fillna("").astype(str)
    for c in ("content_type", "campaign"):
        df[c] = df[c].where(df[c].notna() & df[c].astype(str).str.strip().ne(""), None)
    df["infer_method"] = "given"
    df = df.assign(source="manual", is_synthetic=0, apify_actor=None, apify_run_id=None)
    return infer_columns(df[POST_COLS])


def prepare_comments(df: pd.DataFrame, posts: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    _require(df, COMMENT_REQ, "comments.csv")
    if "username" not in df and "user_hash" not in df:
        raise ValueError("comments.csv: needs a username or user_hash column")
    df = df.copy()
    df["comment_id"], df["post_id"] = df["comment_id"].astype(str), df["post_id"].astype(str)
    if "username" in df:
        df["user_hash"] = df["username"].map(lambda u: hash_user(u) if pd.notna(u) else None)
        df = df.drop(columns="username")
    for c in COMMENT_COLS:
        if c not in df:
            df[c] = None
    df["created_at"] = _ts(df["created_at"], pd.NaT)
    df["collected_at"] = _ts(df["collected_at"], now)
    df["text"] = df["text"].fillna("").astype(str)
    df["url"] = df["post_id"].map(posts.set_index("post_id")["url"])
    df = df.assign(is_synthetic=0, true_need=None, source="manual", apify_actor=None, apify_run_id=None)
    unknown = ~df["post_id"].isin(posts["post_id"])
    if unknown.any():
        print(f"import_csv: dropping {int(unknown.sum())} comments whose post_id is not in the posts")
    return df.loc[~unknown, COMMENT_COLS]


def merge(out: Path, name: str, new: pd.DataFrame, key: str) -> pd.DataFrame:
    path = out / f"{name}.parquet"
    if path.exists():
        new = pd.concat([pd.read_parquet(path), new], ignore_index=True)
    return new.drop_duplicates(key, keep="last").reset_index(drop=True)


def import_csv(posts_csv: Path, comments_csv: Path, out: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    now = pd.Timestamp(datetime.now(timezone.utc)).floor("s")
    new_posts = prepare_posts(pd.read_csv(posts_csv), now)
    all_posts = merge(out, "posts", new_posts, "post_id")
    new_comments = prepare_comments(pd.read_csv(comments_csv), all_posts, now)
    all_comments = merge(out, "comments", new_comments, "comment_id")
    out.mkdir(parents=True, exist_ok=True)
    all_posts.to_parquet(out / "posts.parquet", index=False)
    all_comments.to_parquet(out / "comments.parquet", index=False)
    print(f"import_csv: +{len(new_posts)} posts, +{len(new_comments)} comments → "
          f"{len(all_posts)} posts, {len(all_comments)} comments in {out}")
    return all_posts, all_comments


def main() -> None:
    p = parser("Import hand-collected CSV into real")
    p.set_defaults(dataset="real")
    p.add_argument("--posts", type=Path, required=True)
    p.add_argument("--comments", type=Path, required=True)
    args = p.parse_args()
    if args.dataset != "real":
        p.error("import_csv only writes the real dataset")
    setup_logging()
    import_csv(args.posts, args.comments, raw_dir("real"))


if __name__ == "__main__":
    main()
