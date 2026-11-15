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
    n = llm.name_clusters([{"cluster_id": "C1", "top_terms": ["price", "plz"]}], dataset="t")
    assert set(n) == {"C1"} and set(n["C1"]) == {"name", "description", "action"}
    tools = [{"name": n, "description": "d", "parameters_json_schema": {"type": "object", "properties": {}}}
             for n in ("get_need_clusters", "drill_down_cluster", "get_overview")]
    r1 = llm.chat([llm.user_content("Split [C3] further")], tools, "sys")
    assert r1["function_calls"][0] == {"id": "mock-1", "name": "drill_down_cluster", "args": {"cluster_id": "C3"}}
    assert r1["content"].role == "model" and r1["content"].parts[0].function_call.name == "drill_down_cluster"
    r0 = llm.chat([llm.user_content("hi")], tools, "sys")
    assert r0["function_calls"][0]["name"] == "get_need_clusters"
    resp = llm.responses_content([{"id": "mock-1", "name": "get_overview", "response": {"n": 1}}])
    r2 = llm.chat([llm.user_content("hi"), r1["content"], resp], tools, "sys")
    assert r2["text"] and not r2["function_calls"]


def test_missing_model_name_raises(live, monkeypatch):
    monkeypatch.setattr(llm.settings, "gemini_chat_model", "")
    with pytest.raises(RuntimeError, match="GEMINI_CHAT_MODEL"):
        llm.model_name("chat")


def test_rate_gate_throttles_tokens_per_minute():
    now = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    g = llm.RateGate(100, tpm=1000, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        with g.slot(600):
            now[0] += 1
    assert len(sleeps) == 2 and all(55 < s < 61 for s in sleeps)


def test_rate_gate_counts_batch_texts_as_units():
    now = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    g = llm.RateGate(100, clock=lambda: now[0], sleep=sleep)
    for _ in range(2):
        with g.slot(units=100):  # a full 100-text embed batch uses the whole minute
            now[0] += 1
    assert len(sleeps) == 1 and 57 < sleeps[0] < 61


def test_parse_json_lenient():
    class Names(llm.BaseModel):
        clusters: list[llm.NamedCluster]
    item = {"cluster_id": "C1", "name": "Price", "description": "d.", "action": "Do it."}
    import json as _j
    assert llm.parse_json("```json\n" + _j.dumps({"clusters": [item]}) + "\n```", Names)["clusters"][0]["name"] == "Price"
    assert llm.parse_json("Sure! " + _j.dumps([item]) + " hope this helps", Names)["clusters"][0]["cluster_id"] == "C1"
    with pytest.raises(ValueError):
        llm.parse_json("no json here", Names)


def test_gemma_uses_prompt_json_and_retries_once(monkeypatch):
    replies = iter(["not json", '{"clusters": [{"cluster_id": "C1", "name": "n", "description": "d", "action": "a"}]}'])
    prompts = []

    class R:
        def __init__(self, t):
            self.text = t
    monkeypatch.setattr(llm, "_call", lambda model, prompt, cfg: prompts.append((prompt, cfg)) or R(next(replies)))
    out = llm._sdk_generate("gemma-4-31b", "name these", llm.ClusterNames, 0.2)
    assert out["clusters"][0]["name"] == "n" and len(prompts) == 2
    assert "JSON Schema" in prompts[0][0] and prompts[0][1].response_schema is None
    replies2 = iter(["bad", "still bad"])
    monkeypatch.setattr(llm, "_call", lambda *a: R(next(replies2)))
    with pytest.raises(RuntimeError, match="invalid JSON twice"):
        llm._sdk_generate("gemma-4-31b", "p", llm.ClusterNames, None)


def test_structured_400_falls_back_to_prompt_json(monkeypatch):
    calls = []

    class R:
        text = '{"clusters": []}'
        parsed = None

    def call(model, prompt, cfg):
        calls.append(cfg.response_schema)
        if cfg.response_schema is not None:
            raise _api_error(400)
        return R()
    monkeypatch.setattr(llm, "_call", call)
    monkeypatch.setattr(llm, "_NO_JSON_MODE", set())
    assert llm._sdk_generate("some-model", "p", llm.ClusterNames, None) == {"clusters": []}
    assert calls[0] is not None and calls[1] is None and not llm.json_mode_supported("some-model")


def test_name_clusters_batches_of_15_and_retries_missing(live, monkeypatch):
    sizes = []

    def fake(prompt, schema, **kw):
        chunk = kw["payload"]
        sizes.append(len(chunk))
        keep = chunk if len(chunk) < 15 else chunk[1:]  # first batch "forgets" one cluster
        return {"clusters": [{"cluster_id": p["cluster_id"], "name": "n", "description": "d", "action": "a"}
                             for p in keep]}
    monkeypatch.setattr(llm, "generate_json", fake)
    out = llm.name_clusters([{"cluster_id": f"C{i}"} for i in range(20)], dataset="t")
    assert sizes == [15, 1, 5] and set(out) == {f"C{i}" for i in range(20)}
