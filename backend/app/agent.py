"""Gemini function-calling agent loop (SPEC §6.3). Yields SSE events (§6.4):
tool_start {tool,args} · tool_result {tool,summary,charts} · text_delta {text} · done · error {message}."""
import json
import logging
from collections.abc import Iterator

from . import llm, tools
from .schemas import SSEEvent

log = logging.getLogger("needmap.agent")

MAX_STEPS = 4          # tool-calling rounds per user turn
HISTORY = 10           # last N chat messages sent to the model
SUMMARY_CHARS = 6000   # ≈1.5k tokens fed back per tool result

SYSTEM = """You are a marketing analyst for Pakistani fashion (lawn suit) brands — Sapphire, Khaadi, Gul Ahmed — \
helping a marketer understand what their Instagram audience wants from comment clusters.
Rules:
- Never invent or compute numbers. Call a tool for ANY number, share, count or example, and only quote numbers \
that appear in tool results.
- Cite clusters exactly as the tools give them, e.g. [C3] or [C3.1].
- Reply in at most 4 sentences, then up to 3 bullet-point actions (from the clusters' `action` fields).
- Reply in the user's language: English, or Roman Urdu if the user writes Roman Urdu.
- If the ask is ambiguous, use defaults (all brands, K-Means) and say so in one short line.
- The charts appear on the canvas next to the chat; refer to them instead of listing every number.
- If the dataset is synthetic (is_synthetic true), you may mention it once briefly."""


def _ev(event: str, **data) -> SSEEvent:
    return SSEEvent(event=event, data=data)


def to_contents(messages: list[dict]) -> list:
    """[{role: user|assistant, content: str}] → SDK contents (last HISTORY messages, starting with a user turn)."""
    msgs = [m for m in messages if str(m.get("content", "")).strip()][-HISTORY:]
    while msgs and msgs[0].get("role") != "user":
        msgs = msgs[1:]
    return [llm.user_content(m["content"]) if m["role"] == "user" else llm.model_content(m["content"])
            for m in msgs]


def compact(summary: dict) -> dict:
    """Tool summary for the model, capped at SUMMARY_CHARS of JSON (lists trimmed from the end)."""
    s = json.loads(json.dumps(summary, ensure_ascii=False))
    while len(json.dumps(s, ensure_ascii=False)) > SUMMARY_CHARS:
        lists = [(k, v) for k, v in s.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            return {"truncated": json.dumps(s, ensure_ascii=False)[:SUMMARY_CHARS]}
        k, v = max(lists, key=lambda kv: len(json.dumps(kv[1], ensure_ascii=False)))
        s[k] = v[: max(1, len(v) * 2 // 3)]
        s["truncated"] = True
    return s


def run_agent(messages: list[dict]) -> Iterator[SSEEvent]:
    try:
        contents = to_contents(messages)
        if not contents:
            yield _ev("error", message="empty message")
            return
        decls = tools.declarations()
        for step in range(MAX_STEPS + 1):
            r = llm.chat(contents, decls if step < MAX_STEPS else [], SYSTEM)
            if not r["function_calls"]:
                yield _ev("text_delta", text=r["text"] or "I couldn't produce an answer — please rephrase.")
                break
            contents.append(r["content"] or llm.calls_content(r["function_calls"]))
            responses = []
            for fc in r["function_calls"]:
                name, args = fc["name"], fc["args"]
                yield _ev("tool_start", tool=name, args=args)
                try:
                    res = tools.call_tool(name, args)
                    summary, charts = res.summary, [c.model_dump() for c in res.charts]
                except (tools.ToolError, KeyError) as exc:
                    msg = f"unknown tool {name}" if isinstance(exc, KeyError) else str(exc)
                    summary, charts = {"error": msg}, []
                yield _ev("tool_result", tool=name, summary=summary, charts=charts)
                responses.append({"id": fc.get("id"), "name": name, "response": compact(summary)})
            contents.append(llm.responses_content(responses))
        yield _ev("done")
    except Exception as exc:  # quota, network, missing artifacts → one error event for the UI
        quota = isinstance(exc, llm.DailyQuotaExceeded) or getattr(exc, "code", None) == 429
        if quota:
            log.warning("Gemini quota exceeded: %s", str(exc)[:200])
        else:
            log.exception("agent failed")
        yield _ev("error", message=("Gemini quota exceeded — try again later." if quota else
                                    f"{type(exc).__name__}: {str(exc)[:300]}"))
