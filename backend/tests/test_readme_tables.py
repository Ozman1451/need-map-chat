import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "readme_tables.py"
spec = importlib.util.spec_from_file_location("readme_tables", SCRIPT)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

ALG = {"k": 3, "silhouette": 0.25, "davies_bouldin": 1.5, "calinski_harabasz": 70.0, "stability_ari": 0.8,
       "ari_true": 0.4, "nmi_true": 0.5}


def _artifacts(tmp_path: Path) -> Path:
    for name in ["real", "synthetic"]:
        d = tmp_path / name
        d.mkdir()
        (d / "metrics.json").write_text(json.dumps({"n": 100, "stability": {"resamples": 10, "fraction": 0.8},
                                                    "algorithms": {"kmeans": ALG, "dbscan": {**ALG, "noise_share": 0.05}}}))
    (tmp_path / "real" / "manifest.json").write_text(json.dumps(
        {"primary": "kmeans", "counts": {"posts": 5, "comments": 100, "clustered": 100, "by_brand": {"A": 60, "B": 40}}}))
    (tmp_path / "real" / "clusters.json").write_text(json.dumps([
        {"cluster_id": "C1", "algo": "kmeans", "parent_id": None, "name": "Price asks", "share": 0.6, "size": 60, "action": "Post prices."},
        {"cluster_id": "C1.1", "algo": "kmeans", "parent_id": "C1", "name": "Sub", "share": 0.3, "size": 30, "action": "x"}]))
    return tmp_path


def test_rewrites_only_marked_blocks_idempotently(tmp_path):
    blocks = rt.build_blocks(_artifacts(tmp_path))
    assert set(blocks) == {"metrics", "benchmark", "clusters", "data"}
    readme = "intro\n<!-- metrics:start -->\nold\n<!-- metrics:end -->\nmid\n<!-- clusters:start --><!-- clusters:end -->\nend\n"
    once = rt.replace_blocks(readme, blocks)
    assert rt.replace_blocks(once, blocks) == once
    assert "old" not in once and once.startswith("intro\n") and "\nmid\n" in once and once.endswith("end\n")
    assert "**K-Means** (primary)" in once and "| C1 | **Price asks** | 60% | 60 | Post prices. |" in once
    assert "Sub" not in once  # only top-level clusters
