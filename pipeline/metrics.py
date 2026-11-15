"""Step 6: metrics per algorithm + raw-vs-gloss comparison → data/processed/<ds>/metrics.json.

Internal: silhouette, Davies–Bouldin, Calinski–Harabasz (DBSCAN: noise excluded).
Stability: mean ARI between the full-data labels and a refit on 10 random 80% subsamples.
External (only when true_need is present): ARI + NMI vs true_need.
"""
import json

import numpy as np
import pandas as pd
from sklearn.metrics import (adjusted_rand_score, calinski_harabasz_score, davies_bouldin_score,
                             normalized_mutual_info_score, silhouette_score)

from _cli import parser, processed_dir
from cluster import KS, SEED, dbscan_fit, gmm_model, kmeans_fit, reduce, select_by_silhouette, ward_fit

N_BOOT, FRAC = 10, 0.8


def r(v):
    return None if v is None else round(float(v), 4)


def internal(X, labels) -> dict:
    m = labels >= 0
    if len(set(labels[m])) < 2 or m.sum() <= len(set(labels[m])):
        return {"silhouette": None, "davies_bouldin": None, "calinski_harabasz": None}
    return {"silhouette": r(silhouette_score(X[m], labels[m])),
            "davies_bouldin": r(davies_bouldin_score(X[m], labels[m])),
            "calinski_harabasz": r(calinski_harabasz_score(X[m], labels[m]))}


def stability(X, labels, refit, n_boot=N_BOOT, frac=FRAC, seed=SEED) -> float:
    rng = np.random.default_rng(seed)
    n = len(X)
    aris = []
    for _ in range(n_boot):
        idx = np.sort(rng.choice(n, int(frac * n), replace=False))
        aris.append(adjusted_rand_score(labels[idx], refit(X[idx])))
    return float(np.mean(aris))


def external(labels, truth: pd.Series) -> dict:
    m = truth.notna().to_numpy()
    if not m.any():
        return {"ari_true": None, "nmi_true": None}
    t = truth[m].astype(str).to_numpy()
    return {"ari_true": r(adjusted_rand_score(t, labels[m])), "nmi_true": r(normalized_mutual_info_score(t, labels[m]))}


def refitters(info: dict) -> dict:
    c, db = info["choices"], info["dbscan"]
    return {"kmeans": lambda X: kmeans_fit(X, c["kmeans"]),
            "ward": lambda X: ward_fit(X, c["ward"]),
            "gmm": lambda X: gmm_model(X, c["gmm"]).predict(X),
            "dbscan": lambda X: dbscan_fit(X, db["eps"], db["min_samples"])}


def algorithm_metrics(X, frame: pd.DataFrame, truth: pd.Series, info: dict, U=None) -> dict:
    """Internal metrics in each algorithm's own space: PCA-50, except DBSCAN on UMAP-10 (U) when given.
    DBSCAN stability refits DBSCAN on subsamples of the fixed UMAP-10 coordinates."""
    out = {}
    for algo, refit in refitters(info).items():
        labels = frame[algo].to_numpy()
        space = U if algo == "dbscan" and U is not None else X
        out[algo] = {"k": info["choices"][algo], **internal(space, labels),
                     "stability_ari": r(stability(space, labels, refit)), **external(labels, truth)}
        if algo == "dbscan":
            out[algo].update(noise_share=r((labels == -1).mean()), eps=info["dbscan"]["eps"],
                             min_samples=info["dbscan"]["min_samples"],
                             space="umap10" if U is not None else "pca50",
                             silhouette_pca50=internal(X, labels)["silhouette"])
    return out


def raw_vs_gloss(emb_raw, emb_gloss, truth: pd.Series, ks=KS) -> dict:
    """Same PCA + K-Means/silhouette selection on raw-text vs gloss embeddings of the SAME comments."""
    out = {"n": int(len(emb_raw))}
    labels = {}
    for name, emb in (("gloss", emb_gloss), ("raw", emb_raw)):
        X = reduce(emb)
        k, labels[name], _ = select_by_silhouette(X, kmeans_fit, ks)
        out[name] = {"k": k, "silhouette": r(silhouette_score(X, labels[name])), **external(labels[name], truth)}
    out["ari_raw_vs_gloss"] = r(adjusted_rand_score(labels["gloss"], labels["raw"]))
    return out


def compute_metrics(X, frame, truth, info, raw=None, ks=KS, U=None) -> dict:
    """raw: optional (emb_raw, emb_gloss rows for the same comments, truth for them)."""
    return {"n": int(len(X)), "has_true_need": bool(truth.notna().any()),
            "stability": {"resamples": N_BOOT, "fraction": FRAC, "replace": False},
            "algorithms": algorithm_metrics(X, frame, truth, info, U),
            "raw_vs_gloss": raw_vs_gloss(*raw, ks=ks) if raw else None,
            "curves": info["curves"], "ward_dendrogram": info["ward_dendrogram"],
            "drilldown": info["drilldown"], "dbscan": info["dbscan"], "unusual": info.get("unusual")}


def load_raw(d, frame: pd.DataFrame, truth: pd.Series):
    """Raw-text embeddings (subset) + matching gloss rows, or None if not embedded yet."""
    if not (d / "emb_raw.npy").exists() or not (d / "emb_raw_ids.parquet").exists():
        return None
    ids = pd.read_parquet(d / "emb_raw_ids.parquet")["comment_id"]
    pos = pd.Series(np.arange(len(frame)), index=frame["comment_id"])
    if not ids.isin(pos.index).all():
        return None  # stale subset (comments changed) → re-embed raw
    rows = pos.loc[ids].to_numpy()
    return np.load(d / "emb_raw.npy"), np.load(d / "emb_gloss.npy")[rows], truth.iloc[rows].reset_index(drop=True)


def main() -> None:
    args = parser("Step 6: metrics").parse_args()
    d = processed_dir(args.dataset)
    frame = pd.read_parquet(d / "comment_clusters.parquet")
    truth = frame[["comment_id"]].merge(pd.read_parquet(d / "comments.parquet")[["comment_id", "true_need"]],
                                        on="comment_id", how="left")["true_need"]
    info = json.loads((d / "cluster_info.json").read_text())
    raw = load_raw(d, frame, truth)
    U = np.load(d / "x_umap10.npy") if (d / "x_umap10.npy").exists() else None
    m = compute_metrics(np.load(d / "x_pca.npy"), frame, truth, info, raw, U=U)
    (d / "metrics.json").write_text(json.dumps(m, indent=1))
    print(f"metrics [{args.dataset}]: " + ", ".join(f"{a} sil={v['silhouette']}" for a, v in m["algorithms"].items())
          + ("" if raw else " (raw-vs-gloss skipped: no raw embeddings yet)"))


if __name__ == "__main__":
    main()
