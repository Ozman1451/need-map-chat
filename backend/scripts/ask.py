"""Run the chat agent once from the terminal and print a short event summary.

    python backend/scripts/ask.py "What does my audience want on Khaadi posts?" [--dataset synthetic]
MOCK_LLM=1 runs the offline mock agent.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import run_agent  # noqa: E402
from app.store import store  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("question")
    p.add_argument("--dataset", default=None)
    a = p.parse_args()
    store.load(a.dataset)
    t0, failed = time.time(), False
    for ev in run_agent([{"role": "user", "content": a.question}]):
        dt, d = f"{time.time() - t0:5.1f}s", ev.data
        if ev.event == "tool_start":
            print(f"{dt} tool_start   {d['tool']} {json.dumps(d['args'], ensure_ascii=False)}")
        elif ev.event == "tool_result":
            s = d["summary"]
            keys = ", ".join(k for k in s if k != "dataset")
            print(f"{dt} tool_result  {d['tool']} charts={[c['type'] for c in d['charts']]} summary keys: {keys}")
            if "error" in s:
                print(f"{'':7}error: {s['error']}")
        elif ev.event == "text_delta":
            print(f"{dt} text_delta\n" + "\n".join("        " + ln for ln in d["text"].splitlines()))
        else:
            failed |= ev.event == "error"
            print(f"{dt} {ev.event} {d.get('message', '')}".rstrip())
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
