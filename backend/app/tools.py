"""Agent tools (SPEC §6.2). Each returns ToolResult {summary, charts} over precomputed labels in the Store;
nothing is re-clustered at request time. Cluster ids in summaries use the "[C3]" format."""
import inspect
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from .schemas import ChartSpec, ToolResult
from .store import ALGO_OF, ALGOS, store

MAX_POINTS = 3000
SUMMARY_CLUSTERS = 15
LANG_ALIASES = {"english": "English", "roman urdu": "Roman Urdu", "roman": "Roman Urdu", "urdu": "Urdu",
                "urdu script": "Urdu", "mixed": "Mixed", "code-mixed": "Mixed"}


class ToolError(ValueError):
    """Bad arguments (unknown cluster, brand…): reported back to the model / a 400 to the client."""


# ---------------------------------------------------------------- helpers
def clean(o: Any) -> Any:
    """→ plain JSON-safe Python (numpy scalars → python, NaN → None)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def result(summary: dict, charts: list[ChartSpec]) -> ToolResult:
    for c in charts:
        c.data, c.meta = clean(c.data), clean({"dataset": store.dataset, **c.meta})
    return ToolResult(summary=clean({"dataset": store.dataset, **summary}), charts=charts)


def ref(cid: str) -> str:
    return f"[{cid}]"


def norm_id(cluster_id: str) -> str:
    cid = str(cluster_id).strip().strip("[]").strip().upper()
    if cid not in store.clusters:
        raise ToolError(f"unknown cluster '{cluster_id}'; valid top-level ids look like C1..C"
                        f"{len(store.top_level('kmeans'))} (K-Means), W*, G*, D* (D0 = DBSCAN noise)")
    return cid


def pick(field: str, value: str | None) -> str | None:
    if value in (None, "", "all", "All"):
        return None
    opts = store.options()[field]
    hit = next((o for o in opts if o.lower() == str(value).strip().lower()), None)
    if hit is None:
        raise ToolError(f"unknown {field} '{value}'; options: {', '.join(opts)}")
    return hit


def subset(brand=None, campaign=None, content_type=None) -> tuple[pd.DataFrame, dict]:
    df = store.ensure().df
    filters = {k: pick(k, v) for k, v in (("brand", brand), ("campaign", campaign), ("content_type", content_type))}
    filters = {k: v for k, v in filters.items() if v}
    for k, v in filters.items():
        df = df[df[k] == v]
    return df, filters


def members(cid: str) -> pd.DataFrame:
    df = store.df
    return df[df["sub"] == cid] if "." in cid else df[df[f"{ALGO_OF[cid[0]]}_id"] == cid]


def mix(s: pd.Series) -> dict:
    return {str(k): round(float(v), 3) for k, v in s.value_counts(normalize=True).items()}


def short(t: str, n: int = 80) -> str:
    t = " ".join(str(t or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def card(r: pd.Series, kind: str | None = None) -> dict:
    raw = r["unusual_reasons"]
    reasons = [] if raw is None or (isinstance(raw, float) and math.isnan(raw)) else [x for x in str(raw).split(",") if x]
    return {"id": r["comment_id"], "text": r["text"], "gloss": r["gloss"], "language": r["language_type"],
            "sentiment": r["sentiment"], "intent": r["purchase_intent"], "brand": r["brand"],
            "campaign": r["campaign"], "content_type": r["content_type"], "post_url": r["url"],
            "cluster": r["primary"], "cluster_name": store.clusters.get(r["primary"], {}).get("name"),
            "unusual_score": round(float(r["unusual_score"]), 3), "reasons": reasons, "kind": kind}


def points(df: pd.DataFrame, col: str, highlight: pd.Series | None = None) -> list[dict]:
    out = []
    for r in df.itertuples(index=False):
        p = {"id": r.comment_id, "x": round(float(r.x), 4), "y": round(float(r.y), 4),
             "cluster": getattr(r, col), "text": short(r.text)}
        if highlight is not None:
            p["highlight"] = bool(highlight.get(r.comment_id, False))
        out.append(p)
    return out


def sample_df(df: pd.DataFrame, n: int = MAX_POINTS, keep: pd.Series | None = None) -> pd.DataFrame:
    """≤n rows; rows where `keep` is True are always included."""
    if len(df) <= n:
        return df
    must = df[keep] if keep is not None else df.iloc[:0]
    rest = df.drop(must.index)
    return pd.concat([must, rest.sample(max(0, n - len(must)), random_state=42)])


def cluster_row(c: dict, size: int, share: float) -> dict:
    return {"id": c["cluster_id"], "name": c["name"], "description": c["description"], "action": c["action"],
            "size": int(size), "share": round(share, 4), "global_size": c["size"], "algo": c["algo"],
            "has_children": bool(store.children(c["cluster_id"]))}


def counted_clusters(df: pd.DataFrame, algo: str) -> list[dict]:
    """Top-level clusters of `algo` with their size/share inside df, largest first."""
    counts = df[f"{algo}_id"].value_counts()
    rows = [cluster_row(store.clusters[cid], n, n / len(df)) for cid, n in counts.items() if cid in store.clusters]
    return sorted(rows, key=lambda r: -r["size"])


def brief(rows: list[dict], limit: int = SUMMARY_CLUSTERS) -> list[dict]:
    return [{"id": ref(r["id"]), "name": r["name"], "size": r["size"], "share": r["share"], "action": r["action"]}
            for r in rows[:limit]]


# ---------------------------------------------------------------- tools
def get_overview(brand: str | None = None, campaign: str | None = None) -> ToolResult:
    """Quick numbers: comments, posts, % purchase intent, language mix, top need."""
    df, filters = subset(brand, campaign)
    if df.empty:
        return result({"filters": filters, "n_comments": 0, "note": "no comments match these filters"}, [])
    intent = df["purchase_intent"].isin(["possible", "strong"]).mean()
    strong = (df["purchase_intent"] == "strong").mean()
    langs = mix(df["language_type"])
    top = counted_clusters(df, "kmeans")[0]
    tiles = [
        {"key": "comments", "label": "Comments", "value": len(df)},
        {"key": "posts", "label": "Posts", "value": int(df["post_id"].nunique())},
        {"key": "purchase_intent", "label": "Purchase intent", "value": round(intent, 4), "format": "percent",
         "hint": f"strong {strong:.0%}"},
        {"key": "language_mix", "label": "Language mix", "value": next(iter(langs)), "breakdown": langs},
        {"key": "top_need", "label": "Top need", "value": top["name"], "cluster": top["id"],
         "share": top["share"]},
    ]
    summary = {"filters": filters, "n_comments": len(df), "n_posts": int(df["post_id"].nunique()),
               "purchase_intent_share": round(intent, 4), "strong_intent_share": round(strong, 4),
               "language_mix": langs, "sentiment_mix": mix(df["sentiment"]),
               "top_need": {"id": ref(top["id"]), "name": top["name"], "share": top["share"]},
               "is_synthetic": store.manifest.get("is_synthetic")}
    return result(summary, [ChartSpec(type="kpi_tiles", title="Overview", subtitle=_filters_label(filters),
                                      data={"tiles": tiles}, meta={"filters": filters})])


def get_need_clusters(brand: str | None = None, campaign: str | None = None, content_type: str | None = None,
                      algo: str = "kmeans") -> ToolResult:
    """Audience needs = clusters of comment embeddings (precomputed), with size/share inside the filters."""
    if algo not in ALGOS:
        raise ToolError(f"unknown algo '{algo}'; options: {', '.join(ALGOS)}")
    df, filters = subset(brand, campaign, content_type)
    if df.empty:
        return result({"filters": filters, "algo": algo, "n_comments": 0,
                       "note": "no comments match these filters"}, [])
    rows = counted_clusters(df, algo)
    col = f"{algo}_id"
    pts = points(sample_df(df), col)
    legend = [{"id": r["id"], "name": r["name"]} for r in rows]
    sub = _filters_label(filters)
    meta = {"algo": algo, "filters": filters, "n": len(df)}
    charts = [
        ChartSpec(type="scatter_embed", title="Need map", subtitle=f"{_ALGO_LABEL[algo]} · {sub}",
                  data={"points": pts, "clusters": legend}, meta={**meta, "sampled": len(pts) < len(df)}),
        ChartSpec(type="cluster_list", title="Audience needs", subtitle=f"{len(rows)} clusters · {sub}",
                  data={"clusters": rows}, meta=meta),
    ]
    summary = {"filters": filters, "algo": algo, "n_comments": len(df), "n_clusters": len(rows),
               "clusters": brief(rows)}
    if len(rows) > SUMMARY_CLUSTERS:
        summary["more_clusters"] = len(rows) - SUMMARY_CLUSTERS
    if algo == "dbscan":
        summary["noise_share"] = round(float((df["dbscan"] == -1).mean()), 4)
    return result(summary, charts)


def drill_down_cluster(cluster_id: str) -> ToolResult:
    """Sub-needs of one K-Means cluster (precomputed Ward sub-clustering, clusters with ≥80 comments)."""
    cid = norm_id(cluster_id)
    parent = store.clusters[cid]
    kids = sorted(store.children(cid), key=lambda c: -c["size"])
    base = {"cluster": {"id": ref(cid), "name": parent["name"], "size": parent["size"]}}
    if not kids:
        why = ("only K-Means clusters are split" if parent["algo"] != "kmeans" or "." in cid
               else "clusters under 80 comments are not split")
        return result({**base, "children": [], "note": f"no sub-needs for {ref(cid)}: {why}"}, [])
    rows = [cluster_row(k, k["size"], k["size"] / parent["size"]) for k in kids]
    root = {"id": cid, "name": parent["name"], "value": parent["size"],
            "children": [{"id": r["id"], "name": r["name"], "value": r["size"], "share": r["share"]} for r in rows]}
    meta = {"parent_id": cid}
    charts = [ChartSpec(type="sunburst", title=f"{parent['name']} → sub-needs",
                        subtitle=f"{cid} · {parent['size']} comments", data={"root": root}, meta=meta),
              ChartSpec(type="cluster_list", title=f"Sub-needs of {cid}", subtitle=parent["name"],
                        data={"clusters": rows}, meta=meta)]
    return result({**base, "children": brief(rows)}, charts)


def sample_comments(cluster_id: str, n: int = 8, language: str | None = None) -> ToolResult:
    """Real example comments: half nearest the cluster centroid, half random."""
    cid = norm_id(cluster_id)
    n = max(1, min(int(n), 30))
    df = members(cid)
    if language:
        lang = LANG_ALIASES.get(str(language).strip().lower())
        if not lang:
            raise ToolError(f"unknown language '{language}'; options: English, Roman Urdu, Urdu, Mixed")
        df = df[df["language_type"] == lang]
    c = store.clusters[cid]
    near_ids = [i for i in c.get("exemplar_ids") or [] if i in set(df["comment_id"])][: (n + 1) // 2]
    near = df.set_index("comment_id").loc[near_ids].reset_index() if near_ids else df.iloc[:0]
    rest = df[~df["comment_id"].isin(near_ids)]
    rand = rest.sample(min(len(rest), n - len(near)), random_state=42)
    cards = [card(r, "nearest") for _, r in near.iterrows()] + [card(r, "random") for _, r in rand.iterrows()]
    summary = {"cluster": {"id": ref(cid), "name": c["name"], "size": c["size"], "action": c["action"]},
               "language": language, "n_matching": len(df),
               "comments": [{"text": short(x["text"], 140), "language": x["language"], "sentiment": x["sentiment"],
                             "brand": x["brand"]} for x in cards]}
    return result(summary, [ChartSpec(type="comment_cards", title=f"Examples · {c['name']}",
                                      subtitle=f"{cid}" + (f" · {language}" if language else ""),
                                      data={"cards": cards}, meta={"cluster_id": cid})])


def get_unusual_comments(brand: str | None = None, n: int = 12) -> ToolResult:
    """Most unusual comments (DBSCAN noise / far from K-Means centroid / low GMM probability)."""
    df, filters = subset(brand)
    n = max(1, min(int(n), 50))
    unusual = df[df["unusual"].astype(bool)]
    top = unusual.sort_values("unusual_score", ascending=False).head(n)
    cards = [card(r, "unusual") for _, r in top.iterrows()]
    reasons = unusual["unusual_reasons"].fillna("").str.split(",").explode()
    reason_counts = {k: int(v) for k, v in reasons[reasons != ""].value_counts().items()}
    flag = df.set_index("comment_id")["unusual"].astype(bool)
    pts = points(sample_df(df, keep=df["unusual"].astype(bool)), "primary", flag)
    sub = _filters_label(filters)
    charts = [ChartSpec(type="comment_cards", title="Unusual comments", subtitle=f"top {len(cards)} · {sub}",
                        data={"cards": cards}, meta={"filters": filters}),
              ChartSpec(type="scatter_embed", title="Where the unusual comments sit", subtitle=sub,
                        data={"points": pts, "clusters": [{"id": c["cluster_id"], "name": c["name"]}
                                                          for c in store.top_level("kmeans")]},
                        meta={"filters": filters, "highlight": "unusual"})]
    summary = {"filters": filters, "n_comments": len(df), "n_unusual": len(unusual),
               "unusual_share": round(len(unusual) / len(df), 4) if len(df) else 0, "reason_counts": reason_counts,
               "top": [{"text": short(x["text"], 140), "reasons": x["reasons"], "cluster": ref(x["cluster"]),
                        "brand": x["brand"]} for x in cards]}
    return result(summary, charts)


MIN_BRAND_N = 50
OTHERS = "Others"


def need_share_by(group_by: str = "campaign") -> ToolResult:
    """Share of each K-Means need per campaign / brand / content type (100% per group)."""
    if group_by not in ("campaign", "brand", "content_type"):
        raise ToolError("group_by must be one of: campaign, brand, content_type")
    df = store.ensure().df
    keys = df[group_by]
    if group_by == "brand":  # brands with < MIN_BRAND_N comments pooled so shares aren't noise
        n = keys.value_counts()
        keys = keys.where(~keys.isin(n[n < MIN_BRAND_N].index), OTHERS)
    tab = pd.crosstab(keys, df["kmeans_id"])
    tab = tab.loc[sorted(tab.index, key=lambda g: (g == OTHERS, -tab.loc[g].sum()))]  # Others last
    order = [r["id"] for r in counted_clusters(df, "kmeans")]
    tab = tab[[c for c in order if c in tab.columns]]
    share = tab.div(tab.sum(axis=1), axis=0)
    overall = tab.sum() / tab.values.sum()
    groups = [str(g) for g in share.index]
    series = [{"id": c, "name": store.clusters[c]["name"], "values": [round(float(v), 4) for v in share[c]]}
              for c in share.columns]
    per_group = {}
    for g in share.index:
        s, lift = share.loc[g], share.loc[g] - overall
        per_group[str(g)] = {
            "n": int(tab.loc[g].sum()),
            "top_needs": [{"id": ref(c), "name": store.clusters[c]["name"], "share": round(float(s[c]), 4)}
                          for c in s.sort_values(ascending=False).index[:3]],
            "over_index": [{"id": ref(c), "name": store.clusters[c]["name"], "share": round(float(s[c]), 4),
                            "vs_overall": round(float(lift[c]), 4)}
                           for c in lift.sort_values(ascending=False).index[:2]]}
    label = group_by.replace("_", " ")
    chart = ChartSpec(type="stacked_bar", title=f"Needs by {label}", subtitle="share of comments per group (100%)",
                      data={"groups": groups, "series": series,
                            "counts": {g: per_group[g]["n"] for g in groups}},
                      meta={"group_by": group_by, "algo": "kmeans"})
    return result({"group_by": group_by, "groups": per_group}, [chart])


METRIC_COLS = ["k", "silhouette", "davies_bouldin", "calinski_harabasz", "stability_ari", "ari_true", "nmi_true",
               "noise_share"]


def compare_algorithms() -> ToolResult:
    """Clustering quality per algorithm + selection curves (silhouette vs k, BIC vs n)."""
    m = store.ensure().metrics
    rows = [{"algo": a, **{c: v.get(c) for c in METRIC_COLS}, "silhouette_pca50": v.get("silhouette_pca50")}
            for a, v in m["algorithms"].items()]
    best = {}
    for col, higher in (("silhouette", True), ("davies_bouldin", False), ("calinski_harabasz", True),
                        ("stability_ari", True), ("ari_true", True), ("nmi_true", True)):
        vals = [(r[col], r["algo"]) for r in rows if r.get(col) is not None]
        if vals:
            best[col] = (max if higher else min)(vals)[1]
    note = ("DBSCAN's silhouette/DB/CH are measured on its 10-D UMAP space (silhouette_pca50 is on the same "
            "PCA-50 space as the others); ari_true/nmi_true exist only for synthetic data with ground truth.")
    curves = m.get("curves", {})
    km, wd = curves.get("kmeans_silhouette", []), curves.get("ward_silhouette", [])
    ks = sorted({p["k"] for p in km + wd})
    sil = {"x": ks, "x_label": "k", "y_label": "silhouette",
           "series": [{"name": n, "values": [{p["k"]: p["silhouette"] for p in pts}.get(k) for k in ks]}
                      for n, pts in (("K-Means", km), ("Ward", wd)) if pts],
           "marks": [{"series": "K-Means", "x": m["algorithms"].get("kmeans", {}).get("k")},
                     {"series": "Ward", "x": m["algorithms"].get("ward", {}).get("k")}]}
    bic_pts = curves.get("gmm_bic", [])
    bic = {"x": [p["n"] for p in bic_pts], "x_label": "components", "y_label": "BIC (lower is better)",
           "series": [{"name": "GMM", "values": [p["bic"] for p in bic_pts]}],
           "marks": [{"series": "GMM", "x": m["algorithms"].get("gmm", {}).get("k")}]}
    charts = [ChartSpec(type="metrics_table", title="Algorithm comparison", subtitle=f"{m['n']} comments",
                        data={"columns": ["algo", *METRIC_COLS], "rows": rows, "best": best},
                        meta={"note": note, "has_true_need": m.get("has_true_need")}),
              ChartSpec(type="line", title="Silhouette vs k", subtitle="K-Means and Ward", data=sil),
              ChartSpec(type="line", title="GMM BIC vs components", subtitle="lower is better", data=bic)]
    summary = {"n": m["n"], "rows": rows, "best_by_metric": best, "raw_vs_gloss": m.get("raw_vs_gloss"),
               "primary": "kmeans", "note": note}
    return result(summary, charts)


_ALGO_LABEL = {"kmeans": "K-Means", "ward": "Ward", "dbscan": "DBSCAN", "gmm": "GMM"}


def _filters_label(f: dict) -> str:
    return " · ".join(f.values()) or "all brands"


TOOLS: dict[str, Callable[..., ToolResult]] = {f.__name__: f for f in (
    get_overview, get_need_clusters, drill_down_cluster, sample_comments, get_unusual_comments, need_share_by,
    compare_algorithms)}


def call_tool(name: str, args: dict | None = None) -> ToolResult:
    if name not in TOOLS:
        raise KeyError(name)
    fn = TOOLS[name]
    params = inspect.signature(fn).parameters
    args = {k: v for k, v in (args or {}).items() if v is not None}
    unknown = set(args) - set(params)
    if unknown:
        raise ToolError(f"{name}: unexpected argument(s) {sorted(unknown)}")
    missing = [p for p, spec in params.items() if spec.default is inspect.Parameter.empty and p not in args]
    if missing:
        raise ToolError(f"{name}: missing argument(s) {missing}")
    store.ensure()
    return fn(**args)


# ---------------------------------------------------------------- Gemini function declarations
def declarations() -> list[dict]:
    """JSON-schema function declarations; filter enums come from the loaded dataset."""
    o = store.ensure().options()
    s = lambda d, enum=None: {"type": "string", "description": d, **({"enum": enum} if enum else {})}  # noqa: E731
    brand, campaign = s("Brand filter; omit for all brands", o["brand"]), s("Campaign filter", o["campaign"])
    ctype = s("Post content type filter", o["content_type"])
    cid = s("Cluster id, e.g. C3 (K-Means), C3.1 (sub-need), W2/G2/D2 (Ward/GMM/DBSCAN)")
    obj = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}  # noqa: E731
    return [
        {"name": "get_overview", "description": "Counts of comments and posts, % purchase intent, language mix "
         "and the top need, optionally for one brand/campaign.", "parameters_json_schema":
         obj({"brand": brand, "campaign": campaign})},
        {"name": "get_need_clusters", "description": "What the audience wants: clusters of comments (needs) with "
         "name, share and recommended action, plus a 2-D map. Default algo kmeans.", "parameters_json_schema":
         obj({"brand": brand, "campaign": campaign, "content_type": ctype,
              "algo": s("Clustering algorithm (default kmeans)", ALGOS)})},
        {"name": "drill_down_cluster", "description": "Split one K-Means need into its sub-needs.",
         "parameters_json_schema": obj({"cluster_id": cid}, ["cluster_id"])},
        {"name": "sample_comments", "description": "Real example comments from one cluster (nearest to the "
         "centre plus random).", "parameters_json_schema": obj(
             {"cluster_id": cid, "n": {"type": "integer", "description": "How many (default 8, max 30)"},
              "language": s("Only this language", ["English", "Roman Urdu", "Urdu", "Mixed"])}, ["cluster_id"])},
        {"name": "get_unusual_comments", "description": "The weirdest / off-topic / outlier comments with the "
         "reasons they were flagged.", "parameters_json_schema": obj(
             {"brand": brand, "n": {"type": "integer", "description": "How many (default 12)"}})},
        {"name": "need_share_by", "description": "How the share of each need differs by campaign, brand or "
         "content type.", "parameters_json_schema": obj(
             {"group_by": s("Grouping (default campaign)", ["campaign", "brand", "content_type"])})},
        {"name": "compare_algorithms", "description": "Compare K-Means, Ward, DBSCAN and GMM: silhouette, "
         "Davies-Bouldin, Calinski-Harabasz, bootstrap stability, ARI vs ground truth; selection curves.",
         "parameters_json_schema": obj({})},
    ]
