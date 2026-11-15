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


class DailyQuotaExceeded(RuntimeError):
    """A 429 naming a per-day quota: retrying today is pointless."""


def is_daily_quota(exc: BaseException) -> bool:
    return getattr(exc, "code", None) == 429 and "PerDay" in str(exc)


def _retryable(exc: BaseException) -> bool:
    from google.genai import errors
    if is_daily_quota(exc):
        return False
    return isinstance(exc, errors.APIError) and (exc.code == 429 or (exc.code or 0) >= 500)


def _warn_retry(state) -> None:
    exc = state.outcome.exception()
    log.warning("Gemini %s (attempt %d) — backing off %.0fs: %s", getattr(exc, "code", type(exc).__name__),
                state.attempt_number, state.next_action.sleep if state.next_action else 0,
                " ".join(str(getattr(exc, "message", exc)).split())[:300])


_retry = retry(retry=retry_if_exception(_retryable), wait=wait_exponential_jitter(initial=10, max=90),
               stop=stop_after_attempt(5), before_sleep=_warn_retry, reraise=True)


class RateGate:
    """Per-model client-side limiter over a sliding 60 s window: ≤rpm request units and (optionally)
    ≤tpm estimated input tokens, one request in flight. A batch embed costs one unit per text (that is
    how the free tier counts it). Only real network calls pass through (cache hits return earlier)."""

    def __init__(self, rpm: int, tpm: int | None = None, clock=time.monotonic, sleep=time.sleep):
        self.rpm, self.tpm, self.clock, self.sleep = max(1, rpm), tpm, clock, sleep
        self.sent: deque[tuple[float, int, int]] = deque()
        self.lock = threading.Lock()

    def _fits(self, units: int, tokens: int) -> bool:
        if not self.sent:
            return True
        if sum(u for _, u, _ in self.sent) + units > self.rpm:
            return False
        return self.tpm is None or sum(t for _, _, t in self.sent) + tokens <= self.tpm

    @contextmanager
    def slot(self, tokens: int = 0, units: int = 1):
        with self.lock:  # held for the whole request → concurrency 1
            while True:
                now = self.clock()
                while self.sent and now - self.sent[0][0] >= 60:
                    self.sent.popleft()
                if self._fits(units, tokens):
                    break
                wait = 60 - (now - self.sent[0][0]) + 0.05
                log.info("rate limit (%d req, %d tok)/min reached — waiting %.1fs",
                         self.rpm, self.tpm or 0, wait)
                self.sleep(wait)
            self.sent.append((self.clock(), units, tokens))
            yield


_gates: dict[str, RateGate] = {}
_gates_lock = threading.Lock()


def gate(model: str) -> RateGate:
    with _gates_lock:
        if model not in _gates:
            embed = model == settings.gemini_embed_model
            _gates[model] = (RateGate(settings.gemini_embed_rpm, settings.gemini_embed_tpm) if embed
                             else RateGate(settings.gemini_rpm))
        return _gates[model]


def estimate_tokens(texts: list[str]) -> int:
    """Conservative input-token estimate (no API call): ~3 UTF-8 bytes/token, +2 per text."""
    return sum(len(t.encode("utf-8")) // 3 + 2 for t in texts)


_NO_JSON_MODE: set[str] = set()  # models that rejected response_schema (400) during this run


def json_mode_supported(model: str) -> bool:
    """Gemma on the Gemini API documents no JSON mode / response_schema → prompt for JSON instead."""
    return not model.startswith("gemma") and model not in _NO_JSON_MODE


def parse_json(text: str, schema: type[BaseModel]) -> dict:
    """Lenient parse of a model's JSON reply (code fences, leading prose, bare list for a
    one-field object schema) → validated dict. Raises ValueError / ValidationError."""
    t = re.sub(r"^\s*```(?:json)?|```\s*$", "", text or "").strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in model reply")
    obj, _ = json.JSONDecoder().raw_decode(t[min(starts):])
    fields = list(schema.model_fields)
    if isinstance(obj, list) and len(fields) == 1:
        obj = {fields[0]: obj}
    return schema.model_validate(obj).model_dump()


def _call(model: str, prompt: str, cfg):
    with gate(model).slot():
        return _client().models.generate_content(model=model, contents=prompt, config=cfg)


def _sdk_generate(model: str, prompt: str, schema: type[BaseModel], temperature: float | None) -> dict:
    from google.genai import errors, types
    if json_mode_supported(model):
        cfg = types.GenerateContentConfig(response_mime_type="application/json",
                                          response_schema=schema, temperature=temperature)
        try:
            resp = _call(model, prompt, cfg)
            parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text)
            return parsed.model_dump()
        except errors.ClientError as exc:
            if exc.code != 400:
                raise
            log.warning("%s rejected structured output (400) — falling back to JSON-in-prompt", model)
            _NO_JSON_MODE.add(model)
    return _prompt_json(model, prompt, schema, temperature)


def _prompt_json(model: str, prompt: str, schema: type[BaseModel], temperature: float | None) -> dict:
    """No JSON mode: ask for JSON in the prompt, validate with pydantic, retry once on invalid JSON."""
    from google.genai import types
    full = (prompt + "\n\nReply with ONLY valid JSON (no prose, no code fences) matching this JSON Schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False))
    cfg = types.GenerateContentConfig(temperature=temperature)
    for attempt in (1, 2):
        text = _call(model, full, cfg).text
        try:
            return parse_json(text, schema)
        except ValueError as exc:  # pydantic ValidationError is a ValueError
            if attempt == 2:
                raise RuntimeError(f"{model} returned invalid JSON twice: {str(exc)[:200]}") from exc
            log.warning("%s returned invalid JSON — retrying once", model)


def _sdk_embed(model: str, texts: list[str], task_type: str, dim: int) -> list[list[float]]:
    from google.genai import types
    cfg = types.EmbedContentConfig(task_type=task_type, output_dimensionality=dim)
    with gate(model).slot(estimate_tokens(texts), units=len(texts)):
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
def mock_vectors(texts: list[str], dim: int) -> np.ndarray:
    """Deterministic hash-seeded random vectors (MOCK_LLM, both embedding backends)."""
    return np.stack([np.random.default_rng(int(hashlib.sha1(t.encode()).hexdigest()[:15], 16))
                     .standard_normal(dim) for t in texts]).astype(np.float32)


def embed(texts: list[str], *, dataset: str, task_type: str = "CLUSTERING", dim: int = 768) -> np.ndarray:
    """→ float32 array (len(texts), dim), L2-normalised. Cached per chunk of 100 as .npy."""
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)
    if is_mock():
        vecs = mock_vectors(texts, dim)
    else:
        model = model_name("embed")
        parts = []
        for i in range(0, len(texts), EMBED_BATCH):
            chunk = texts[i:i + EMBED_BATCH]
            path = _cache_path(dataset, "embed", cache_key(model, task_type, {"texts": chunk, "dim": dim}), "npy")
            if path.exists():
                parts.append(np.load(path))
                continue
            try:
                arr = np.asarray(_embed_raw(model, chunk, task_type, dim), dtype=np.float32)
            except Exception as exc:
                if is_daily_quota(exc):
                    raise DailyQuotaExceeded(str(exc)[:300]) from exc
                raise
            _atomic_write(path, lambda p: np.save(open(p, "wb"), arr))
            parts.append(arr)
        vecs = np.concatenate(parts)
    vecs = vecs.astype(np.float32)
    return vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)


def embed_pending(texts: list[str], *, dataset: str, task_type: str = "CLUSTERING", dim: int = 768) -> int:
    """How many of `texts` still need a network call (chunks not in the disk cache)."""
    if is_mock():
        return 0
    model = model_name("embed")
    return sum(len(texts[i:i + EMBED_BATCH]) for i in range(0, len(texts), EMBED_BATCH)
               if not _cache_path(dataset, "embed", cache_key(model, task_type, {"texts": texts[i:i + EMBED_BATCH],
                                                                             "dim": dim}), "npy").exists())


# ---------------------------------------------------------------- cluster naming (pipeline step 5)
NAME_BATCH = 15


class NamedCluster(BaseModel):
    cluster_id: str
    name: str = Field(description="≤4 words")
    description: str = Field(description="one sentence")
    action: str = Field(description="one imperative sentence for the marketing team")


class ClusterNames(BaseModel):
    clusters: list[NamedCluster]


NAME_PROMPT = """You name clusters of Instagram comments on Pakistani lawn/clothing-brand posts for a marketer.
For EACH cluster below use only its facts (top terms, example comments, stats); do not invent numbers.
Make names distinct from each other. A cluster with "parent_cluster_name" is a sub-group of that parent: \
name what makes it different from its siblings.
Return one entry per cluster, same cluster_id: \
JSON {"clusters": [{"cluster_id": "...", "name": "≤4 words", "description": "one sentence", \
"action": "one imperative sentence"}]}.

Clusters (JSON):
"""


def name_clusters(payloads: list[dict], *, dataset: str) -> dict[str, dict]:
    """payloads: [{cluster_id, top_terms, examples, stats...}] → {cluster_id: {name, description, action}}.
    Up to NAME_BATCH clusters per Gemini call; cached per batch."""
    out: dict[str, dict] = {}
    for i in range(0, len(payloads), NAME_BATCH):
        out.update(_name_chunk(payloads[i:i + NAME_BATCH], dataset))
    return out


def _name_chunk(chunk: list[dict], dataset: str, retry_missing: bool = True) -> dict[str, dict]:
    if is_mock():
        return {p["cluster_id"]: _mock_name(p) for p in chunk}
    prompt = NAME_PROMPT + json.dumps(chunk, ensure_ascii=False, sort_keys=True)
    res = generate_json(prompt, ClusterNames, dataset=dataset, kind="name", payload=chunk, temperature=0.2)
    want = {p["cluster_id"] for p in chunk}
    got = {c["cluster_id"]: {k: c[k] for k in ("name", "description", "action")}
           for c in res["clusters"] if c["cluster_id"] in want}
    missing = [p for p in chunk if p["cluster_id"] not in got]
    if missing and retry_missing and len(missing) < len(chunk):
        got.update(_name_chunk(missing, dataset, retry_missing=False))
    missing = want - set(got)
    if missing:
        raise RuntimeError(f"naming returned nothing for {sorted(missing)}")
    return got


def _mock_name(p: dict) -> dict:
    terms = [str(t) for t in p.get("top_terms", [])][:3] or ["misc"]
    return {"name": " ".join(terms).title()[:40], "description": f"Comments about {', '.join(terms)}.",
            "action": f"Address {terms[0]} questions in captions and replies."}


# ---------------------------------------------------------------- real posts: campaign / content_type
CAMPAIGNS = ["Eid", "11.11", "12.12", "Summer Lawn", "Winter", "Regular"]
INFER_BATCH = 25


class PostInference(BaseModel):
    post_id: str
    campaign: Literal["Eid", "11.11", "12.12", "Summer Lawn", "Winter", "Regular"]
    content_type: Optional[Literal["Influencer", "Sale Announcement"]] = Field(
        None, description="only if the caption clearly is an influencer/celebrity post or a sale announcement")


class PostInferences(BaseModel):
    posts: list[PostInference]


INFER_PROMPT = """You classify Instagram posts of Pakistani lawn/clothing brands from caption, date and media type.
For EACH post return:
- campaign: Eid (Eid/festive/Chand Raat) | 11.11 | 12.12 | Summer Lawn (summer/spring lawn collection) | \
Winter (winter/khaddar/shawl) | Regular (anything else)
- content_type: "Influencer" if the post features a named influencer/celebrity/ambassador, \
"Sale Announcement" if it announces a sale/discount/flat-% off, otherwise null
Return one entry per post, same post_id, JSON {"posts": [...]}.

Posts (JSON):
"""


def infer_posts(posts: list[dict], *, dataset: str) -> list[dict]:
    """posts: [{post_id, caption, posted_at, media}] → [{post_id, campaign, content_type|None}], same order.
    INFER_BATCH posts per cached call (Gemma falls back to JSON-in-prompt inside generate_json)."""
    out: list[dict] = []
    for i in range(0, len(posts), INFER_BATCH):
        chunk = [{k: str(p.get(k) or "")[:600] for k in ("post_id", "caption", "posted_at", "media")}
                 for p in posts[i:i + INFER_BATCH]]
        out.extend(_mock_infer(chunk) if is_mock() else _infer_chunk(chunk, dataset))
    return out


def _infer_chunk(chunk: list[dict], dataset: str) -> list[dict]:
    prompt = INFER_PROMPT + json.dumps(chunk, ensure_ascii=False)
    res = generate_json(prompt, PostInferences, dataset=dataset, kind="infer", payload=chunk, temperature=0.0)
    got = {r["post_id"]: r for r in res["posts"]}
    missing = [c for c in chunk if c["post_id"] not in got]
    if missing and len(missing) < len(chunk):
        got.update({r["post_id"]: r for r in _infer_chunk(missing, dataset)})
    elif missing:
        raise RuntimeError(f"post inference returned nothing for {len(missing)} posts")
    return [got[c["post_id"]] for c in chunk]


_CAMPAIGN_KW = [("12.12", ("12.12", "12 12")), ("11.11", ("11.11", "11 11")),
                ("Eid", ("eid", "festive", "chand raat")), ("Winter", ("winter", "khaddar", "shawl")),
                ("Summer Lawn", ("summer", "spring", "lawn"))]


def _mock_infer(chunk: list[dict]) -> list[dict]:
    rows = []
    for p in chunk:
        t = p["caption"].lower()
        camp = next((c for c, kws in _CAMPAIGN_KW if any(k in t for k in kws)), "Regular")
        ct = ("Sale Announcement" if any(k in t for k in ("sale", "% off", "discount", "flat"))
              else "Influencer" if any(k in t for k in ("ft.", "featuring", "wearing", "ambassador")) else None)
        rows.append({"post_id": p["post_id"], "campaign": camp, "content_type": ct})
    return rows


# ---------------------------------------------------------------- live chat (agent)
def user_content(text: str):
    from google.genai import types
    return types.Content(role="user", parts=[types.Part(text=text)])


def model_content(text: str):
    from google.genai import types
    return types.Content(role="model", parts=[types.Part(text=text)])


def calls_content(calls: list[dict]):
    """Model turn for function calls when no SDK Content came back (mock)."""
    from google.genai import types
    return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
        id=c.get("id"), name=c["name"], args=c["args"])) for c in calls])


def responses_content(results: list[dict]):
    """results: [{id, name, response: dict}] → one user turn of function responses."""
    from google.genai import types
    return types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=r.get("id"), name=r["name"], response=r["response"])) for r in results])


def chat(contents: list, tools: list[dict], system: str) -> dict:
    """One function-calling turn (automatic function calling off). contents: list of types.Content;
    tools: FunctionDeclaration dicts (name, description, parameters_json_schema).
    → {"text": str, "function_calls": [{"id", "name", "args"}], "content": model Content for history}.
    The returned Content keeps Gemini 3 thought signatures, so it must be appended to history as-is."""
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
    try:
        resp = _retry(call)()
    except Exception as exc:
        if is_daily_quota(exc):
            raise DailyQuotaExceeded(str(exc)[:300]) from exc
        raise
    calls = [{"id": fc.id, "name": fc.name, "args": dict(fc.args or {})} for fc in (resp.function_calls or [])]
    content = resp.candidates[0].content if resp.candidates else None
    text = "".join(p.text for p in (content.parts or []) if p.text and not p.thought) if content else ""
    return {"text": "" if calls else text, "function_calls": calls, "content": content}


_MOCK_ROUTES = [  # (keywords, tool) — first match wins; default get_need_clusters
    (("split", "drill", "sub-need", "further", "break down"), "drill_down_cluster"),
    (("weird", "unusual", "odd", "spam", "outlier", "ajeeb"), "get_unusual_comments"),
    (("vs", "campaign", "change", "differ", "compare brand", "by brand", "content type"), "need_share_by"),
    (("algorithm", "silhouette", "best clustering", "fits best"), "compare_algorithms"),
    (("example", "show me comments", "sample"), "sample_comments"),
    (("overview", "how many", "numbers", "kitne"), "get_overview"),
]


def _mock_chat(contents: list, tools: list[dict]) -> dict:
    """Deterministic offline agent: route the last user text by keyword; after tool replies, answer
    from their summaries (numbers only from the tool output)."""
    last = contents[-1] if contents else None
    parts = getattr(last, "parts", None) or []
    responses = [p.function_response for p in parts if p.function_response]
    if responses or not tools:
        return {"text": _mock_answer(responses), "function_calls": [], "content": None}
    text = " ".join(p.text for p in parts if p.text).lower()
    names = {t["name"] for t in tools}
    name = next((tool for kws, tool in _MOCK_ROUTES if any(k in text for k in kws) and tool in names),
                "get_need_clusters" if "get_need_clusters" in names else tools[0]["name"])
    args: dict = {}
    m = re.search(r"\[?\b([CWGD]\d+(?:\.\d+)?)\b\]?", text.upper())
    if name in ("drill_down_cluster", "sample_comments"):
        args["cluster_id"] = m.group(1) if m else "C1"
    if m and name == "get_need_clusters":
        name, args = "sample_comments", {"cluster_id": m.group(1)}
    for b in ("sapphire", "khaadi", "gul ahmed"):
        if b in text and name in ("get_need_clusters", "get_overview", "get_unusual_comments"):
            args["brand"] = b.title()
    if name == "need_share_by":
        args["group_by"] = "brand" if "brand" in text else "content_type" if "content" in text else "campaign"
    calls = [{"id": "mock-1", "name": name, "args": args}]
    return {"text": "", "function_calls": calls, "content": calls_content(calls)}


def _mock_answer(responses: list) -> str:
    if not responses:
        return "Mock reply: ask me what your audience wants."
    fr = responses[-1]
    s = dict(fr.response or {})
    if "error" in s:
        return f"Mock reply: {fr.name} failed — {s['error']}"
    items = s.get("clusters") or s.get("children") or []
    if items:
        lines = "\n".join(f"- {c['id']} {c['name']} ({c['share']:.0%}): {c.get('action', '')}" for c in items[:3])
        return f"Mock reply: {fr.name} found {len(items)} groups. The biggest is {items[0]['id']}.\n{lines}"
    if "cluster" in s:
        return f"Mock reply: here are example comments from {s['cluster']['id']} {s['cluster']['name']}."
    return f"Mock reply: {fr.name} returned its results — see the canvas."
