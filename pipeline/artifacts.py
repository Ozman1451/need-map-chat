"""Step 7: copy tables to artifacts/<ds>/ and write manifest.json; print the metrics table."""
import json
import shutil
from datetime import datetime, timezone

import pandas as pd

from _cli import artifacts_dir, parser, processed_dir
from app import embeddings, llm
from app.config import settings

TABLES = ["posts.parquet", "comments.parquet", "comment_tags.parquet", "comment_clusters.parquet",
          "clusters.json", "metrics.json"]


def build_manifest(dataset: str, posts: pd.DataFrame, comments: pd.DataFrame, metrics: dict) -> dict:
    brand = comments["post_id"].map(posts.set_index("post_id")["brand"])
    models = ({k: "mock" for k in ("chat", "batch")} if llm.is_mock() else
              {k: getattr(settings, f"gemini_{k}_model") or None for k in ("chat", "batch")})
    models["embed"] = embeddings.model_label()
    return {"dataset": dataset, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "is_synthetic": bool(comments["is_synthetic"].astype(bool).all()) if len(comments) else None,
            "counts": {"posts": len(posts), "comments": len(comments), "clustered": metrics["n"],
                       "by_brand": {str(k): int(v) for k, v in brand.value_counts().items()}},
            "k": {a: v["k"] for a, v in metrics["algorithms"].items()},
            "dbscan": metrics["dbscan"], "primary": "kmeans", "models": models,
            "embedding": {"backend": embeddings.backend(), "model": models["embed"], "dims": 768,
                          "text": "gloss (raw text embedded too, for comparison)",
                          "prefix": embeddings.PREFIX if embeddings.backend() == "local" else None}}


def metrics_table(m: dict) -> str:
    cols = ["k", "silhouette", "davies_bouldin", "stability_ari", "ari_true"]
    head = f"{'algo':<8}{'k':>4}{'silhouette':>12}{'DB':>8}{'stab ARI':>10}{'ARI true':>10}"
    fmt = lambda v: "—" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)  # noqa: E731
    rows = [f"{a:<8}" + "".join(f"{fmt(v.get(c)):>{w}}" for c, w in zip(cols, (4, 12, 8, 10, 10)))
            for a, v in m["algorithms"].items()]
    return "\n".join([head, *rows])


def main() -> None:
    args = parser("Step 7: write artifacts").parse_args()
    src, dst = processed_dir(args.dataset), artifacts_dir(args.dataset)
    for t in TABLES:
        shutil.copy2(src / t, dst / t)
    metrics = json.loads((src / "metrics.json").read_text())
    manifest = build_manifest(args.dataset, pd.read_parquet(src / "posts.parquet"),
                              pd.read_parquet(src / "comments.parquet"), metrics)
    (dst / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"artifacts [{args.dataset}] → {dst}\n{metrics_table(metrics)}")


if __name__ == "__main__":
    main()
