"""Step 5: profile + name every cluster → clusters.json.

- K-Means clusters and their drill-down children: Gemini names (c-TF-IDF top terms over glosses, 8 comments
  nearest the centroid, stats), up to 15 clusters per call, cached.
- Ward / GMM / DBSCAN clusters: name, description and action copied from the K-Means cluster they overlap most
  (≥50% of members), else "Mixed: A + B" from the top two. No Gemini call.
- Off-topic is rule-based: a cluster whose glosses are ≥50% off-topic (spam, food, electronics, services…)
  gets the fixed Off-topic label. DBSCAN noise keeps its fixed label.
"""
import json
import re

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

from _cli import parser, processed_dir, setup_logging
from app import llm
from cluster import PREFIX

N_TERMS = 8
N_EXEMPLARS = 8
MAJORITY = 0.5
OFF_TOPIC_SHARE = 0.5
EXTRA_STOP = {"comment", "commenter", "user", "asks", "asking", "wants", "want", "says", "saying",
              "brand", "person", "expresses", "expressing", "question", "inquires", "inquiring"}
OFF_TOPIC = re.compile(
    r"\b(?:spam|gibberish|follows?|follow[- ]?backs?|followers?|earn(?:ing|ings)?|income|profit|trading|investment|"
    r"crypto|recipes?|biryani|nihari|sajji|falooda|raita|chutney|dahi|ice cream|restaurant|food|i?phones?|samsung|"
    r"redmi|nokia|macbook|laptops?|charger|bikes?|toys?|repair(?:man)?|mechanic|gym|dermatologist|coaching|ielts|"
    r"assignment|movies?|reels? viral|quran|prayer|mortality|unrelated|off[- ]topic)\b", re.I)
NOISE = {"name": "Unusual comments", "description": "Comments DBSCAN could not place in any dense need group.",
         "action": "Review these individually for spam, new topics, or one-off issues."}
OFF = {"name": "Off-topic / Spam",
       "description": "Mostly comments unrelated to the brand's clothes: spam, self-promotion, other products or services.",
       "action": "Exclude these from need analysis and hide or report clear spam."}
KEYS = ["cluster_id", "algo", "parent_id", "name", "description", "action", "size", "share", "top_terms",
        "exemplar_ids", "sentiment_mix", "intent_mix", "language_mix", "top_cities", "off_topic_share", "derived_from"]


def is_off_topic(gloss: pd.Series) -> pd.Series:
    return gloss.fillna("").str.contains(OFF_TOPIC)


def ctfidf_top_terms(docs: list[list[str]], n=N_TERMS) -> list[list[str]]:
    """Class-based TF-IDF: one 'document' per cluster. → top n terms per cluster."""
    cv = CountVectorizer(stop_words=list(ENGLISH_STOP_WORDS | EXTRA_STOP), token_pattern=r"(?u)\b[^\W\d_]{2,}\b")
    try:
        M = cv.fit_transform([" ".join(d) for d in docs]).toarray().astype(float)
    except ValueError:  # empty vocabulary
        return [[] for _ in docs]
    tf = M / np.clip(M.sum(axis=1, keepdims=True), 1, None)
    idf = np.log(1 + M.sum() / len(docs) / np.clip(M.sum(axis=0), 1, None))
    score, vocab = tf * idf, cv.get_feature_names_out()
    return [[vocab[j] for j in np.argsort(-row)[:n] if row[j] > 0] for row in score]


def mix(s: pd.Series) -> dict:
    return {str(k): round(float(v), 3) for k, v in s.value_counts(normalize=True).items()}


def nearest_to_centroid(X: np.ndarray, idx: np.ndarray, n=N_EXEMPLARS) -> np.ndarray:
    c = X[idx].mean(axis=0)
    return idx[np.argsort(np.linalg.norm(X[idx] - c, axis=1))[:n]]


def profile(df: pd.DataFrame, idx: np.ndarray, exemplars: np.ndarray, total: int) -> dict:
    g = df.iloc[idx]
    cities = g["city"].dropna().value_counts().head(5)
    return {"size": int(len(idx)), "share": round(len(idx) / total, 4),
            "exemplar_ids": df["comment_id"].iloc[exemplars].tolist(),
            "sentiment_mix": mix(g["sentiment"]), "intent_mix": mix(g["purchase_intent"]),
            "language_mix": mix(g["language_type"]), "top_cities": {str(k): int(v) for k, v in cities.items()},
            "off_topic_share": round(float(g["off_topic"].mean()), 3)}


def group_clusters(df, X, groups: list[tuple[str, np.ndarray]], algo, parent_id=None) -> list[dict]:
    """groups: [(cluster_id, row indices)] that share one c-TF-IDF space (an algorithm, or siblings)."""
    terms = ctfidf_top_terms([df["gloss"].iloc[idx].tolist() for _, idx in groups])
    out = []
    for (cid, idx), top in zip(groups, terms):
        noise = algo == "dbscan" and cid == "D0"
        ex = (idx[np.argsort(-df["unusual_score"].to_numpy()[idx])[:N_EXEMPLARS]] if noise
              else nearest_to_centroid(X, idx))
        out.append({"cluster_id": cid, "algo": algo, "parent_id": parent_id, "top_terms": top,
                    **profile(df, idx, ex, len(df)), "derived_from": None, "_idx": idx, "_noise": noise})
    return out


def build_profiles(df: pd.DataFrame, X: np.ndarray) -> list[dict]:
    """df: comment_clusters ⋈ tags ⋈ text (+ off_topic flag), aligned with X rows."""
    rows = []
    for algo, prefix in PREFIX.items():
        labels = df[algo].to_numpy()
        groups = [(f"{prefix}{v if v >= 0 else 0}", np.flatnonzero(labels == v))
                  for v in sorted(set(labels), key=lambda v: (v < 0, v))]
        rows += group_clusters(df, X, groups, algo)
        if algo == "kmeans":
            for parent in sorted(df["sub"].dropna().str.split(".").str[0].unique(), key=lambda s: int(s[1:])):
                subs = df["sub"].where(df["primary"] == parent)
                kids = sorted(subs.dropna().unique(), key=lambda s: int(s.split(".")[1]))
                rows += group_clusters(df, X, [(k, np.flatnonzero(subs == k)) for k in kids], algo, parent)
    return rows


def gemini_payload(p: dict, df: pd.DataFrame, parent_name: str | None = None) -> dict:
    ex = df.set_index("comment_id").loc[p["exemplar_ids"]]
    payload = {k: p[k] for k in ("cluster_id", "size", "share", "top_terms", "sentiment_mix", "intent_mix",
                                 "language_mix", "top_cities")}
    payload["examples"] = [{"text": t, "gloss": g} for t, g in zip(ex["text"], ex["gloss"])]
    if parent_name:
        payload["parent_cluster_name"] = parent_name
    return payload


def derive(p: dict, primary: pd.Series, kmeans_names: dict[str, dict]) -> dict:
    """Name a Ward/GMM/DBSCAN cluster from its majority K-Means cluster (≥50%), else 'Mixed: A + B'."""
    share = primary.iloc[p["_idx"]].value_counts(normalize=True)
    top = [(cid, float(s)) for cid, s in share.head(2).items()]
    a, pa = top[0]
    derived = {cid: round(s, 3) for cid, s in top}
    if pa >= MAJORITY or len(top) == 1:
        return {**kmeans_names[a], "derived_from": derived}
    b, pb = top[1]
    A, B = kmeans_names[a]["name"], kmeans_names[b]["name"]
    return {"name": f"Mixed: {A} + {B}", "description": f"Mix of {A} ({pa:.0%}) and {B} ({pb:.0%}) comments.",
            "action": kmeans_names[a]["action"], "derived_from": derived}


def name_all(profiles: list[dict], df: pd.DataFrame, dataset: str) -> list[dict]:
    off = lambda p: p["off_topic_share"] >= OFF_TOPIC_SHARE  # noqa: E731
    km = [p for p in profiles if p["algo"] == "kmeans" and not p["parent_id"]]
    kids = [p for p in profiles if p["algo"] == "kmeans" and p["parent_id"]]
    names = {p["cluster_id"]: OFF for p in km if off(p)}
    names.update(llm.name_clusters([gemini_payload(p, df) for p in km if not off(p)], dataset=dataset))
    names.update({p["cluster_id"]: OFF for p in kids if off(p)})
    names.update(llm.name_clusters([gemini_payload(p, df, names[p["parent_id"]]["name"]) for p in kids if not off(p)],
                                   dataset=dataset))
    km_names = {p["cluster_id"]: names[p["cluster_id"]] for p in km}
    for p in profiles:
        if p.pop("_noise"):
            p.update(NOISE)
        elif off(p):
            p.update(OFF)
        elif p["algo"] == "kmeans":
            p.update(names[p["cluster_id"]])
        else:
            p.update(derive(p, df["primary"], km_names))
    return [{k: p[k] for k in KEYS} for p in profiles]


def load_joined(d) -> pd.DataFrame:
    cc = pd.read_parquet(d / "comment_clusters.parquet")
    tags = pd.read_parquet(d / "comment_tags.parquet")
    text = pd.read_parquet(d / "comments.parquet")[["comment_id", "text", "true_need"]]
    df = cc.merge(tags, on="comment_id", how="left").merge(text, on="comment_id", how="left")
    df["off_topic"] = is_off_topic(df["gloss"])
    return df


def main() -> None:
    args = parser("Step 5: cluster naming").parse_args()
    setup_logging()
    d = processed_dir(args.dataset)
    df, X = load_joined(d), np.load(d / "x_pca.npy")
    profiles = build_profiles(df, X)
    n_gem = sum(p["algo"] == "kmeans" and p["off_topic_share"] < OFF_TOPIC_SHARE for p in profiles)
    print(f"name [{args.dataset}]: {len(profiles)} clusters, {n_gem} named by Gemini in batches of "
          f"{llm.NAME_BATCH}, the rest derived from K-Means", flush=True)
    clusters = name_all(profiles, df, args.dataset)
    (d / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False, indent=1))
    print(f"name [{args.dataset}]: wrote {len(clusters)} clusters "
          f"({sum(c['name'] == OFF['name'] for c in clusters)} off-topic)")


if __name__ == "__main__":
    main()
