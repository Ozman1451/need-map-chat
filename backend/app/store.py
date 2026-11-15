"""In-memory store over artifacts/<dataset>/ (one dataset loaded at a time, switchable)."""
import json
import threading
from pathlib import Path

import pandas as pd

from .config import settings

ALGOS = ["kmeans", "ward", "dbscan", "gmm"]
PREFIX = {"kmeans": "C", "ward": "W", "dbscan": "D", "gmm": "G"}  # label n → "C3"; DBSCAN noise −1 → "D0"
ALGO_OF = {v: k for k, v in PREFIX.items()}
FILES = ["manifest.json", "clusters.json", "metrics.json", "posts.parquet", "comments.parquet",
         "comment_tags.parquet", "comment_clusters.parquet"]


class Store:
    def __init__(self) -> None:
        self.dataset: str | None = None
        self.root: Path = settings.artifacts_dir
        self.manifest: dict = {}
        self.metrics: dict = {}
        self.clusters: dict[str, dict] = {}
        self.df: pd.DataFrame = pd.DataFrame()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ loading
    def available(self) -> dict[str, dict]:
        """Datasets with complete artifacts → their manifest counts."""
        out = {}
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()) if self.root.exists() else []:
            if all((d / f).exists() for f in FILES):
                m = json.loads((d / "manifest.json").read_text())
                out[d.name] = {**m.get("counts", {}), "is_synthetic": m.get("is_synthetic")}
        return out

    def load(self, dataset: str | None = None, root: Path | None = None) -> None:
        dataset = dataset or settings.dataset
        root = Path(root) if root else self.root
        a = root / dataset
        missing = [f for f in FILES if not (a / f).exists()]
        if missing:
            raise FileNotFoundError(f"artifacts/{dataset} incomplete (missing {', '.join(missing)}); "
                                    f"run `make pipeline DATASET={dataset}`")
        posts = pd.read_parquet(a / "posts.parquet")[["post_id", "brand", "campaign", "content_type", "url"]]
        df = (pd.read_parquet(a / "comment_clusters.parquet")
              .merge(pd.read_parquet(a / "comments.parquet")[["comment_id", "post_id", "text"]], on="comment_id")
              .merge(pd.read_parquet(a / "comment_tags.parquet"), on="comment_id", how="left")
              .merge(posts, on="post_id", how="left"))
        for algo in ALGOS:  # integer labels → cluster ids used in clusters.json
            df[f"{algo}_id"] = PREFIX[algo] + df[algo].clip(lower=0).astype(int).astype(str)
        with self._lock:
            self.root, self.dataset = root, dataset
            self.df = df.reset_index(drop=True)
            self.manifest = json.loads((a / "manifest.json").read_text())
            self.metrics = json.loads((a / "metrics.json").read_text())
            self.clusters = {c["cluster_id"]: c for c in json.loads((a / "clusters.json").read_text())}

    def ensure(self) -> "Store":
        if self.dataset is None:
            self.load()
        return self

    # ------------------------------------------------------------ helpers
    def options(self) -> dict[str, list[str]]:
        d = self.ensure().df
        return {"brand": sorted(d["brand"].dropna().unique()), "campaign": sorted(d["campaign"].dropna().unique()),
                "content_type": sorted(d["content_type"].dropna().unique())}

    def top_level(self, algo: str) -> list[dict]:
        return [c for c in self.clusters.values() if c["algo"] == algo and not c["parent_id"]]

    def children(self, cluster_id: str) -> list[dict]:
        return [c for c in self.clusters.values() if c["parent_id"] == cluster_id]


store = Store()
