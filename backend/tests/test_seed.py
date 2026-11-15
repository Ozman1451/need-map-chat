import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
import seed_synthetic as seed  # noqa: E402

from app.llm import NEEDS  # noqa: E402

COMMENT_COLS = ["comment_id", "post_id", "user_hash", "text", "created_at", "is_synthetic", "true_need"]


def test_need_weights_vary_by_campaign():
    sale, regular = seed.need_weights("12.12", "Reel"), seed.need_weights("Regular", "Reel")
    assert abs(sum(sale.values()) - 1) < 1e-9 and set(sale) == set(NEEDS)
    assert sale["discount_request"] > 2 * regular["discount_request"]
    assert seed.need_weights("Eid", "Reel")["delivery_time"] > regular["delivery_time"]


def test_plan_calls_batches_of_25():
    import numpy as np
    rng = np.random.default_rng(0)
    posts = seed.make_posts(12, rng)
    calls = seed.plan_calls(posts, 500, 10, rng)
    assert all(sum(s["count"] for s in slots) <= 25 for _, slots in calls)
    assert sum(s["count"] for c in calls if c[0] == "off_topic" for s in c[1]) == 10


def test_seed_mock_run(tmp_path):
    env = {**os.environ, "MOCK_LLM": "1", "GEMINI_BATCH_MODEL": "test-batch", "CACHE_ROOT": str(tmp_path / "c")}
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "seed_synthetic.py"), "--posts", "8",
                        "--comments", "200", "--odd", "6", "--out", str(tmp_path)],
                       capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    posts, comments = pd.read_parquet(tmp_path / "posts.parquet"), pd.read_parquet(tmp_path / "comments.parquet")
    assert list(comments.columns) == COMMENT_COLS and len(posts) == 8
    assert len(comments) > 100 and comments["comment_id"].is_unique
    assert (comments["is_synthetic"] == 1).all() and (posts["is_synthetic"] == 1).all()
    assert set(comments["true_need"]) <= set(NEEDS) | {"off_topic"}
    assert comments["user_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert comments["post_id"].isin(posts["post_id"]).all()
    assert posts["comments_count"].sum() == len(comments)
    assert not (tmp_path / "c").exists()  # mock never writes cache
