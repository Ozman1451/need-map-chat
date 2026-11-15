from pathlib import Path

import pandas as pd

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"


def test_sample_fixture():
    comments, posts = pd.read_parquet(SAMPLE / "comments.parquet"), pd.read_parquet(SAMPLE / "posts.parquet")
    assert len(comments) == 200 and comments["comment_id"].is_unique
    assert comments["post_id"].isin(posts["post_id"]).all()
    assert {"text", "user_hash", "is_synthetic", "true_need"} <= set(comments.columns)
    assert {"brand", "campaign", "content_type", "caption", "source"} <= set(posts.columns)
    assert comments["true_need"].nunique() >= 8 and (comments["true_need"] == "off_topic").any()
    assert posts["brand"].nunique() == 3
