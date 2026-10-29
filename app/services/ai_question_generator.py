"""Gemini-backed question generation. Runs on the backend only.

* Calls the REST API with the key in a header (never in URLs, logs, or browser responses).
* Local rate budget + cool-down after quota errors; limited retries; timeouts.
* Output is validated (question_validator) and stored; duplicates are rejected by hash.
* Failures never propagate to users: callers fall back to stored questions.
"""
import json
import logging
import math
import re
import threading
import time
from collections import defaultdict, deque

import requests
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..categories import CATEGORY_GUIDANCE
from ..models import Category, Question
from .question_validator import ValidationError, validate_question

log = logging.getLogger(__name__)
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GenerationError(Exception):
    """Internal error. Message is for logs only, never shown to users."""


class QuotaExceeded(GenerationError):
    pass


class _Budget:
    """Process-local limiter: N calls per minute plus a cool-down after HTTP 429."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = deque()
        self.blocked_until = 0.0

    def acquire(self, per_minute):
        now = time.monotonic()
        with self.lock:
            if now < self.blocked_until:
                raise QuotaExceeded("cooling down after quota error")
            while self.calls and now - self.calls[0] > 60:
                self.calls.popleft()
            if len(self.calls) >= per_minute:
                raise QuotaExceeded("local per-minute budget exhausted")
            self.calls.append(now)

    def block(self, seconds):
        with self.lock:
            self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)


def build_prompt(category_name, language, count, guidance="", avoid=()):
    easy = math.ceil(count * 0.4)
    hard = count // 5
    medium = count - easy - hard
    lang_rule = ("Write every question, option and explanation in Kannada (ಕನ್ನಡ) script. Do NOT write "
                 "English general-knowledge questions." if language == "kn"
                 else "Write in clear English.")
    avoid_txt = ""
    if avoid:
        avoid_txt = "\nDo NOT repeat or paraphrase these existing questions:\n" + "\n".join(f"- {a}" for a in avoid)
    return (
        f"Create {count} multiple-choice quiz questions for the category \"{category_name}\".\n"
        f"{('Category focus: ' + guidance) if guidance else ''}\n{lang_rule}\n"
        f"Difficulty mix: {easy} easy, {medium} medium, {hard} hard.\n"
        "Rules:\n"
        "- Exactly four distinct options; exactly one is correct; the correct letter must vary across questions.\n"
        "- Only well-established facts that will not change. Avoid time-sensitive wording such as "
        "'current', 'latest', 'recent', 'today', 'this year', 'as of'.\n"
        "- No 'all of the above' / 'none of the above'. No trick wording unless the category is about tricks.\n"
        "- The explanation must be complete (1-3 sentences) and justify the correct answer.\n"
        f"{avoid_txt}\n"
        "Return ONLY a JSON array (no markdown, no commentary). Each item must have exactly these keys: "
        "question, option_a, option_b, option_c, option_d, correct_answer (\"A\"|\"B\"|\"C\"|\"D\"), "
        "explanation, difficulty (\"easy\"|\"medium\"|\"hard\")."
    )


def parse_json_array(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise GenerationError("response is not valid JSON")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise GenerationError("response is not valid JSON") from exc
    if isinstance(data, dict):
        data = data.get("questions", [])
    if not isinstance(data, list):
        raise GenerationError("response JSON is not a list")
    return data


class GeminiGenerator:
    def __init__(self, api_key, model, timeout=30, retries=2, max_calls_per_minute=8, http=None):
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.max_calls_per_minute = max_calls_per_minute
        self.http = http or requests
        self.budget = _Budget()

    @classmethod
    def from_config(cls, cfg):
        return cls(cfg.get("GEMINI_API_KEY"), cfg.get("GEMINI_MODEL"), cfg.get("GEMINI_TIMEOUT", 30),
                   cfg.get("GEMINI_RETRIES", 2), cfg.get("GEMINI_MAX_CALLS_PER_MINUTE", 8))

    @property
    def enabled(self):
        return bool(self.api_key)

    def generate(self, category_name, language="en", count=10, guidance="", avoid=()):
        """Return a list of raw question dicts (unvalidated)."""
        if not self.enabled:
            raise GenerationError("GEMINI_API_KEY not configured")
        payload = {
            "contents": [{"parts": [{"text": build_prompt(category_name, language, count, guidance, avoid)}]}],
            "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
        }
        url = ENDPOINT.format(model=self.model)
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        last = None
        for attempt in range(self.retries + 1):
            self.budget.acquire(self.max_calls_per_minute)
            try:
                resp = self.http.post(url, headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                last = GenerationError(f"network error: {type(exc).__name__}")
                time.sleep(min(2 ** attempt, 4))
                continue
            if resp.status_code == 429:
                try:
                    wait = min(int(resp.headers.get("Retry-After", 60)), 300)
                except (TypeError, ValueError):
                    wait = 60
                self.budget.block(wait)
                raise QuotaExceeded("Gemini quota/rate limit (HTTP 429)")
            if resp.status_code >= 500:
                last = GenerationError(f"Gemini server error HTTP {resp.status_code}")
                time.sleep(min(2 ** attempt, 4))
                continue
            if resp.status_code != 200:
                raise GenerationError(f"Gemini request rejected HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                body = resp.json()
                text = "".join(p.get("text", "") for p in body["candidates"][0]["content"]["parts"])
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                last = GenerationError("unexpected response structure")
                continue
            try:
                return parse_json_array(text)
            except GenerationError as exc:
                last = exc
                continue
        raise last or GenerationError("generation failed")


def get_generator():
    gen = current_app.extensions.get("question_generator")
    if gen is None:
        gen = GeminiGenerator.from_config(current_app.config)
        current_app.extensions["question_generator"] = gen
    return gen


def store_questions(session, category, pool, items, source="ai"):
    """Validate and insert raw items. Returns (inserted, rejected)."""
    language = category.language
    hashes_existing = set(session.scalars(select(Question.question_hash).where(Question.pool == pool)))
    inserted = rejected = 0
    for raw in items:
        try:
            data = validate_question(raw, language)
        except ValidationError as exc:
            rejected += 1
            log.info("Rejected question for %s: %s", category.name, exc)
            continue
        if data["question_hash"] in hashes_existing:
            rejected += 1
            continue
        session.add(Question(pool=pool, category_id=category.id, source=source, **data))
        try:
            session.commit()
            hashes_existing.add(data["question_hash"])
            inserted += 1
        except IntegrityError:
            session.rollback()  # duplicate inserted concurrently
            rejected += 1
    return inserted, rejected


_locks = defaultdict(threading.Lock)


def generate_and_store(session, category, pool="category", count=None):
    """Try to add new questions. Never raises; returns the number inserted."""
    gen = get_generator()
    if not gen.enabled:
        return 0
    key = (pool, category.id)
    lock = _locks[key]
    if not lock.acquire(blocking=False):
        return 0  # another request is already generating for this slot
    try:
        count = count or current_app.config.get("GEMINI_BATCH_SIZE", 10)
        recent = session.scalars(select(Question.question_text).where(
            Question.pool == pool, Question.category_id == category.id
        ).order_by(Question.id.desc()).limit(10)).all()
        raw = gen.generate(category.name, category.language, count,
                           CATEGORY_GUIDANCE.get(category.name, ""), recent)
        inserted, rejected = store_questions(session, category, pool, raw)
        log.info("Gemini %s/%s: inserted=%s rejected=%s", pool, category.name, inserted, rejected)
        return inserted
    except QuotaExceeded as exc:
        log.warning("Gemini quota/rate limit for %s: %s", category.name, exc)
    except GenerationError as exc:
        log.error("Gemini generation failed for %s: %s", category.name, exc)
    except Exception:  # noqa: BLE001 - never break gameplay because of AI problems
        log.exception("Unexpected error during question generation for %s", category.name)
        session.rollback()
    finally:
        lock.release()
    return 0
