import numpy as np
import pytest
from google.genai import errors
from pydantic import BaseModel
from tenacity import wait_none

from app import llm


class Out(BaseModel):
    x: int


def _api_error(code):
    return errors.ClientError(code, {"error": {"code": code, "message": "boom", "status": "X"}})


@pytest.fixture
def live(monkeypatch):
    """Non-mock mode; the SDK layer is still patched per test."""
    monkeypatch.delenv("MOCK_LLM")
    monkeypatch.setattr(llm, "_gates", {})


def test_cache_key_stable_and_sensitive():
    k = llm.cache_key("m", "p", {"a": 1, "b": 2})
    assert k == llm.cache_key("m", "p", {"b": 2, "a": 1})
    assert k != llm.cache_key("m2", "p", {"a": 1, "b": 2})
    assert k != llm.cache_key("m", "p2", {"a": 1, "b": 2})


def test_second_call_is_cache_hit(live, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_generate_raw", lambda *a: calls.append(a) or {"x": 1})
    a = llm.generate_json("prompt", Out, dataset="t", payload=[1])
    b = llm.generate_json("prompt", Out, dataset="t", payload=[1])
    assert a == b == {"x": 1} and len(calls) == 1
    assert len(list((llm.settings.cache_dir / "t" / "gen").glob("*.json"))) == 1


def test_cached_calls_do_not_count_against_rate_gate(live, monkeypatch):
    class Resp:
        parsed = Out(x=3)

    class Models:
        def generate_content(self, **kw):
            return Resp()

    monkeypatch.setattr(llm, "_client", lambda: type("C", (), {"models": Models()})())
    for _ in range(3):
        assert llm.generate_json("p", Out, dataset="t") == {"x": 3}
    assert len(llm.gate("test-batch").sent) == 1


def test_retry_on_429_then_success(live, monkeypatch):
    attempts = []

    def flaky(*a):
        attempts.append(1)
        if len(attempts) == 1:
            raise _api_error(429)
        return {"x": 2}

    monkeypatch.setattr(llm, "_sdk_generate", flaky)
    assert llm._generate_raw.retry_with(wait=wait_none())("m", "p", Out, None) == {"x": 2}
    assert len(attempts) == 2


def test_no_retry_on_400(live, monkeypatch):
    attempts = []
    monkeypatch.setattr(llm, "_sdk_generate", lambda *a: attempts.append(1) or (_ for _ in ()).throw(_api_error(400)))
    with pytest.raises(errors.ClientError):
        llm._generate_raw.retry_with(wait=wait_none())("m", "p", Out, None)
    assert len(attempts) == 1


def test_rate_gate_waits_when_window_full():
    now = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    g = llm.RateGate(2, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        with g.slot():
            now[0] += 1
    assert len(sleeps) == 1 and 57 < sleeps[0] < 61


def test_tag_batch_chunks_by_50(live, monkeypatch):
    sizes = []
    monkeypatch.setattr(llm, "_tag_chunk", lambda chunk, ds: sizes.append(len(chunk)) or llm._mock_tags(chunk))
    rows = llm.tag_batch([{"comment_id": f"c{i}", "text": "price plz"} for i in range(120)], dataset="t")
    assert sizes == [50, 50, 20] and [r["comment_id"] for r in rows] == [f"c{i}" for i in range(120)]


def test_mock_tags_schema():
    rows = llm.tag_batch([{"comment_id": "a", "text": "Karachi delivery kab hogi?"},
                          {"comment_id": "b", "text": "قیمت کیا ہے"}], dataset="t")
    for r in rows:
        llm.CommentTag(**r)
    assert rows[0]["city"] == "Karachi" and rows[1]["language_type"] == "Urdu"


def test_mock_embed_normalised_and_deterministic():
    a = llm.embed(["price plz", "love it"], dataset="t")
    assert a.shape == (2, 768) and np.allclose(np.linalg.norm(a, axis=1), 1)
    assert np.array_equal(a, llm.embed(["price plz", "love it"], dataset="t"))


def test_mock_name_and_chat():
    n = llm.name_cluster({"top_terms": ["price", "plz"]}, dataset="t")
    assert set(n) == {"name", "description", "action"}
    tools = [{"name": "get_overview", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    r1 = llm.chat([{"role": "user", "parts": [{"text": "hi"}]}], tools, "sys")
    assert r1["function_calls"][0]["name"] == "get_overview"
    r2 = llm.chat([{"role": "user"}, {"role": "model"}, {"role": "tool"}], tools, "sys")
    assert r2["text"] and not r2["function_calls"]


def test_missing_model_name_raises(live, monkeypatch):
    monkeypatch.setattr(llm.settings, "gemini_chat_model", "")
    with pytest.raises(RuntimeError, match="GEMINI_CHAT_MODEL"):
        llm.model_name("chat")
