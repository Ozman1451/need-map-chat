import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_blobs

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
import clean  # noqa: E402
import cluster  # noqa: E402
import embed as embed_step  # noqa: E402
import metrics  # noqa: E402
import name  # noqa: E402
import tag  # noqa: E402

from app import llm  # noqa: E402

SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def blobs():
    X, y = make_blobs(n_samples=300, centers=6, n_features=20, cluster_std=1.0, random_state=0)
    return X, y


@pytest.fixture(scope="module")
def sample_X():
    comments = pd.read_parquet(SAMPLE / "comments.parquet")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MOCK_LLM", "1")
        emb = llm.embed(comments["text"].tolist(), dataset="t")
    return cluster.reduce(emb), comments


def test_clean_rules():
    df = pd.DataFrame({
        "comment_id": list("abcdefgh"), "post_id": ["p1"] * 6 + ["p2", "p2"],
        "text": ["  price   plz ", "😍😍🔥", "https://x.co/abc", "", "price plz", "قیمت؟ 😍",
                 "price plz", "see www.shop.pk now"],
        "is_synthetic": True})
    out, stats = clean.clean_comments(df)
    assert out["comment_id"].tolist() == ["a", "f", "g", "h"]  # b emoji, c URL, d empty, e dup in p1
    assert out["text"].iloc[0] == "price plz" and "😍" in out["text"].iloc[1]  # whitespace normalised, emoji kept
    assert stats == {"input": 8, "dropped_no_content": 3, "dropped_dup_within_post": 1, "output": 4}
    assert out["true_need"].isna().all()  # column added when absent (real data)


def test_clean_sample_keeps_cross_post_repeats():
    raw = pd.read_parquet(SAMPLE / "comments.parquet")
    out, _ = clean.clean_comments(raw)
    assert not out.duplicated(["post_id", "text"]).any() and len(out) >= 190


def test_relabel_by_size_and_noise():
    out = cluster.relabel_by_size(np.array([5, 5, 2, -1, 2, 2, 9]))
    assert out.tolist() == [2, 2, 1, -1, 1, 1, 3]


def test_k_selection_finds_blobs(blobs):
    X, y = blobs
    k, labels, curve = cluster.select_by_silhouette(X, cluster.kmeans_fit, cluster.KS)
    assert k == 6 and [c["k"] for c in curve] == list(cluster.KS)
    assert set(labels) == set(range(1, 7))
    n, gl, prob, bic = cluster.select_gmm(X, cluster.KS)
    assert 4 <= n <= 14 and len(gl) == len(X) and ((prob > 0) & (prob <= 1)).all() and len(bic) == 11


def test_knee_eps_dbscan_separates_blobs(blobs):
    X, _ = blobs
    eps = cluster.knee_eps(cluster.k_distance(X))
    labels = cluster.dbscan_fit(X, eps)
    assert eps > 0 and len(set(labels) - {-1}) >= 2


def test_run_clustering_on_sample(sample_X):
    X, comments = sample_X
    frame, Xp, U, info = cluster.run_clustering(X, drill_min=40)
    n = len(comments)
    assert len(frame) == n and Xp.shape == (n, X.shape[1]) and U.shape == (n, 10)
    assert info["dbscan"]["space"] == "umap10" and 5 <= info["dbscan"]["min_samples"] <= 20
    assert frame["unusual"].sum() == (frame["unusual_reasons"] != "").sum() == info["unusual"]["count"]
    assert frame["unusual_score"].between(0, 4).all()
    for algo in ("kmeans", "ward", "gmm"):
        assert 4 <= info["choices"][algo] <= 14
        assert frame[algo].between(1, info["choices"][algo]).all()
    assert frame["dbscan"].ge(-1).all() and frame["gmm_prob"].between(0, 1).all()
    assert (frame["primary"] == "C" + frame["kmeans"].astype(str)).all()
    assert len(info["ward_dendrogram"]["linkage"]) == info["choices"]["ward"] - 1


def test_dbscan_select_sweeps_into_noise_range(blobs):
    X, _ = blobs
    labels, info = cluster.dbscan_select(X)
    assert len(labels) == len(X) and info["k"] == len(set(labels) - {-1})
    if info["swept"]:
        assert [t["min_samples"] for t in info["sweep"]] == list(cluster.MIN_SAMPLES_SWEEP)
        in_range = [t for t in info["sweep"] if 0.02 <= t["noise_share"] <= 0.08 and t["silhouette"] is not None]
        if in_range:
            assert info["silhouette"] == max(t["silhouette"] for t in in_range)
    else:
        assert info["min_samples"] == 10 and 0.02 <= info["noise_share"] <= 0.08


def test_unusual_reasons():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((100, 5))
    X[7] += 30  # far from its centroid
    km = np.ones(100, dtype=int)
    db = np.ones(100, dtype=int)
    db[3] = -1
    prob = np.full(100, 0.9)
    prob[5] = 0.3
    u = cluster.unusual(X, km, db, prob)
    assert u.loc[3, "unusual_reasons"].startswith("dbscan_noise") and "low_gmm_prob" in u.loc[5, "unusual_reasons"]
    assert "far_from_centroid" in u.loc[7, "unusual_reasons"] and u["unusual_score"].idxmax() in (3, 5, 7)
    assert u["unusual_reasons"].str.contains("far_from_centroid").sum() == 3  # top 3% of 100
    assert (u["unusual"] == (u["unusual_reasons"] != "")).all()
    assert u.loc[~u["unusual"], "unusual_score"].lt(1).all() and u.loc[u["unusual"], "unusual_score"].ge(1).all()


def test_drill_down_creates_children(blobs):
    X, _ = blobs
    primary = np.where(np.arange(len(X)) < 200, 1, 2)  # one big parent (200), one small (100)
    sub, info = cluster.drill_down(X, primary, min_size=150)
    assert list(info) == ["C1"] and 2 <= info["C1"]["k"] <= 4
    kids = {s for s in sub[:200]}
    assert kids == {f"C1.{i}" for i in range(1, info["C1"]["k"] + 1)} and set(sub[200:]) == {None}


def test_ctfidf_distinguishes_clusters():
    terms = name.ctfidf_top_terms([["asks price of suit", "price please"], ["delivery to lahore", "delivery time"]])
    assert terms[0][0] == "price" and terms[1][0] == "delivery"


def test_off_topic_rule():
    g = pd.Series(["Spam request for mutual follows.", "Asks for a chicken biryani recipe.",
                   "Asks the price of the lawn suit.", "Wants to know delivery time to Lahore.", None])
    assert name.is_off_topic(g).tolist() == [True, True, False, False, False]


def test_derive_majority_and_mixed():
    primary = pd.Series(["C1"] * 6 + ["C2"] * 3 + ["C3"])
    km = {c: {"name": f"N{c}", "description": "d", "action": f"act {c}"} for c in ("C1", "C2", "C3")}
    major = name.derive({"_idx": np.arange(10)}, primary, km)
    assert major["name"] == "NC1" and major["derived_from"] == {"C1": 0.6, "C2": 0.3}
    mixed = name.derive({"_idx": np.arange(3, 10)}, primary, km)  # C1 3/7, C2 3/7, C3 1/7
    assert mixed["name"] == "Mixed: NC1 + NC2" and mixed["action"] == "act C1"


def test_name_all_gemini_only_for_kmeans(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "name_clusters", lambda payloads, dataset: calls.append([p["cluster_id"] for p in payloads])
                        or {p["cluster_id"]: {"name": "G" + p["cluster_id"], "description": "d", "action": "a"}
                            for p in payloads})
    rng = np.random.default_rng(1)
    n = 60
    X = rng.standard_normal((n, 5))
    km = np.repeat([1, 2, 3], 20)
    gl = ["Asks the price of the suit."] * 20 + ["Wants delivery to Karachi."] * 20 + ["Spam request for follows."] * 20
    df = pd.DataFrame({"comment_id": [f"c{i}" for i in range(n)], "kmeans": km, "ward": km,
                       "gmm": np.where((np.arange(n) >= 5) & (np.arange(n) < 55), 1, 2), "dbscan": np.where(np.arange(n) == 0, -1, km),
                       "primary": [f"C{v}" for v in km], "sub": [f"C1.{1 + i % 2}" if i < 20 else None for i in range(n)],
                       "unusual_score": rng.random(n), "gloss": gl, "text": gl, "city": None, "sentiment": "neu",
                       "purchase_intent": "none", "language_type": "English"})
    df["off_topic"] = name.is_off_topic(df["gloss"])
    out = {(c["algo"], c["cluster_id"]): c for c in name.name_all(name.build_profiles(df, X), df, "t")}
    assert calls == [["C1", "C2"], ["C1.1", "C1.2"]]  # C3 is off-topic → no Gemini
    assert out[("kmeans", "C3")]["name"] == name.OFF["name"] and out[("dbscan", "D0")]["name"] == name.NOISE["name"]
    assert out[("ward", "W1")]["name"] == "GC1" and out[("ward", "W1")]["derived_from"] == {"C1": 1.0}
    assert out[("gmm", "G1")]["name"].startswith("Mixed: GC2 + ")  # 15 C1 / 20 C2 / 15 C3 → no majority
    assert out[("gmm", "G2")]["name"] == name.OFF["name"]  # 5 C1 + 5 C3 → 50% off-topic


def test_metrics_without_true_need(blobs):
    X, _ = blobs
    frame = pd.DataFrame({a: cluster.relabel_by_size(cluster.kmeans_fit(X, 6)) for a in ("kmeans", "ward", "gmm")})
    frame["dbscan"] = cluster.relabel_by_size(cluster.dbscan_fit(X, cluster.knee_eps(cluster.k_distance(X))))
    info = {"choices": {"kmeans": 6, "ward": 6, "gmm": 6, "dbscan": 3},
            "dbscan": {"eps": cluster.knee_eps(cluster.k_distance(X)), "min_samples": 10}}
    truth = pd.Series([None] * len(X))
    m = metrics.algorithm_metrics(X, frame, truth, info)
    assert m["kmeans"]["ari_true"] is None and m["kmeans"]["silhouette"] > 0.5
    assert m["kmeans"]["stability_ari"] > 0.9 and 0 <= m["dbscan"]["noise_share"] <= 1
    rv = metrics.raw_vs_gloss(X + 0.01, X, truth)
    assert rv["raw"]["ari_true"] is None and rv["ari_raw_vs_gloss"] > 0.9 and rv["n"] == len(X)




def test_finalize_tags_and_embed_unique():
    comments = pd.DataFrame({"comment_id": ["a", "b"], "text": ["price?", "hi"]})
    tags = pd.DataFrame([{"comment_id": "b", "sentiment": "neu", "purchase_intent": "none",
                          "language_type": "English", "city": "null", "gloss": " "}])
    out = tag.finalize_tags(tags, comments)
    assert out["comment_id"].tolist() == ["b"] and out["gloss"].iloc[0] == "hi" and out["city"].isna().all()
    calls = []
    vecs = embed_step.embed_unique(["x", "y", "x"], lambda xs: calls.append(xs) or np.eye(len(xs)))
    assert calls == [["x", "y"]] and (vecs[0] == vecs[2]).all()


def test_daily_quota_is_not_retried():
    class E(Exception):
        code = 429
    assert llm.is_daily_quota(E("Quota exceeded ... quotaId: EmbedContentRequestsPerDayPerProjectPerModel-FreeTier"))
    assert not llm.is_daily_quota(E("quotaId: EmbedContentRequestsPerMinutePerProjectPerModel-FreeTier"))
