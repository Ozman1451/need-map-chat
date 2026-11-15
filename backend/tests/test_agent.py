import json

from fastapi.testclient import TestClient

from app import agent, llm
from app.main import app


def events(messages):
    return [(e.event, e.data) for e in agent.run_agent(messages)]


def test_mock_agent_emits_events_in_order(loaded_store):
    ev = events([{"role": "user", "content": "What does my audience want on Khaadi posts?"}])
    assert [e for e, _ in ev] == ["tool_start", "tool_result", "text_delta", "done"]
    assert ev[0][1] == {"tool": "get_need_clusters", "args": {"brand": "Khaadi"}}
    assert ev[1][1]["tool"] == "get_need_clusters" and ev[1][1]["summary"]["filters"] == {"brand": "Khaadi"}
    assert [c["type"] for c in ev[1][1]["charts"]] == ["scatter_embed", "cluster_list"]
    assert "[C" in ev[2][1]["text"]


def test_agent_multi_step_and_tool_errors(loaded_store, monkeypatch):
    """Scripted model: bad call → error fed back; then a good call; then text. History is trimmed."""
    seen = []
    script = [[{"id": "a", "name": "drill_down_cluster", "args": {"cluster_id": "C999"}}],
              [{"id": "b", "name": "compare_algorithms", "args": {}}], []]

    def fake_chat(contents, tools, system):
        seen.append(contents[:])
        calls = script[len(seen) - 1]
        return {"text": "" if calls else "Done [C1].", "function_calls": calls,
                "content": llm.calls_content(calls) if calls else None}
    monkeypatch.setattr(llm, "chat", fake_chat)
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(13)]
    ev = events(msgs)
    assert [e for e, _ in ev] == ["tool_start", "tool_result", "tool_start", "tool_result", "text_delta", "done"]
    assert "error" in ev[1][1]["summary"] and ev[1][1]["charts"] == []
    assert ev[3][1]["charts"]
    assert len(seen[0]) <= agent.HISTORY and seen[0][0].role == "user"
    fr = seen[1][-1].parts[0].function_response
    assert fr.name == "drill_down_cluster" and fr.id == "a" and "error" in fr.response


def test_agent_step_cap(loaded_store, monkeypatch):
    calls = []

    def always_call(contents, tools, system):
        calls.append(bool(tools))
        if not tools:
            return {"text": "final", "function_calls": [], "content": None}
        c = [{"id": None, "name": "get_overview", "args": {}}]
        return {"text": "", "function_calls": c, "content": llm.calls_content(c)}
    monkeypatch.setattr(llm, "chat", always_call)
    ev = events([{"role": "user", "content": "loop"}])
    assert sum(e == "tool_start" for e, _ in ev) == agent.MAX_STEPS and ev[-2] == ("text_delta", {"text": "final"})
    assert calls == [True] * agent.MAX_STEPS + [False]


def test_agent_error_event(loaded_store, monkeypatch):
    def boom(*a):
        raise llm.DailyQuotaExceeded("429 PerDay")
    monkeypatch.setattr(llm, "chat", boom)
    ev = events([{"role": "user", "content": "hi"}])
    assert ev == [("error", {"message": "Gemini quota exceeded — try again later."})]


def test_compact_caps_summary():
    s = agent.compact({"rows": [{"t": "x" * 200}] * 100, "n": 1})
    assert len(json.dumps(s)) <= agent.SUMMARY_CHARS and s["truncated"] and s["n"] == 1


def test_sse_endpoint(loaded_store):
    r = TestClient(app).post("/api/chat", json={"messages": [{"role": "user", "content": "Show me the weird comments"}]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    blocks = [b for b in r.text.split("\n\n") if b.strip()]
    names = [b.split("\n")[0].removeprefix("event: ") for b in blocks]
    assert names == ["tool_start", "tool_result", "text_delta", "done"]
    data = json.loads(blocks[1].split("\n")[1].removeprefix("data: "))
    assert data["tool"] == "get_unusual_comments" and data["charts"]
