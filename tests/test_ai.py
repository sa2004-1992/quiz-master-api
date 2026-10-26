import json
import threading

import pytest
import requests
from sqlalchemy import select

from app.models import Category, Question
from app.services.ai_question_generator import (GeminiGenerator, GenerationError, QuotaExceeded,
                                                generate_and_store, parse_json_array)
from app.services.question_validator import ValidationError, question_hash, validate_question
from tests.conftest import add_questions, api, cat_id, make_app, play_through, register, login, start, state


def good(i, correct="B", prefix="Mock"):
    return {"question": f"{prefix} question number {i} about science?", "option_a": f"a{i}", "option_b": f"b{i}",
            "option_c": f"c{i}", "option_d": f"d{i}", "correct_answer": correct,
            "explanation": "A complete explanation of the answer.", "difficulty": "easy"}


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def gemini_body(items):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(items)}]}}]}


class FakeHttp:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def install(app, http, **kw):
    gen = GeminiGenerator("test-key-123", "test-model", timeout=5, retries=kw.pop("retries", 0),
                          max_calls_per_minute=kw.pop("per_minute", 50), http=http)
    app.extensions["question_generator"] = gen
    return gen


def run_generate(app, category="History", pool="category"):
    s = app.extensions["db_sessionmaker"]()
    with app.app_context():
        cat = s.scalars(select(Category).where(Category.name == category)).one()
        n = generate_and_store(s, cat, pool)
    s.close()
    return n


# ---------------------------------------------------------------- validator
def test_validator_accepts_good_and_rejects_bad():
    ok = validate_question(good(1))
    assert ok["correct_answer"] == "B" and len(ok["question_hash"]) == 64
    bad_cases = [
        {**good(1), "correct_answer": "E"}, {**good(1), "correct_answer": ""},
        {**good(1), "option_d": ""}, {**good(1), "option_c": "a1"},  # duplicate options
        {**good(1), "explanation": ""}, {**good(1), "question": ""}, {k: v for k, v in good(1).items() if k != "option_a"},
        {**good(1), "difficulty": "impossible"}, "not a dict", None,
        {**good(1), "question": "What is the current population of India today?"},
    ]
    for case in bad_cases:
        with pytest.raises(ValidationError):
            validate_question(case)


def test_validator_language_rules():
    kn = {**good(1), "question": "ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ ಯಾವುದು?"}
    assert validate_question(kn, "kn")
    with pytest.raises(ValidationError):
        validate_question(good(2), "kn")  # English question in the Kannada category
    with pytest.raises(ValidationError):
        validate_question(kn, "en")


def test_hash_is_stable_across_formatting():
    assert question_hash("What  is  2+2?") == question_hash("what is 2 2")


def test_parse_json_variants():
    assert parse_json_array('```json\n[{"a":1}]\n```') == [{"a": 1}]
    assert parse_json_array('Here you go: [{"a":1}] hope it helps') == [{"a": 1}]
    assert parse_json_array('{"questions":[{"a":1}]}') == [{"a": 1}]
    with pytest.raises(GenerationError):
        parse_json_array("sorry I cannot")


# ---------------------------------------------------------------- generation + storage
def test_generate_and_store_valid_batch_and_duplicates(app):
    http = FakeHttp(FakeResponse(payload=gemini_body([good(i) for i in range(10)])))
    install(app, http)
    assert run_generate(app) == 10
    assert run_generate(app) == 0  # identical batch -> all duplicates rejected by hash
    s = app.extensions["db_sessionmaker"]()
    assert s.query(Question).filter_by(source="ai").count() == 10
    call = http.calls[0]
    assert "test-key-123" not in call["url"] and call["headers"]["x-goog-api-key"] == "test-key-123"
    assert call["timeout"] == 5 and "History" in call["json"]["contents"][0]["parts"][0]["text"]


def test_invalid_items_are_skipped_not_stored(app):
    items = [good(1), {**good(2), "correct_answer": "Z"}, {**good(3), "option_b": ""}, good(1), good(4)]
    install(app, FakeHttp(FakeResponse(payload=gemini_body(items))))
    assert run_generate(app) == 2  # only valid, non-duplicate ones


def test_kannada_prompt_and_validation(app):
    kn_items = [{**good(i), "question": f"ಕನ್ನಡ ಪ್ರಶ್ನೆ ಸಂಖ್ಯೆ {i} ಯಾವುದು?"} for i in range(3)] + [good(9)]
    http = FakeHttp(FakeResponse(payload=gemini_body(kn_items)))
    install(app, http)
    assert run_generate(app, "Kannada") == 3  # the English question is rejected
    assert "Kannada" in http.calls[0]["json"]["contents"][0]["parts"][0]["text"]


def test_malformed_responses_never_raise(app):
    for resp in [FakeResponse(payload={"unexpected": 1}), FakeResponse(payload={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}),
                 FakeResponse(status=500, payload={}), FakeResponse(status=403, payload={"error": "SECRET"}),
                 requests.Timeout("slow")]:
        install(app, FakeHttp(resp), retries=1)
        assert run_generate(app) == 0
    s = app.extensions["db_sessionmaker"]()
    assert s.query(Question).filter_by(source="ai").count() == 0


def test_quota_error_triggers_cooldown(app):
    http = FakeHttp(FakeResponse(status=429, payload={}, headers={"Retry-After": "30"}))
    install(app, http, retries=2)
    assert run_generate(app) == 0
    assert run_generate(app) == 0
    assert len(http.calls) == 1  # second call blocked locally during the cool-down, no API request


def test_local_rate_budget(app):
    http = FakeHttp(FakeResponse(payload=gemini_body([good(i, prefix=f"P{k}") for k in range(1) for i in range(2)])))
    gen = install(app, http, per_minute=1)
    run_generate(app)
    with pytest.raises(QuotaExceeded):
        gen.generate("History")
    assert len(http.calls) == 1


def test_missing_api_key_app_still_works(app, client, user):
    assert app.extensions["question_generator"].enabled is False
    assert run_generate(app) == 0
    gid = start(client, "category", cat_id(app, "History"))
    assert gid and state(client, gid)["total"] == 2  # seeded questions only


def test_gameplay_survives_ai_failure_and_hides_internals(tmp_path):
    app = make_app(tmp_path)
    install(app, FakeHttp(FakeResponse(status=403, payload={"error": "API KEY INVALID test-key-123"})))
    c = app.test_client()
    register(c)
    login(c)
    gid = start(c, "category", cat_id(app, "Chess"))  # near end of the stored sequence -> tries Gemini, fails
    assert gid and state(c, gid)["total"] == 2
    page = c.get(f"/quiz/{gid}").get_data(as_text=True) + json.dumps(state(c, gid))
    assert "test-key-123" not in page and "INVALID" not in page


def test_top_up_when_sequence_exhausted(tmp_path):
    app = make_app(tmp_path)
    install(app, FakeHttp(FakeResponse(payload=gemini_body([good(i, prefix="Fresh") for i in range(10)]))))
    c = app.test_client()
    register(c)
    login(c)
    cid = cat_id(app, "Chess")
    g = start(c, "category", cid)  # 2 stored + 10 generated -> 5 questions per game
    assert state(c, g)["total"] == 5
    s = app.extensions["db_sessionmaker"]()
    assert s.query(Question).filter_by(category_id=cid, pool="category").count() == 12


def test_admin_generate_endpoint_requires_token(tmp_path):
    app = make_app(tmp_path, ADMIN_API_TOKEN="s3cret-token")
    install(app, FakeHttp(FakeResponse(payload=gemini_body([good(i) for i in range(3)]))))
    c = app.test_client()
    assert c.post("/api/admin/generate-questions", json={"category": "History"}).status_code == 401
    r = c.post("/api/admin/generate-questions", json={"category": "History"},
               headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 200 and r.get_json()["inserted"] == 3
    app2 = make_app(tmp_path / "x" if False else tmp_path, ADMIN_API_TOKEN="")
    assert app2.test_client().post("/api/admin/generate-questions", json={}).status_code == 404


def test_concurrent_generation_for_same_category_is_serialized(app):
    import time

    class Slow(FakeHttp):
        def post(self, *a, **k):
            time.sleep(0.3)
            return super().post(*a, **k)

    http = Slow(FakeResponse(payload=gemini_body([good(i) for i in range(5)])))
    install(app, http)
    results = []
    ts = [threading.Thread(target=lambda: results.append(run_generate(app))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [0, 0, 5] and len(http.calls) == 1
