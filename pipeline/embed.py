"""Step 3: embed gloss and raw text separately (all comments), L2-normalised.

Backend from EMBED_BACKEND (default local multilingual-e5-base; gemini optional), see app/embeddings.py.
gloss → emb_gloss.npy + emb_ids.parquet; raw → emb_raw.npy + emb_raw_ids.parquet (= comment_tags order).
Identical strings are embedded once. On the Gemini backend a per-day quota 429 stops cleanly (exit 3).
"""
import sys
import time

import numpy as np
import pandas as pd

from _cli import parser, processed_dir, setup_logging
from app import embeddings, llm


def embed_unique(texts: list[str], embed_fn) -> np.ndarray:
    uniq = list(dict.fromkeys(texts))
    vecs = embed_fn(uniq)
    pos = {t: i for i, t in enumerate(uniq)}
    return vecs[[pos[t] for t in texts]]


def main() -> None:
    p = parser("Step 3: embeddings")
    p.add_argument("--only", choices=["gloss", "raw"], default=None)
    args = p.parse_args()
    setup_logging()
    d = processed_dir(args.dataset)
    tags = pd.read_parquet(d / "comment_tags.parquet")
    text = pd.read_parquet(d / "comments.parquet").set_index("comment_id")["text"]
    ids = tags[["comment_id"]]
    jobs = {"gloss": (tags["gloss"].tolist(), "emb_ids.parquet"),
            "raw": (text.loc[tags["comment_id"]].tolist(), "emb_raw_ids.parquet")}
    fn = lambda xs: embeddings.embed(xs, dataset=args.dataset)  # noqa: E731
    print(f"embed [{args.dataset}]: backend={embeddings.backend()} model={embeddings.model_label()}", flush=True)
    for name in [args.only] if args.only else list(jobs):
        texts, ids_file = jobs[name]
        t0 = time.perf_counter()
        try:
            vecs = embed_unique(texts, fn)
        except llm.DailyQuotaExceeded:
            uniq = list(dict.fromkeys(texts))
            left = llm.embed_pending(uniq, dataset=args.dataset)
            print(f"embed [{args.dataset}] {name}: DAILY QUOTA EXHAUSTED — {left} of {len(uniq)} unique texts "
                  f"remain; rerun later to resume from cache", flush=True)
            sys.exit(3)
        np.save(d / f"emb_{name}.npy", vecs)
        ids.to_parquet(d / ids_file, index=False)
        print(f"embed [{args.dataset}] {name}: {len(texts)} texts ({len(set(texts))} unique) → {vecs.shape} "
              f"in {time.perf_counter() - t0:.1f}s", flush=True)
    print(f"embed [{args.dataset}]: done")


if __name__ == "__main__":
    main()
