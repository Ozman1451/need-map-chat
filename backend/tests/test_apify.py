"""Apify scraper / mapper / CSV import on fake Apify JSON — no network, MOCK_LLM inference."""
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
import clean  # noqa: E402
import import_csv  # noqa: E402
import map_apify  # noqa: E402
import scrape_apify as sa  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "apify"
USERNAMES = ["ayesha_k", "Sana.R", "zara99", "hina_m", "maria.b", "nida_x", "sapphirepakistan"]

TARGETS = {
    "brands": [{"name": "Sapphire", "instagram": "sapphirepakistan"},
               {"name": "Khaadi", "instagram": "khaadiofficial"},
               {"name": "Gul Ahmed", "instagram": "gulahmedfashion"}],
    "since": "2026-03-01", "caption_keywords": ["lawn"], "max_posts_per_brand": 30, "scan_posts_per_brand": 60,
    "max_comments_per_post": 15, "max_budget_usd": 4.50, "post_urls": [],
    "actors": {"profile": "apify/instagram-profile-scraper", "posts": "apify/instagram-post-scraper",
               "comments": "apify/instagram-comment-scraper"},
    "price_per_1k": {"profile": 2.70, "posts": 2.70, "comments": 2.60},
    "start_fee_usd": {"profile": 0, "posts": 0, "comments": 0},
}


def fixture(name):
    return json.loads((FIX / name).read_text("utf-8"))


class FakeRun:
    def __init__(self, rid, ds, items):
        self.id, self.default_dataset_id, self.status = rid, ds, "SUCCEEDED"
        self.usage_total_usd = round(len(items) * 0.0026, 4)


class FakeActor:
    def __init__(self, client, actor_id):
        self.client, self.actor_id = client, actor_id

    def call(self, *, run_input, max_items, max_total_charge_usd):
        self.client.calls.append((self.actor_id, run_input, max_items, max_total_charge_usd))
        if self.actor_id.endswith("profile-scraper"):
            items = [p for p in fixture("profiles.json") if p["username"] in run_input["usernames"]]
        elif self.actor_id.endswith("post-scraper"):
            wanted = run_input["username"]
            posts = fixture("posts.json")
            if any(w.startswith("http") for w in wanted):
                items = [p for p in posts if p["url"] in wanted]
            else:
                since = pd.Timestamp(run_input["onlyPostsNewerThan"], tz="UTC")
                items = []
                for owner in wanted:
                    mine = [p for p in posts if p["ownerUsername"] == owner and pd.Timestamp(p["timestamp"]) >= since
                            and not (run_input.get("skipPinnedPosts") and p.get("isPinned"))]
                    items += mine[:run_input["resultsLimit"]]
        else:
            code = run_input["directUrls"][0].rstrip("/").rsplit("/", 1)[-1]
            f = FIX / f"comments_{code}.json"
            items = fixture(f.name)[:run_input["resultsLimit"]] if f.exists() else []
        items = items[:max_items]
        rid = f"run{len(self.client.calls)}"
        self.client.datasets[rid + "ds"] = items
        return FakeRun(rid, rid + "ds", items)


class FakeDataset:
    def __init__(self, items):
        self.items = items

    def iterate_items(self):
        yield from self.items


class FakeClient:
    def __init__(self):
        self.calls, self.datasets = [], {}

    def actor(self, actor_id):
        return FakeActor(self, actor_id)

    def dataset(self, ds_id):
        return FakeDataset(self.datasets[ds_id])


@pytest.fixture
def scraped(tmp_path):
    client = FakeClient()
    posts, comments = sa.scrape(copy.deepcopy(TARGETS), client, tmp_path / "real", tmp_path / "real" / "runs.jsonl")
    return posts, comments, client, tmp_path / "real"


def test_filter_posts_since_keyword_cap():
    items = fixture("posts.json")
    assert [i["shortCode"] for i in map_apify.filter_posts(items, TARGETS)] == ["KHA1", "SAP1", "SAP2"]
    capped = map_apify.filter_posts(items, {**TARGETS, "max_posts_per_brand": 1})
    assert [i["shortCode"] for i in capped] == ["KHA1", "SAP1"]
    assert len(map_apify.filter_posts(items, {**TARGETS, "post_urls": ["x"]})) == 5


def test_media_content_type():
    f = map_apify.media_content_type
    assert f({"type": "Video", "productType": "clips"}) == "Reel" and f({"type": "Video"}) == "Reel"
    assert f({"type": "Sidecar"}) == "Carousel" and f({"type": "Image"}) == "Product Photo" and f({}) == "Other"


def test_mapped_schema_provenance_inference(scraped):
    posts, comments, _, base = scraped
    assert list(posts.columns) == map_apify.POST_COLS and list(comments.columns) == map_apify.COMMENT_COLS
    assert set(posts["post_id"]) == {"SAP1", "SAP2", "KHA1"}
    p = posts.set_index("post_id")
    assert p.loc["SAP1", "content_type"] == "Reel" and p.loc["SAP1", "campaign"] == "Summer Lawn"
    assert p.loc["SAP1", "infer_method"] == "media_type+rules"
    assert p.loc["SAP2", "content_type"] == "Carousel" and p.loc["SAP2", "campaign"] == "Eid"
    assert p.loc["KHA1", "content_type"] == "Sale Announcement" and p.loc["KHA1", "infer_method"] == "rules"
    assert pd.isna(p.loc["KHA1", "likes"]) and p.loc["KHA1", "brand"] == "Khaadi"
    for df in (posts, comments):
        assert (df["source"] == "apify").all() and (df["is_synthetic"] == 0).all()
        assert df["apify_run_id"].notna().all() and df["apify_actor"].notna().all() and df["collected_at"].notna().all()
    assert len(comments) == 7  # c2 duplicate dropped, reply r1 not a row
    assert comments["comment_id"].is_unique and comments["true_need"].isna().all()
    assert (comments["url"] == comments["post_id"].map(p["url"])).all()
    brands = json.loads((base / "brands.json").read_text())
    assert {b["brand"]: b["followers"] for b in brands}["Khaadi"] == 5200000
    assert set(pd.read_parquet(base / "posts.parquet")["post_id"]) == set(posts["post_id"])


def test_usernames_hashed_and_user_fields_dropped(scraped):
    _, comments, _, base = scraped
    want = hashlib.sha256(b"sana.r").hexdigest()
    assert want in set(comments["user_hash"]) and comments["user_hash"].str.len().eq(64).all()
    blob = (base / "comments.parquet").read_bytes() + (base / "posts.parquet").read_bytes()
    for u in USERNAMES[:-1]:
        assert u.encode() not in blob
    assert b"https://pic/" not in blob and b"DM sent" not in blob


def test_clean_accepts_mapped_comments(scraped):
    _, comments, _, _ = scraped
    out, stats = clean.clean_comments(comments)
    assert stats["dropped_no_content"] == 1 and len(out) == 6  # emoji-only dropped


def test_runs_log_and_server_caps(scraped):
    _, _, client, base = scraped
    rows = [json.loads(line) for line in (base / "runs.jsonl").read_text().splitlines()]
    assert [r["step"] for r in rows] == ["profile", "posts", "comments", "comments", "comments"]
    assert all({"actor", "run_id", "items", "est_cost", "usage_usd"} <= set(r) for r in rows)
    post_call = client.calls[1]
    assert post_call[1] == {"username": ["sapphirepakistan", "khaadiofficial", "gulahmedfashion"], "resultsLimit": 60,
                            "onlyPostsNewerThan": "2026-03-01", "skipPinnedPosts": True}
    assert post_call[2] == 180
    comment_call = client.calls[2]
    assert comment_call[1]["resultsLimit"] == 15 and comment_call[2] == 15
    assert float(comment_call[3]) == pytest.approx(0.039)


def test_resume_is_idempotent(scraped, tmp_path):
    posts, comments, _, base = scraped
    again = FakeClient()
    p2, c2 = sa.scrape(copy.deepcopy(TARGETS), again, base, base / "runs.jsonl")
    assert again.calls == [] and len(p2) == len(posts) and len(c2) == len(comments)
    (base / "apify" / "comments" / "SAP2.json").unlink()
    third = FakeClient()
    sa.scrape(copy.deepcopy(TARGETS), third, base, base / "runs.jsonl")
    assert [c[0] for c in third.calls] == ["apify/instagram-comment-scraper"]


def test_estimate_cost_matches_plan():
    est = sa.estimate_cost(TARGETS)
    assert est["profile"] == pytest.approx(0.0081) and est["posts"] == pytest.approx(0.486)
    assert est["comments"] == pytest.approx(3.51) and est["total"] == pytest.approx(4.0041)
    fee = sa.estimate_cost({**TARGETS, "start_fee_usd": {"profile": 0, "posts": 0, "comments": 0.01}})
    assert fee["comments"] == pytest.approx(3.51 + 90 * 0.01)
    old = sa.estimate_cost({**TARGETS, "max_comments_per_post": 20})
    assert old["total"] > TARGETS["max_budget_usd"]


def test_budget_guard_aborts_before_any_call(tmp_path):
    client = FakeClient()
    with pytest.raises(sa.BudgetExceeded):
        sa.scrape({**TARGETS, "max_budget_usd": 1.0}, client, tmp_path / "real", tmp_path / "runs.jsonl")
    assert client.calls == [] and not (tmp_path / "runs.jsonl").exists()


def test_budget_counts_previous_spend(tmp_path):
    log = tmp_path / "runs.jsonl"
    log.write_text(json.dumps({"step": "comments", "est_cost": 9.0, "usage_usd": 1.0}) + "\n"
                   + json.dumps({"step": "comments", "est_cost": 0.04, "usage_usd": None}) + "\n")
    assert sa.spent_so_far(log) == pytest.approx(1.04)
    client = FakeClient()
    with pytest.raises(sa.BudgetExceeded):  # 1.04 spent + 4.00 worst case > 4.50
        sa.scrape(copy.deepcopy(TARGETS), client, tmp_path / "real", log)
    with pytest.raises(sa.BudgetExceeded):  # per-run guard: no call once a single run would cross the budget
        sa.run_actor(client, {**TARGETS, "max_budget_usd": 1.05}, "comments", {}, 15, log, dry=False)
    assert client.calls == []


def test_dry_run_is_tiny(tmp_path):
    d = sa.dry_targets(TARGETS)
    assert len(d["brands"]) == 1 and d["max_posts_per_brand"] == 2 and d["max_comments_per_post"] == 10
    assert sa.estimate_cost(d)["total"] < 0.1 and TARGETS["max_comments_per_post"] == 15  # original untouched
    posts, comments = sa.scrape(d, FakeClient(), tmp_path / "real" / "dry", tmp_path / "runs.jsonl", dry=True)
    assert set(posts["brand"]) == {"Sapphire"} and len(posts) == 2 and len(comments) <= 20
    assert (tmp_path / "real" / "dry" / "posts.parquet").exists()
    assert all(json.loads(line)["dry"] for line in (tmp_path / "runs.jsonl").read_text().splitlines())


def test_post_urls_skip_discovery_and_filter(tmp_path):
    t = {**TARGETS, "post_urls": ["https://www.instagram.com/p/SAP3/"]}
    assert sa.plan_runs(t)["comments"]["runs"] == 1
    client = FakeClient()
    posts, _ = sa.scrape(t, client, tmp_path / "real", tmp_path / "runs.jsonl")
    assert client.calls[1][1] == {"username": t["post_urls"]}
    assert list(posts["post_id"]) == ["SAP3"]  # kept although its caption has no "lawn"


def test_import_csv_round_trip(tmp_path):
    pd.DataFrame([
        {"post_id": "M1", "brand": "Khaadi", "url": "https://www.instagram.com/p/M1/", "posted_at": "2026-04-01",
         "caption": "Eid lawn collection", "likes": 10, "content_type": "Reel", "campaign": ""},
        {"post_id": "M2", "brand": "Sapphire", "url": "https://www.instagram.com/p/M2/", "posted_at": "2026-04-02",
         "caption": "anything", "content_type": "Carousel", "campaign": "Winter"},
    ]).to_csv(tmp_path / "p.csv", index=False)
    pd.DataFrame([
        {"comment_id": "m1", "post_id": "M1", "username": "Sana.R", "text": "Price?", "created_at": "2026-04-01T10:00Z"},
        {"comment_id": "m2", "post_id": "M2", "username": "hina_m", "text": "Size?"},
        {"comment_id": "m3", "post_id": "NOPE", "username": "x", "text": "lost"},
    ]).to_csv(tmp_path / "c.csv", index=False)
    out = tmp_path / "real"
    posts, comments = import_csv.import_csv(tmp_path / "p.csv", tmp_path / "c.csv", out)
    assert list(posts.columns) == map_apify.POST_COLS and list(comments.columns) == map_apify.COMMENT_COLS
    p = posts.set_index("post_id")
    assert p.loc["M1", "campaign"] == "Eid" and p.loc["M1", "content_type"] == "Reel"
    assert p.loc["M1", "infer_method"] == "given+rules" and p.loc["M2", "infer_method"] == "given"
    assert (posts["source"] == "manual").all() and (comments["is_synthetic"] == 0).all()
    assert set(comments["comment_id"]) == {"m1", "m2"}
    assert comments.set_index("comment_id").loc["m1", "user_hash"] == hashlib.sha256(b"sana.r").hexdigest()
    assert b"Sana.R" not in (out / "comments.parquet").read_bytes()
    posts2, comments2 = import_csv.import_csv(tmp_path / "p.csv", tmp_path / "c.csv", out)
    assert len(posts2) == 2 and len(comments2) == 2
    with pytest.raises(ValueError, match="caption"):
        import_csv.prepare_posts(pd.DataFrame([{"post_id": "x"}]), pd.Timestamp.now(tz="UTC"))


def test_targets_yaml_is_complete():
    t = map_apify.load_targets()
    assert set(TARGETS) <= set(t)
    assert all(s in t["price_per_1k"] and s in t["start_fee_usd"] and s in t["actors"] for s in sa.STEPS)


def test_cli_estimate_offline_and_rejects_synthetic():
    env = {**os.environ, "MOCK_LLM": "1", "APIFY_TOKEN": ""}
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "scrape_apify.py"), "--estimate"],
                       capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    assert "full-run cost plan" in r.stdout and "dry-run cost plan" in r.stdout
    for script in ("scrape_apify.py", "map_apify.py"):
        r = subprocess.run([sys.executable, str(ROOT / "pipeline" / script), "--dataset", "synthetic"],
                           capture_output=True, text=True, timeout=60, env=env)
        assert r.returncode != 0
