"""Refresh the generated blocks in README.md from artifacts/ (run: make readme).

Rewrites everything between `<!-- NAME:start -->` and `<!-- NAME:end -->` for NAME in
data | metrics | benchmark | clusters. Idempotent; nothing outside the markers is touched.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALGO_LABEL = {"kmeans": "K-Means", "ward": "Agglomerative (Ward)", "gmm": "Gaussian Mixture", "dbscan": "DBSCAN"}
ORDER = ["kmeans", "ward", "gmm", "dbscan"]


def _f(v, nd=3) -> str:
    return "–" if v is None else f"{v:.{nd}f}"


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def metrics_table(m: dict, primary: str = "kmeans") -> str:
    rows = ["| Algorithm | k | Silhouette ↑ | Davies–Bouldin ↓ | Calinski–Harabasz ↑ | Stability (ARI) ↑ | Noise |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for a in ORDER:
        x = m["algorithms"].get(a)
        if not x:
            continue
        sil = _f(x["silhouette"])
        if a == "dbscan" and x.get("silhouette_pca50") is not None:
            sil = f"{sil} ({x.get('space', 'umap')}) · {_f(x['silhouette_pca50'])} (pca50)"
        noise = f"{x['noise_share']:.0%}" if x.get("noise_share") is not None else "–"
        name = f"**{ALGO_LABEL[a]}** (primary)" if a == primary else ALGO_LABEL[a]
        rows.append(f"| {name} | {x['k']} | {sil} | {_f(x['davies_bouldin'], 2)} | {_f(x['calinski_harabasz'], 1)} "
                    f"| {_f(x['stability_ari'], 2)} | {noise} |")
    st = m.get("stability", {})
    lines = ["\n".join(rows), "",
             f"*{m['n']:,} comments. Stability = mean ARI across {st.get('resamples', '?')} resamples of "
             f"{st.get('fraction', 0):.0%} of the data.*"]
    rg = m.get("raw_vs_gloss")
    if rg:
        lines.append(f"*Embedding the Gemini English gloss instead of the raw comment text: K-Means silhouette "
                     f"{_f(rg['gloss']['silhouette'])} vs {_f(rg['raw']['silhouette'])} (raw).*")
    return "\n".join(lines)


def benchmark_table(m: dict) -> str:
    rows = ["| Algorithm | k | ARI vs true need ↑ | NMI vs true need ↑ | Stability (ARI) ↑ |", "|---|---:|---:|---:|---:|"]
    for a in ORDER:
        x = m["algorithms"].get(a)
        if x:
            rows.append(f"| {ALGO_LABEL[a]} | {x['k']} | {_f(x['ari_true'])} | {_f(x['nmi_true'])} | {_f(x['stability_ari'], 2)} |")
    return "\n".join(rows) + f"\n\n*Labelled benchmark: {m['n']:,} comments, each generated from one known need.*"


def clusters_table(clusters: list[dict], algo: str = "kmeans") -> str:
    top = sorted((c for c in clusters if c["algo"] == algo and not c["parent_id"]), key=lambda c: -c["share"])
    rows = ["| | Need | Share | Comments | Recommended action |", "|---|---|---:|---:|---|"]
    rows += [f"| {c['cluster_id']} | **{c['name']}** | {c['share']:.0%} | {c['size']} | {c['action']} |" for c in top]
    return "\n".join(rows)


def data_block(manifest: dict, posts_path: Path | None = None, raw_comments: Path | None = None) -> str:
    c = manifest.get("counts", {})
    brands = sorted(c.get("by_brand", {}).items(), key=lambda kv: -kv[1])
    scraped = None
    if raw_comments and raw_comments.exists():
        import pandas as pd
        scraped = len(pd.read_parquet(raw_comments, columns=["comment_id"]))
    window = collected = None
    if posts_path and posts_path.exists():
        import pandas as pd
        p = pd.read_parquet(posts_path, columns=["posted_at", "collected_at"])
        fmt = lambda t: pd.Timestamp(t).strftime("%-d %b %Y")  # noqa: E731
        window, collected = f"{fmt(p.posted_at.min())} – {fmt(p.posted_at.max())}", fmt(p.collected_at.max())
    rows = ["| | |", "|---|---|",
            f"| Brands | {len(brands)} |",
            f"| Posts | {c.get('posts', 0):,} |"]
    if scraped is not None:
        rows.append(f"| Comments scraped | {scraped:,} |")
    rows.append(f"| Comments clustered (after cleaning) | {c.get('clustered', c.get('comments', 0)):,} |")
    if window:
        rows += [f"| Posts dated | {window} |", f"| Scraped | {collected} (Apify) |"]
    rows.append("")
    rows.append("Comments per brand: " + " · ".join(f"{b} {n:,}" for b, n in brands))
    return "\n".join(rows)


def build_blocks(artifacts: Path, raw: Path | None = None) -> dict[str, str]:
    out = {}
    real, syn = artifacts / "real", artifacts / "synthetic"
    if (m := _load(real / "metrics.json")):
        primary = (_load(real / "manifest.json") or {}).get("primary", "kmeans")
        out["metrics"] = metrics_table(m, primary)
    if (m := _load(syn / "metrics.json")):
        out["benchmark"] = benchmark_table(m)
    if (cl := _load(real / "clusters.json")):
        out["clusters"] = clusters_table(cl)
    if (man := _load(real / "manifest.json")):
        out["data"] = data_block(man, real / "posts.parquet", raw / "comments.parquet" if raw else None)
    return out


def replace_blocks(text: str, blocks: dict[str, str]) -> str:
    for name, body in blocks.items():
        pat = re.compile(rf"(<!-- {name}:start -->)(.*?)(<!-- {name}:end -->)", re.S)
        text = pat.sub(lambda mo: f"{mo.group(1)}\n{body}\n{mo.group(3)}", text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--readme", type=Path, default=ROOT / "README.md")
    ap.add_argument("--artifacts", type=Path, default=ROOT / "artifacts")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw" / "real")
    a = ap.parse_args()
    blocks = build_blocks(a.artifacts, a.raw)
    a.readme.write_text(replace_blocks(a.readme.read_text(), blocks))
    print(f"README blocks refreshed: {', '.join(blocks) or 'none (no artifacts)'}")


if __name__ == "__main__":
    main()
