import json

import pandas as pd


def test_run_all_on_sample(sample_artifacts):
    a = sample_artifacts / "sample"
    cc = pd.read_parquet(a / "comment_clusters.parquet")
    assert list(cc.columns) == ["comment_id", "x", "y", "kmeans", "ward", "dbscan", "gmm", "gmm_prob",
                                "primary", "sub", "centroid_dist", "unusual", "unusual_score", "unusual_reasons"]
    tags = pd.read_parquet(a / "comment_tags.parquet")
    assert len(cc) == len(tags) == 200 and tags["gloss"].str.len().gt(0).all()
    clusters = json.loads((a / "clusters.json").read_text())
    assert {c["algo"] for c in clusters} == {"kmeans", "ward", "dbscan", "gmm"}
    assert all(c["name"] and c["action"] for c in clusters)
    km = {c["cluster_id"] for c in clusters if c["algo"] == "kmeans" and not c["parent_id"]}
    assert km == set(cc["primary"])
    m = json.loads((a / "metrics.json").read_text())
    assert set(m["algorithms"]) == {"kmeans", "ward", "dbscan", "gmm"} and m["has_true_need"]
    man = json.loads((a / "manifest.json").read_text())
    assert man["dataset"] == "sample" and man["counts"]["comments"] == 200 and man["is_synthetic"]
