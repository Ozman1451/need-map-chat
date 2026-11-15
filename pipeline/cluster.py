"""Step 4: cluster gloss embeddings + UMAP 2-D + drill-down + unusual score.

K-Means / Ward / GMM run on PCA(50); DBSCAN runs on a 10-D cosine UMAP of that PCA(50) (density needs a
space where neighbourhoods are meaningful; UMAP straight from 768-d was not reproducible). Outputs (data/processed/<ds>/): comment_clusters.parquet, x_pca.npy,
x_umap10.npy, cluster_info.json. Labels are renumbered 1..k by size (1 = largest); DBSCAN noise stays -1.
"""
import json

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import NearestNeighbors

from _cli import parser, processed_dir

SEED = 42
KS = range(4, 15)
MIN_SAMPLES = 10
MIN_SAMPLES_SWEEP = range(5, 21)
NOISE_RANGE = (0.02, 0.08)
FAR_PCT = 97  # top 3% distance to own K-Means centroid → unusual
LOW_GMM_PROB = 0.5
DRILL_MIN = 80
DRILL_KS = range(2, 5)
PREFIX = {"kmeans": "C", "ward": "W", "dbscan": "D", "gmm": "G"}


# ---------------------------------------------------------------- primitives
def reduce(X: np.ndarray, n: int = 50) -> np.ndarray:
    n = min(n, X.shape[0] - 1, X.shape[1])
    return PCA(n, random_state=SEED).fit_transform(X)


def relabel_by_size(labels: np.ndarray) -> np.ndarray:
    """Map cluster labels to 1..k by descending size; -1 (noise) is kept."""
    labels = np.asarray(labels)
    ids, counts = np.unique(labels[labels >= 0], return_counts=True)
    order = ids[np.lexsort((ids, -counts))]
    lut = {old: new for new, old in enumerate(order, start=1)}
    return np.array([lut.get(v, -1) for v in labels], dtype=int)


def kmeans_fit(X, k):
    return KMeans(k, n_init=10, random_state=SEED).fit_predict(X)


def ward_fit(X, k):
    return AgglomerativeClustering(k, linkage="ward").fit_predict(X)


def gmm_model(X, n):
    return GaussianMixture(n, covariance_type="diag", reg_covar=1e-4, random_state=SEED).fit(X)


def dbscan_fit(X, eps, min_samples=MIN_SAMPLES):
    return DBSCAN(eps=eps, min_samples=min_samples).fit_predict(X)


def valid_ks(ks, n: int) -> list[int]:
    return [k for k in ks if 2 <= k < n]


def select_by_silhouette(X, fit, ks) -> tuple[int, np.ndarray, list[dict]]:
    """Fit each k, keep the one with the highest silhouette. → (k, labels, curve)."""
    best, curve = None, []
    for k in valid_ks(ks, len(X)):
        labels = fit(X, k)
        s = float(silhouette_score(X, labels)) if len(set(labels)) > 1 else -1.0
        curve.append({"k": k, "silhouette": round(s, 4)})
        if best is None or s > best[0]:
            best = (s, k, labels)
    return best[1], relabel_by_size(best[2]), curve


def select_gmm(X, ns) -> tuple[int, np.ndarray, np.ndarray, list[dict]]:
    """Fit each n, keep the lowest BIC. → (n, labels, max prob, curve)."""
    best, curve = None, []
    for n in valid_ks(ns, len(X)):
        m = gmm_model(X, n)
        bic = float(m.bic(X))
        curve.append({"n": n, "bic": round(bic, 1)})
        if best is None or bic < best[0]:
            best = (bic, n, m)
    m = best[2]
    return best[1], relabel_by_size(m.predict(X)), m.predict_proba(X).max(axis=1), curve


def k_distance(X, min_samples=MIN_SAMPLES) -> np.ndarray:
    """Distance from each point to its min_samples-th neighbour (self included, as DBSCAN counts it)."""
    nn = NearestNeighbors(n_neighbors=min(min_samples, len(X))).fit(X)
    return nn.kneighbors(X)[0][:, -1]


def knee_eps(kdist: np.ndarray) -> float:
    """Knee of the sorted k-distance curve: point farthest below the chord (Kneedle, convex rising)."""
    y = np.sort(kdist)
    if len(y) < 3 or y[-1] == y[0]:
        return float(y[-1]) or 1e-6
    xn = np.linspace(0, 1, len(y))
    yn = (y - y[0]) / (y[-1] - y[0])
    return float(y[int(np.argmax(xn - yn))])


def umap_nd(X: np.ndarray, n: int = 2, min_dist: float = 0.1) -> np.ndarray:
    import umap
    if len(X) < n + 4:
        return np.zeros((len(X), n))
    return umap.UMAP(n_components=n, metric="cosine", n_neighbors=min(15, len(X) - 1), min_dist=min_dist,
                     random_state=SEED, n_jobs=1, compatibility_layout=True).fit_transform(X)


def umap_2d(X: np.ndarray) -> np.ndarray:
    return umap_nd(X, 2, 0.1)


def dbscan_select(U: np.ndarray, noise_range=NOISE_RANGE, sweep=MIN_SAMPLES_SWEEP) -> tuple[np.ndarray, dict]:
    """DBSCAN with eps from the k-distance knee, min_samples=10. If the noise share falls outside
    noise_range, sweep min_samples and keep the best non-noise silhouette whose noise is in range
    (none in range → the one closest to the range). → (labels, info)."""
    def run(ms):
        eps = knee_eps(k_distance(U, ms))
        labels = relabel_by_size(dbscan_fit(U, eps, ms))
        m = labels >= 0
        k = len(set(labels[m]))
        sil = float(silhouette_score(U[m], labels[m])) if 2 <= k < m.sum() else None
        return {"min_samples": ms, "eps": round(eps, 4), "k": k, "noise_share": round(float((~m).mean()), 4),
                "silhouette": None if sil is None else round(sil, 4)}, labels

    base, labels = run(MIN_SAMPLES)
    info = {"space": "umap10", **base, "swept": False}
    lo, hi = noise_range
    if lo <= base["noise_share"] <= hi:
        return labels, info
    trials = [run(ms) for ms in sweep]
    ok = [t for t in trials if lo <= t[0]["noise_share"] <= hi and t[0]["silhouette"] is not None]
    pick = (max(ok, key=lambda t: t[0]["silhouette"]) if ok else
            min(trials, key=lambda t: max(lo - t[0]["noise_share"], t[0]["noise_share"] - hi)))
    return pick[1], {"space": "umap10", **pick[0], "swept": True, "sweep": [t[0] for t in trials]}


def unusual(X, km: np.ndarray, db: np.ndarray, gmm_prob: np.ndarray) -> pd.DataFrame:
    """Unusual = DBSCAN noise OR top 3% distance to own K-Means centroid OR GMM max prob < 0.5.
    score = number of reasons + 0.99 × centroid-distance percentile (tie-break) → integer part = #reasons."""
    dist = np.zeros(len(X))
    for c in set(km):
        idx = km == c
        dist[idx] = np.linalg.norm(X[idx] - X[idx].mean(axis=0), axis=1)
    pct = pd.Series(dist).rank(pct=True).to_numpy()
    flags = {"dbscan_noise": db == -1, "far_from_centroid": dist >= np.percentile(dist, FAR_PCT),
             "low_gmm_prob": gmm_prob < LOW_GMM_PROB}
    reasons = [",".join(k for k, f in flags.items() if f[i]) for i in range(len(X))]
    n = sum(f.astype(int) for f in flags.values())
    return pd.DataFrame({"centroid_dist": dist.round(4), "unusual": n > 0,
                         "unusual_score": np.round(n + 0.99 * pct, 4), "unusual_reasons": reasons})


def centroid_linkage(X, labels) -> dict:
    """Ward linkage over cluster centroids (small dendrogram)."""
    ids = sorted(set(labels) - {-1})
    cents = np.stack([X[labels == i].mean(axis=0) for i in ids])
    Z = linkage(cents, "ward") if len(ids) > 1 else np.zeros((0, 4))
    return {"labels": [f"W{i}" for i in ids], "linkage": np.round(Z, 4).tolist()}


def drill_down(X, primary: np.ndarray, min_size=DRILL_MIN, ks=DRILL_KS, prefix="C") -> tuple[list, dict]:
    """Ward k=2..4 (silhouette) inside every primary cluster with ≥min_size members.
    → (sub labels per row like "C3.1" or None, {parent_id: {k, silhouette_curve}})."""
    sub = [None] * len(primary)
    info = {}
    for p in sorted(set(primary) - {-1}):
        idx = np.flatnonzero(primary == p)
        if len(idx) < min_size:
            continue
        k, labels, curve = select_by_silhouette(X[idx], ward_fit, ks)
        for i, lab in zip(idx, labels):
            sub[i] = f"{prefix}{p}.{lab}"
        info[f"{prefix}{p}"] = {"k": k, "curve": curve}
    return sub, info


# ---------------------------------------------------------------- whole step
def run_clustering(emb: np.ndarray, ks=KS, drill_min=DRILL_MIN) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, dict]:
    """emb: (n, d) gloss embeddings → (label frame, PCA matrix, UMAP-10 matrix, info with choices/curves)."""
    X = reduce(emb)
    k_km, km, km_curve = select_by_silhouette(X, kmeans_fit, ks)
    k_wd, wd, wd_curve = select_by_silhouette(X, ward_fit, ks)
    k_gm, gm, gm_prob, gm_curve = select_gmm(X, ks)
    U = umap_nd(X, 10, 0.0)  # on PCA-50 of the gloss embeddings: 768-d input made UMAP non-deterministic
    db, db_info = dbscan_select(U)
    kd = k_distance(U, db_info["min_samples"])
    xy = umap_2d(X)
    sub, drill = drill_down(X, km, drill_min)
    frame = pd.DataFrame({"x": xy[:, 0].round(4), "y": xy[:, 1].round(4), "kmeans": km, "ward": wd,
                          "dbscan": db, "gmm": gm, "gmm_prob": np.round(gm_prob, 4),
                          "primary": [f"C{v}" for v in km], "sub": sub})
    frame = pd.concat([frame, unusual(X, km, db, gm_prob)], axis=1)
    kd_sorted = np.sort(kd)
    step = max(1, len(kd_sorted) // 200)
    info = {
        "n": int(len(X)), "pca_dims": int(X.shape[1]),
        "choices": {"kmeans": k_km, "ward": k_wd, "gmm": k_gm,
                    "dbscan": int(len(set(db) - {-1}))},
        "curves": {"kmeans_silhouette": km_curve, "ward_silhouette": wd_curve, "gmm_bic": gm_curve,
                   "dbscan_kdistance": [round(float(v), 4) for v in kd_sorted[::step]]},
        "dbscan": {**db_info, "noise": int((db == -1).sum())},
        "unusual": {"rule": f"dbscan noise OR top {100 - FAR_PCT}% centroid distance OR gmm prob < {LOW_GMM_PROB}",
                    "count": int(frame["unusual"].sum())},
        "ward_dendrogram": centroid_linkage(X, wd),
        "drilldown": drill,
    }
    return frame, X, U, info


def main() -> None:
    args = parser("Step 4: clustering").parse_args()
    d = processed_dir(args.dataset)
    ids = pd.read_parquet(d / "emb_ids.parquet")
    frame, X, U, info = run_clustering(np.load(d / "emb_gloss.npy"))
    frame.insert(0, "comment_id", ids["comment_id"].to_numpy())
    frame.to_parquet(d / "comment_clusters.parquet", index=False)
    np.save(d / "x_pca.npy", X)
    np.save(d / "x_umap10.npy", U)
    (d / "cluster_info.json").write_text(json.dumps(info, indent=1))
    db = info["dbscan"]
    print(f"cluster [{args.dataset}]: choices {info['choices']}, dbscan(umap10) eps={db['eps']} "
          f"min_samples={db['min_samples']} noise={db['noise_share']:.1%}, unusual={info['unusual']['count']}, "
          f"drill-down parents {list(info['drilldown'])}")


if __name__ == "__main__":
    main()
