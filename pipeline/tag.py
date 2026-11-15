"""Step 2: Gemini tagging → comment_tags.parquet. 50 comments/call, cached, resume-safe
(already-tagged ids are skipped; progress is saved after every call)."""
import pandas as pd

from _cli import parser, processed_dir, setup_logging
from app import llm

TAG_COLS = ["comment_id", "sentiment", "purchase_intent", "language_type", "city", "gloss"]


def finalize_tags(tags: pd.DataFrame, comments: pd.DataFrame) -> pd.DataFrame:
    """Order like comments, keep only known ids, fall back to the raw text for an empty gloss."""
    tags = tags.drop_duplicates("comment_id", keep="last")
    out = comments[["comment_id", "text"]].merge(tags, on="comment_id", how="inner")
    empty = out["gloss"].fillna("").str.strip() == ""
    out.loc[empty, "gloss"] = out.loc[empty, "text"]
    out["city"] = out["city"].where(out["city"].fillna("").str.strip().str.lower().ne("") &
                                    out["city"].fillna("").str.lower().ne("null"))
    return out[TAG_COLS].reset_index(drop=True)


def main() -> None:
    args = parser("Step 2: Gemini tagging").parse_args()
    setup_logging()
    d = processed_dir(args.dataset)
    comments = pd.read_parquet(d / "comments.parquet")
    path = d / "comment_tags.parquet"
    done = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=TAG_COLS)
    todo = comments[~comments["comment_id"].isin(done["comment_id"])]
    rows = todo[["comment_id", "text"]].to_dict("records")
    print(f"tag [{args.dataset}]: {len(done)} already tagged, {len(rows)} to tag")
    parts = [done]
    for i in range(0, len(rows), llm.TAG_BATCH):
        parts.append(pd.DataFrame(llm.tag_batch(rows[i:i + llm.TAG_BATCH], dataset=args.dataset)))
        finalize_tags(pd.concat(parts), comments).to_parquet(path, index=False)
        n = min(i + llm.TAG_BATCH, len(rows))
        if n % 500 < llm.TAG_BATCH or n == len(rows):
            print(f"  tagged {n}/{len(rows)}", flush=True)
    tags = finalize_tags(pd.concat(parts), comments)
    tags.to_parquet(path, index=False)
    print(f"tag [{args.dataset}]: {len(tags)} rows; languages {tags['language_type'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
