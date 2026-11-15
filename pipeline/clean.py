"""Step 1: clean comments → data/processed/<ds>/{comments,posts}.parquet.

Drops empty / emoji-only / URL-only comments, normalises whitespace (emojis kept) and removes
exact duplicates within the same post, plus the same user posting the same text on several posts
(copy-paste spam); repeats by different users across posts still carry need frequency.
"""
import re

import pandas as pd

from _cli import parser, processed_dir, raw_dir

URL = re.compile(r"(https?://\S+|www\.\S+)", re.I)
WS = re.compile(r"\s+")


def normalize(text) -> str:
    return WS.sub(" ", str(text or "")).strip()


def has_content(text: str) -> bool:
    """True if anything alphanumeric (any script) remains once URLs are removed."""
    return any(ch.isalnum() for ch in URL.sub(" ", text))


def clean_comments(comments: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = comments.copy()
    df["text"] = df["text"].map(normalize)
    keep = df["text"].map(has_content)
    df = df[keep]
    dup = df.duplicated(["post_id", "text"])
    df = df[~dup]
    rep = df["user_hash"].notna() & df.duplicated(["user_hash", "text"]) if "user_hash" in df else df["text"].isna()
    df = df[~rep].reset_index(drop=True)
    if "true_need" not in df:
        df["true_need"] = None
    stats = {"input": len(comments), "dropped_no_content": int((~keep).sum()),
             "dropped_dup_within_post": int(dup.sum()),
             "dropped_user_repeat": int(rep.sum()), "output": len(df)}
    return df, stats


def main() -> None:
    args = parser("Step 1: clean comments").parse_args()
    src, dst = raw_dir(args.dataset), processed_dir(args.dataset)
    posts = pd.read_parquet(src / "posts.parquet")
    comments, stats = clean_comments(pd.read_parquet(src / "comments.parquet"))
    comments = comments[comments["post_id"].isin(posts["post_id"])]
    comments.to_parquet(dst / "comments.parquet", index=False)
    posts.to_parquet(dst / "posts.parquet", index=False)
    print(f"clean [{args.dataset}]: {stats}")


if __name__ == "__main__":
    main()
