import json

import pytest
from fastapi.testclient import TestClient

from app import tools
from app.main import app
from app.schemas import ChartSpec

CALLS = [
    ("get_overview", {}),
    ("get_overview", {"brand": "khaadi"}),
    ("get_need_clusters", {}),
    *[("get_need_clusters", {"algo": a}) for a in ("ward", "dbscan", "gmm")],
    ("get_need_clusters", {"brand": "Sapphire", "campaign": "Eid"}),
    ("drill_down_cluster", {"cluster_id": "[C1]"}),
    ("sample_comments", {"cluster_id": "C1", "n": 6}),
    ("get_unusual_comments", {"n": 5}),
    *[("need_share_by", {"group_by": g}) for g in ("campaign", "brand", "content_type")],
    ("compare_algorithms", {}),
]
EXPECTED = {"get_overview": ["kpi_tiles"], "get_need_clusters": ["scatter_embed", "cluster_list"],
            "sample_comments": ["comment_cards"], "get_unusual_comments": ["comment_cards", "scatter_embed"],
            "need_share_by": ["stacked_bar"], "compare_algorithms": ["metrics_table", "line", "line"]}
DATA_KEYS = {"kpi_tiles": {"tiles"}, "scatter_embed": {"points", "clusters"}, "cluster_list": {"clusters"},
             "sunburst": {"root"}, "comment_cards": {"cards"}, "stacked_bar": {"groups", "series", "counts"},
             "metrics_table": {"columns", "rows", "best"}, "line": {"x", "series"}}


@pytest.mark.parametrize("name,args", CALLS, ids=lambda x: str(x))
def test_tool_returns_valid_chartspecs(loaded_store, name, args):
    res = tools.call_tool(name, args)
    payload = json.loads(res.model_dump_json())  # JSON-serialisable (no numpy / NaN)
    assert set(payload) == {"summary", "charts"} and payload["summary"]["dataset"] == "sample"
    if name in EXPECTED:
        assert [c["type"] for c in payload["charts"]] == EXPECTED[name]
    for c in payload["charts"]:
        ChartSpec.model_validate(c)
        assert DATA_KEYS[c["type"]] <= set(c["data"]), c["type"]
        if c["type"] == "scatter_embed":
            assert 0 < len(c["data"]["points"]) <= tools.MAX_POINTS
            assert {"x", "y", "cluster", "text", "id"} <= set(c["data"]["points"][0])
        if c["type"] == "stacked_bar":
            for i in range(len(c["data"]["groups"])):
                assert sum(s["values"][i] for s in c["data"]["series"]) == pytest.approx(1, abs=1e-2)
    if "clusters" in payload["summary"]:
        assert payload["summary"]["clusters"][0]["id"].startswith("[")


def test_cluster_shares_and_filters(loaded_store):
    s = tools.call_tool("get_need_clusters", {"brand": "Khaadi"}).summary
    assert s["filters"] == {"brand": "Khaadi"}
    n = (loaded_store.df["brand"] == "Khaadi").sum()
    assert s["n_comments"] == n and sum(c["size"] for c in s["clusters"]) == n


def test_drill_down_children(loaded_store):
    parents = [c for c in loaded_store.top_level("kmeans") if loaded_store.children(c["cluster_id"])]
    small = [c for c in loaded_store.top_level("kmeans") if not loaded_store.children(c["cluster_id"])]
    if parents:
        res = tools.call_tool("drill_down_cluster", {"cluster_id": parents[0]["cluster_id"]})
        assert [c.type for c in res.charts] == ["sunburst", "cluster_list"]
        assert res.charts[0].data["root"]["children"]
    res = tools.call_tool("drill_down_cluster", {"cluster_id": small[0]["cluster_id"]})
    assert res.charts == [] and "note" in res.summary


def test_bad_args_raise_tool_error(loaded_store):
    for name, args in [("drill_down_cluster", {"cluster_id": "C999"}), ("get_overview", {"brand": "Nike"}),
                       ("need_share_by", {"group_by": "city"}), ("get_need_clusters", {"algo": "hdbscan"}),
                       ("sample_comments", {}), ("compare_algorithms", {"x": 1})]:
        with pytest.raises(tools.ToolError):
            tools.call_tool(name, args)


def test_declarations_cover_tools(loaded_store):
    decls = tools.declarations()
    assert [d["name"] for d in decls] == list(tools.TOOLS)
    brand = decls[0]["parameters_json_schema"]["properties"]["brand"]
    assert set(brand["enum"]) == set(loaded_store.df["brand"].unique())


def test_api_tool_manifest_dataset(loaded_store):
    c = TestClient(app)
    r = c.post("/api/tool/get_need_clusters", json={"algo": "gmm"})
    assert r.status_code == 200 and r.json()["charts"][0]["type"] == "scatter_embed"
    assert c.post("/api/tool/compare_algorithms").status_code == 200
    assert c.post("/api/tool/nope", json={}).status_code == 404
    assert c.post("/api/tool/drill_down_cluster", json={"cluster_id": "C999"}).status_code == 400
    m = c.get("/api/manifest").json()
    assert m["dataset"] == "sample" and "sample" in m["datasets"] and m["options"]["brand"]
    assert c.post("/api/dataset", json={"name": "sample"}).json()["dataset"] == "sample"
    assert c.post("/api/dataset", json={"name": "nope"}).status_code == 404


def test_small_brands_grouped_as_others(loaded_store, monkeypatch):
    df = loaded_store.df
    keep = df["brand"].value_counts().index[0]
    monkeypatch.setattr(tools, "MIN_BRAND_N", int((df["brand"] == keep).sum()))
    groups = tools.need_share_by("brand").charts[0].data["groups"]
    assert groups == [keep, tools.OTHERS]
