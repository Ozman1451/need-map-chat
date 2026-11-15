import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PIPE = Path(__file__).resolve().parents[2] / "pipeline"
STEPS = {"clean.py", "tag.py", "embed.py", "cluster.py", "name.py", "metrics.py", "artifacts.py", "run_all.py"}
# seed_synthetic is covered by test_seed.py; pipeline steps by the run_all test below
STUBS = sorted(p for p in PIPE.glob("*.py")
               if not p.name.startswith("_") and p.name not in STEPS | {"seed_synthetic.py"})


@pytest.mark.parametrize("script", STUBS, ids=lambda p: p.name)
def test_stub_script_runs(script):
    r = subprocess.run([sys.executable, str(script), "--dataset", "synthetic"],
                       capture_output=True, text=True, timeout=60, env={**os.environ, "MOCK_LLM": "1"})
    assert r.returncode == 0, r.stderr


def test_run_all_on_sample(tmp_path):
    env = {**os.environ, "MOCK_LLM": "1", "PIPELINE_OUT": str(tmp_path), "CACHE_ROOT": str(tmp_path / "c")}
    r = subprocess.run([sys.executable, str(PIPE / "run_all.py"), "--dataset", "sample"],
                       capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    a = tmp_path / "artifacts" / "sample"
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
