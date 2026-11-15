"""Sole Gemini gateway (google-genai SDK).

Every call: model name from env, sha1 disk cache under data/cache/<dataset>/<kind>/,
tenacity backoff on 429/5xx. MOCK_LLM=1 → deterministic offline fakes (no cache, no network).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from .config import settings

log = logging.getLogger("needmap.llm")

NEEDS = [
    "price_inquiry", "discount_request", "delivery_time", "availability_city", "size_fit",
    "fabric_quality", "compliment", "order_complaint", "inbox_request", "purchase_intent",
]
TAG_BATCH = 50
EMBED_BATCH = 100
CITIES = ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan",
          "Peshawar", "Quetta", "Sialkot", "Hyderabad", "Gujranwala", "Dubai", "UK"]


# ---------------------------------------------------------------- plumbing
def is_mock() -> bool:
    return os.environ.get("MOCK_LLM", "").lower() in ("1", "true", "yes") or settings.mock_llm


def model_name(kind: Literal["chat", "batch", "embed"]) -> str:
    name = getattr(settings, f"gemini_{kind}_model")
    if not name:
        raise RuntimeError(f"GEMINI_{kind.upper()}_MODEL is not set (env or .env)")
    return name


_client_obj = None
_client_lock = threading.Lock()


def _client():
    global _client_obj
    with _client_lock:  # one shared client; a GC'd duplicate would close its httpx client mid-request
        if _client_obj is None:
            from google import genai
            _client_obj = genai.Client(api_key=settings.gemini_api_key or None)
    return _client_obj


def cache_key(model: str, prompt: str, payload: Any) -> str:
    blob = model + "\n" + prompt + "\n" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _cache_path(dataset: str, kind: str, key: str, ext: str = "json") -> Path:
    return settings.cache_dir / dataset / kind / f"{key}.{ext}"


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    os.replace(tmp, path)


def _cached_json(dataset: str, kind: str, model: str, prompt: str, payload: Any, fn) -> Any:
    path = _cache_path(dataset, kind, cache_key(model, prompt, payload))
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    out = fn()
    _atomic_write(path, lambda p: p.write_text(json.dumps(out, ensure_ascii=False), "utf-8"))
    return out


def _retryable(exc: BaseException) -> bool:
    from google.genai import errors
    return isinstance(exc, errors.APIError) and (exc.code == 429 or (exc.code or 0) >= 500)


def _warn_retry(state) -> None:
    exc = state.outcome.exception()
    log.warning("Gemini %s (attempt %d) — backing off %.0fs", getattr(exc, "code", type(exc).__name__),
                state.attempt_number, state.next_action.sleep if state.next_action else 0)


_retry = retry(retry=retry_if_exception(_retryable), wait=wait_exponential_jitter(initial=10, max=90),
               stop=stop_after_attempt(5), before_sleep=_warn_retry, reraise=True)


class RateGate:
    """Per-model client-side limiter: ≤rpm requests per sliding 60 s window, one request in flight.
    Only real network calls pass through it (cache hits return before reaching the SDK)."""

    def __init__(self, rpm: int, clock=time.monotonic, sleep=time.sleep):
        self.rpm, self.clock, self.sleep = max(1, rpm), clock, sleep
        self.sent: deque[float] = deque()
        self.lock = threading.Lock()

    @contextmanager
    def slot(self):
        with self.lock:  # held for the whole request → concurrency 1
            while True:
                now = self.clock()
                while self.sent and now - self.sent[0] >= 60:
                    self.sent.popleft()
                if len(self.sent) < self.rpm:
                    break
                wait = 60 - (now - self.sent[0]) + 0.05
                log.info("rate limit %d/min reached — waiting %.1fs", self.rpm, wait)
                self.sleep(wait)
            self.sent.append(self.clock())
            yield


_gates: dict[str, RateGate] = {}
_gates_lock = threading.Lock()


def gate(model: str) -> RateGate:
    with _gates_lock:
        if model not in _gates:
            _gates[model] = RateGate(settings.gemini_rpm)
        return _gates[model]


def _sdk_generate(model: str, prompt: str, schema: type[BaseModel], temperature: float | None) -> dict:
    from google.genai import types
    cfg = types.GenerateContentConfig(response_mime_type="application/json",
                                      response_schema=schema, temperature=temperature)
    with gate(model).slot():
        resp = _client().models.generate_content(model=model, contents=prompt, config=cfg)
    parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text)
    return parsed.model_dump()


def _sdk_embed(model: str, texts: list[str], task_type: str, dim: int) -> list[list[float]]:
    from google.genai import types
    cfg = types.EmbedContentConfig(task_type=task_type, output_dimensionality=dim)
    with gate(model).slot():
        resp = _client().models.embed_content(model=model, contents=texts, config=cfg)
    return [e.values for e in resp.embeddings]


_generate_raw = _retry(lambda *a: _sdk_generate(*a))
_embed_raw = _retry(lambda *a: _sdk_embed(*a))


def generate_json(prompt: str, schema: type[BaseModel], *, dataset: str, kind: str = "gen",
                  payload: Any = None, model: str | None = None, temperature: float | None = None) -> dict:
    """Cached structured-output call. `payload` is the input part of the cache key."""
    model = model or model_name("batch")
    key_input = {"payload": payload, "schema": schema.__name__, "temperature": temperature}
    return _cached_json(dataset, kind, model, prompt, key_input,
                        lambda: _generate_raw(model, prompt, schema, temperature))


# ---------------------------------------------------------------- synthetic comments
NEED_DESC = {
    "price_inquiry": "asking the price of the suit/article",
    "discount_request": "asking for a discount, sale, promo code, or when the sale starts",
    "delivery_time": "asking how long delivery takes or whether it arrives before Eid/an event",
    "availability_city": "asking if it's available in a specific city/outlet, online, or abroad",
    "size_fit": "asking about sizes, stitched vs unstitched, fit, length, or size chart",
    "fabric_quality": "asking about or judging the fabric, print quality, colour fastness, transparency",
    "compliment": "praising the design, colours, model, or brand",
    "order_complaint": "complaining about a late, wrong, damaged, or missing order or bad service",
    "inbox_request": "asking the brand to DM/inbox them or saying they sent a DM with no reply",
    "purchase_intent": "saying they want to buy / order this / tagging a friend to buy together",
    "off_topic": ("off-topic or odd: spam promoting other pages, follow-for-follow, crypto/earning "
                  "schemes, questions about unrelated products (phones, shoes, recipes), comments in "
                  "other languages (Arabic, Turkish, Spanish, Hindi), random jokes, gibberish"),
}


class GenComment(BaseModel):
    post_id: str
    text: str


class GenComments(BaseModel):
    comments: list[GenComment]


COMMENT_PROMPT = """You write realistic Instagram comments left by Pakistani customers (mostly women) \
on posts by Pakistani lawn/clothing brands.

Hidden need of EVERY comment in this batch: {need} — {desc}.
Express it the way a real customer would; never name the need itself. Each comment's MAIN point must be this need \
(a brief side remark is fine, but don't let another topic dominate).

Write exactly the number of comments requested for each post (total {total}).
Style rules:
- Length: about half the comments are very short (1–6 words, e.g. "price?", "inbox plz", "kab aye ga 😩"); the rest 7–25 words. Casual, mostly lowercase, typos and SMS spellings (plz, pls, kitnay ka, availble, sooo, kb, msg), emojis in some comments but not all, occasionally an @mention of a friend handle.
- Languages, as exact counts for this batch: {lang_counts}. "Urdu script" means proper Urdu (Perso-Arabic) letters only; "code-mixed" means Roman Urdu and English mixed in one sentence; "English" means plain (Pakistani-style) English.
- Vary phrasing a lot: no two comments alike, don't start many with the same word, almost no hashtags.
- Mention Pakistani cities when natural (Lahore, Karachi, Islamabad, Pindi, Faisalabad, Multan, Peshawar, Quetta, \
Sialkot, Hyderabad; sometimes Dubai or UK for overseas).
- Fit the post's brand, campaign and product but don't repeat the caption.

Posts (post_id | brand | campaign | content type | caption → number of comments):
{posts}

Return JSON {{"comments": [{{"post_id": "...", "text": "..."}}]}}."""


def generate_comments(need: str, slots: list[dict], *, dataset: str) -> list[dict]:
    """slots: [{post_id, brand, campaign, content_type, caption, count}] → [{post_id, text}]."""
    if is_mock():
        return _mock_comments(need, slots)
    lines = "\n".join(f"- {s['post_id']} | {s['brand']} | {s['campaign']} | {s['content_type']} | "
                      f"\"{s['caption']}\" → {s['count']}" for s in slots)
    total = sum(s["count"] for s in slots)
    prompt = COMMENT_PROMPT.format(need=need, desc=NEED_DESC[need], total=total, posts=lines,
                                   lang_counts=_lang_counts(total))
    out = generate_json(prompt, GenComments, dataset=dataset, kind="seed", payload=slots, temperature=1.0)
    return out["comments"]


LANG_MIX = [("Roman Urdu", 0.45), ("English", 0.25), ("Urdu script", 0.15), ("code-mixed", 0.15)]


def _lang_counts(total: int) -> str:
    counts = [int(total * f) for _, f in LANG_MIX]
    counts[0] += total - sum(counts)
    return ", ".join(f"{lang} {n}" for (lang, _), n in zip(LANG_MIX, counts) if n)


_MOCK_BANK = {
    "price_inquiry": ["price plz {e}", "kitnay ka hai ye?", "price?", "is suit ki qeemat kya hai", "price please"],
    "discount_request": ["sale kb lagegi?", "any discount code? {e}", "koi discount hai?", "sale kab aye gi"],
    "delivery_time": ["delivery kitne din me hogi {c}?", "will it reach {c} before eid?", "delivery time?"],
    "availability_city": ["{c} outlet me available hai?", "available in {c}?", "{c} mein milay ga?"],
    "size_fit": ["size chart plz", "stitched available hai?", "medium size hai?", "length kitni hai"],
    "fabric_quality": ["fabric kaisa hai?", "lawn transparent to nahi?", "colour fast hai?", "quality ghatiya hai"],
    "compliment": ["beautiful {e}", "so pretty 😍", "zabardast design", "love this ❤️", "bohat khoobsurat"],
    "order_complaint": ["order abhi tak nahi mila {e}", "worst service, wrong size bheja", "2 hafte ho gaye order nahi aya"],
    "inbox_request": ["inbox plz", "check DM", "inbox kar dein", "msg kiya reply nahi aya"],
    "purchase_intent": ["mujhe ye chahiye {e}", "want to order this", "ye lena hai @sana", "order karna hai"],
    "off_topic": ["follow for follow 🔥", "earn 5000 daily dm me", "iphone kitnay ka hai?", "hola amigos", "check my page"],
}


def _mock_comments(need: str, slots: list[dict]) -> list[dict]:
    rng = random.Random(cache_key("mock", need, slots))
    out = []
    for s in slots:
        for _ in range(s["count"]):
            t = rng.choice(_MOCK_BANK[need]).format(c=rng.choice(CITIES), e=rng.choice(["😍", "🙏", "❤️", "!!", ""]))
            out.append({"post_id": s["post_id"], "text": f"{t} {rng.randint(1, 999)}" if rng.random() < .5 else t})
    return out


# ---------------------------------------------------------------- tagging (pipeline step 2)
class CommentTag(BaseModel):
    comment_id: str
    sentiment: Literal["pos", "neu", "neg"]
    purchase_intent: Literal["none", "possible", "strong"]
    language_type: Literal["English", "Roman Urdu", "Urdu", "Mixed"]
    city: Optional[str] = None
    gloss: str = Field(description="≤15-word English paraphrase of the commenter's intent")


class CommentTags(BaseModel):
    tags: list[CommentTag]


TAG_PROMPT = """You tag Instagram comments on Pakistani clothing-brand posts. For EACH comment return:
- sentiment: pos | neu | neg
- purchase_intent: none | possible (asks price/size/availability) | strong (wants to order/buy)
- language_type: English | Roman Urdu | Urdu (Urdu script) | Mixed (code-mixed)
- city: Pakistani or foreign city mentioned, else null
- gloss: ≤15-word plain English paraphrase of what the commenter wants or says
Return one tag per comment, same comment_id, JSON {"tags": [...]}.

Comments (JSON):
"""


def tag_batch(comments: list[dict], *, dataset: str) -> list[dict]:
    """comments: [{comment_id, text}] → comment_tags rows, same order. 50 comments per call."""
    out: list[dict] = []
    for i in range(0, len(comments), TAG_BATCH):
        chunk = [{"comment_id": c["comment_id"], "text": c["text"]} for c in comments[i:i + TAG_BATCH]]
        out.extend(_mock_tags(chunk) if is_mock() else _tag_chunk(chunk, dataset))
    return out


def _tag_chunk(chunk: list[dict], dataset: str) -> list[dict]:
    prompt = TAG_PROMPT + json.dumps(chunk, ensure_ascii=False)
    got = {t["comment_id"]: t for t in
           generate_json(prompt, CommentTags, dataset=dataset, kind="tag", payload=chunk)["tags"]}
    missing = [c for c in chunk if c["comment_id"] not in got]
    if missing and len(missing) < len(chunk):
        got.update({t["comment_id"]: t for t in _tag_chunk(missing, dataset)})
    elif missing:
        raise RuntimeError(f"tagging returned no tags for {len(missing)} comments")
    return [got[c["comment_id"]] for c in chunk]


_URDU = re.compile(r"[؀-ۿ]")
_ROMAN = {"hai", "kya", "ka", "ki", "ke", "kar", "dein", "nahi", "mein", "me", "hain", "bhi", "ye", "kab",
          "kb", "kitnay", "kitne", "mujhe", "lena", "chahiye", "abhi", "tak", "bohat", "kaisa", "milay"}
_ENGLISH = {"the", "is", "this", "please", "plz", "price", "available", "in", "want", "love", "so",
            "will", "it", "delivery", "size", "order", "beautiful", "any", "check"}


def _mock_tags(chunk: list[dict]) -> list[dict]:
    rows = []
    for c in chunk:
        t = c["text"].lower()
        words = set(re.findall(r"[a-z]+", t))
        if _URDU.search(t):
            lang = "Urdu"
        else:
            r, e = len(words & _ROMAN), len(words & _ENGLISH)
            lang = "Mixed" if r and e else "Roman Urdu" if r else "English"
        neg = any(w in t for w in ("worst", "nahi mila", "ghatiya", "wrong", "late", "nahi aya"))
        pos = any(w in t for w in ("love", "beautiful", "pretty", "zabardast", "khoobsurat", "😍", "❤"))
        strong = any(w in t for w in ("order", "chahiye", "lena", "want"))
        possible = any(w in t for w in ("price", "size", "available", "kitnay", "delivery", "discount"))
        city = next((x for x in CITIES if x.lower() in t), None)
        rows.append({"comment_id": c["comment_id"], "sentiment": "neg" if neg else "pos" if pos else "neu",
                     "purchase_intent": "strong" if strong else "possible" if possible else "none",
                     "language_type": lang, "city": city, "gloss": " ".join(c["text"].split()[:15])})
    return rows


# ---------------------------------------------------------------- embeddings (pipeline step 3)
def embed(texts: list[str], *, dataset: str, task_type: str = "CLUSTERING", dim: int = 768) -> np.ndarray:
    """→ float32 array (len(texts), dim), L2-normalised. Cached per chunk of 100 as .npy."""
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)
    if is_mock():
        vecs = np.stack([np.random.default_rng(int(hashlib.sha1(t.encode()).hexdigest()[:15], 16))
                         .standard_normal(dim) for t in texts])
    else:
        model = model_name("embed")
        parts = []
        for i in range(0, len(texts), EMBED_BATCH):
            chunk = texts[i:i + EMBED_BATCH]
            path = _cache_path(dataset, "embed", cache_key(model, task_type, {"texts": chunk, "dim": dim}), "npy")
            if path.exists():
                parts.append(np.load(path))
                continue
            arr = np.asarray(_embed_raw(model, chunk, task_type, dim), dtype=np.float32)
            _atomic_write(path, lambda p: np.save(open(p, "wb"), arr))
            parts.append(arr)
        vecs = np.concatenate(parts)
    vecs = vecs.astype(np.float32)
    return vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)


# ---------------------------------------------------------------- cluster naming (pipeline step 5)
class ClusterName(BaseModel):
    name: str = Field(description="≤4 words")
    description: str = Field(description="one sentence")
    action: str = Field(description="one imperative sentence for the marketing team")


NAME_PROMPT = """You name one cluster of Instagram comments on Pakistani lawn/clothing-brand posts for a marketer.
Use only the facts given (top terms, example comments, stats); do not invent numbers.
Return JSON {"name": "≤4 words", "description": "one sentence", "action": "one imperative sentence"}.

Cluster data (JSON):
"""


def name_cluster(payload: dict, *, dataset: str) -> dict:
    if is_mock():
        terms = [str(t) for t in payload.get("top_terms", [])][:3] or ["misc"]
        return {"name": " ".join(terms).title()[:40], "description": f"Comments about {', '.join(terms)}.",
                "action": f"Address {terms[0]} questions in captions and replies."}
    prompt = NAME_PROMPT + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return generate_json(prompt, ClusterName, dataset=dataset, kind="name", payload=payload, temperature=0.2)


# ---------------------------------------------------------------- live chat (agent, Phase 3)
def chat(contents: list, tools: list[dict], system: str) -> dict:
    """One function-calling turn. tools: FunctionDeclaration dicts (name, description, parameters).
    → {"text": str, "function_calls": [{"name", "args"}], "content": model Content (for history)}."""
    if is_mock():
        return _mock_chat(contents, tools)
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**t) for t in tools])] if tools else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    model = model_name("chat")

    def call():
        with gate(model).slot():
            return _client().models.generate_content(model=model, contents=contents, config=cfg)
    resp = _retry(call)()
    calls = [{"name": fc.name, "args": dict(fc.args or {})} for fc in (resp.function_calls or [])]
    content = resp.candidates[0].content if resp.candidates else None
    return {"text": "" if calls else (resp.text or ""), "function_calls": calls, "content": content}


def _mock_chat(contents: list, tools: list[dict]) -> dict:
    last = contents[-1] if contents else None
    role = last.get("role") if isinstance(last, dict) else getattr(last, "role", None)
    if role == "user" and tools:  # first step: call the first tool; after a tool reply: answer
        return {"text": "", "function_calls": [{"name": tools[0]["name"], "args": {}}], "content": None}
    return {"text": "Mock reply: here is what the tool found.", "function_calls": [], "content": None}
