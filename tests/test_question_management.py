import csv
import io
import json
import sqlite3

import pytest
from sqlalchemy import func, select

from app.models import Category, DailyQuestionSet, PlayAllProgress, Question, QuizGame, UserCategoryProgress
from app.services import question_bank
from tests.conftest import api, cat_id, login, make_app, play_through, register, start, state
from tests.test_ai import FakeHttp, FakeResponse, gemini_body, good, install, kn_good

ADMIN = frozenset({"alice"})


@pytest.fixture
def adm_app(tmp_path):
    return make_app(tmp_path, ADMIN_USERNAMES=ADMIN)


@pytest.fixture
def admin(adm_app):
    c = adm_app.test_client()
    register(c, "alice")
    login(c, "alice")
    return c


def row(q, a="Alpha one", b="Beta two", c="Gamma three", d="Delta four", ans="B", expl="Because B is the right one.", cat="Math"):
    return [q, a, b, c, d, ans, expl, cat]


HEADER = ["question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation", "category_name"]


def make_csv(rows, header=HEADER, bom=False, newline="\n"):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=newline)
    if header is not None:
        w.writerow(header)
    w.writerows(rows)
    return (("\ufeff" if bom else "") + buf.getvalue()).encode("utf-8")


def post_csv(client, data, mode="category", category="any", name="questions.csv", step="preview"):
    return client.post(f"/api/admin/questions/csv/{step}", content_type="multipart/form-data",
                       data={"mode": mode, "category": category, "file": (io.BytesIO(data), name)})


def count(app, mode=None, cat=None):
    s = app.extensions["db_sessionmaker"]()
    try:
        q = select(func.count(Question.id))
        if mode:
            q = q.where(Question.pool == mode)
        if cat:
            q = q.where(Question.category_id == cat_id(app, cat))
        return s.scalar(q)
    finally:
        s.close()


def fetch(app, text):
    s = app.extensions["db_sessionmaker"]()
    try:
        return s.scalars(select(Question).where(Question.question_text == text)).all()
    finally:
        s.close()


# ===================================================================== access control
def test_only_listed_administrators_can_use_the_tools(adm_app, admin):
    anon = adm_app.test_client()
    assert anon.get("/admin/questions").status_code == 302
    for path in ["/api/admin/questions/counts", "/api/admin/questions/csv/template", "/api/admin/questions/list?mode=all"]:
        assert anon.get(path).status_code == 401
    assert anon.post("/api/admin/questions/generate", json={}).status_code == 401
    bob = adm_app.test_client()
    register(bob, "bob")
    login(bob, "bob")
    assert bob.get("/admin/questions").status_code == 403
    assert bob.get("/api/admin/questions/counts").status_code == 403
    assert post_csv(bob, make_csv([row("A perfectly fine question?")])).status_code == 403
    assert bob.post("/api/admin/questions/generate", json={"mode": "all", "count": 1}).status_code == 403
    assert admin.get("/admin/questions").status_code == 200
    assert "Manage Questions" in admin.get("/").get_data(as_text=True) and "Manage Questions" not in bob.get("/").get_data(as_text=True)


def test_tools_are_off_when_no_administrator_is_configured(tmp_path):
    app = make_app(tmp_path)
    c = app.test_client()
    register(c, "alice")
    login(c, "alice")
    assert c.get("/admin/questions").status_code == 404 and c.get("/api/admin/questions/counts").status_code == 404
    assert "Manage Questions" not in c.get("/").get_data(as_text=True)


def test_admin_posts_require_csrf(tmp_path):
    import re
    app = make_app(tmp_path, ADMIN_USERNAMES=ADMIN, WTF_CSRF_ENABLED=True)
    c = app.test_client()
    tok = lambda path: re.search(r'name="csrf_token" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)
    c.post("/register", data=dict(full_name="Al Ice", email="a@x.com", username="alice", gender="Male", password="secret1",
                                  confirm_password="secret1", csrf_token=tok("/register")))
    c.post("/login", data=dict(identifier="alice", password="secret1", csrf_token=tok("/login")))
    assert post_csv(c, make_csv([row("A perfectly fine question?")])).status_code == 400   # no token
    meta = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/admin/questions").get_data(as_text=True)).group(1)
    r = c.post("/api/admin/questions/csv/preview", headers={"X-CSRFToken": meta}, content_type="multipart/form-data",
               data={"mode": "category", "category": "any", "file": (io.BytesIO(make_csv([row("A perfectly fine question?")])), "q.csv")})
    assert r.status_code == 200 and r.get_json()["valid"] == 1


def test_admin_page_has_the_controls(admin):
    html = admin.get("/admin/questions").get_data(as_text=True)
    for text in ["Import from CSV", "Generate with Gemini", "Browse stored questions", "Question bank", "Category Quiz", "All Quiz",
                 "Daily Quiz", "Validate &amp; Preview", "Confirm Import", "Generate Questions", "Drag and drop a CSV file",
                 "question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, category_name"]:
        assert text in html, text
    assert html.count("<option") >= 3 * 56 // 56 and "Use category_name from each row" in html


# ===================================================================== CSV import: three modes
@pytest.mark.parametrize("mode", ["category", "all", "daily"])
def test_valid_csv_is_saved_only_to_the_selected_mode_with_generated_ids(adm_app, admin, mode):
    before = {m: count(adm_app, m) for m in ("category", "all", "daily")}
    data = make_csv([row("What is the capital of India?", "Mumbai", "New Delhi", "Bengaluru", "Chennai", "B",
                         "New Delhi is the capital of India.", "General Knowledge (GK)"),
                     row("How many sides does a hexagon have exactly?", "5", "6", "7", "8", "B", "A hexagon has six sides.", "Math")])
    assert post_csv(admin, data, mode).get_json()["valid"] == 2
    assert {m: count(adm_app, m) for m in before} == before  # a preview writes nothing
    r = post_csv(admin, data, mode, step="import").get_json()
    assert r["ok"] and r["imported"] == 2 and r["invalid"] == 0 and r["duplicates"] == 0 and r["mode"] == mode
    for m in before:
        assert count(adm_app, m) == before[m] + (2 if m == mode else 0)
    q = fetch(adm_app, "What is the capital of India?")[0]
    assert q.pool == mode and q.quiz_mode == mode and q.id and q.source == "csv" and q.correct_answer == "B"
    assert q.category_id == cat_id(adm_app, "General Knowledge (GK)") and q.daily_date is None
    assert r["first_id"] and r["last_id"] and r["last_id"] >= r["first_id"]  # ids were generated by the database


def test_selected_category_must_match_the_rows(adm_app, admin):
    math = str(cat_id(adm_app, "Math"))
    data = make_csv([row("What is two plus two in decimal?", cat="Math"), row("Which planet is known as the red one?", cat="Science")])
    j = post_csv(admin, data, "category", math).get_json()
    assert (j["valid"], j["invalid"]) == (1, 1) and "does not match the selected category" in j["problems"][0]["reason"]
    assert post_csv(admin, data, "category", "any").get_json()["valid"] == 2          # use each row's category_name
    assert post_csv(admin, data, "category", "").status_code == 400                     # a choice is required
    assert post_csv(admin, data, "category", "99999").status_code == 400
    assert post_csv(admin, data, "weekly", "any").status_code == 400                    # unknown mode


def test_invalid_rows_are_reported_never_silently_skipped(adm_app, admin):
    rows = [row("A valid question about numbers?"),
            row("Bad answer marker question?", ans="E"), row("Lower case marker question?", ans="b"),
            row("Empty answer marker question?", ans=""), row("Two letters marker question?", ans="AB"),
            row("Unknown category question?", cat="Astrology"), row("Missing option question?", c=""),
            row("", cat="Math"), row("Missing explanation question?", expl=""),
            ["Only seven columns here", "a", "b", "c", "d", "A", "expl text here"],
            row("Same options question?", "x", "x", "y", "z"), row("Missing category question?", cat="")]
    j = post_csv(admin, make_csv(rows)).get_json()
    assert j["total"] == 12 and j["valid"] == 1 and j["invalid"] == 11 and j["duplicates"] == 0
    reasons = " | ".join(p["reason"] for p in j["problems"])
    for text in ["correct_answer must be exactly A, B, C or D", "unknown category_name", "option_c is missing",
                 "question_text is missing", "explanation is missing", "expected 8 columns but found 7", "options must be distinct",
                 "category_name is missing"]:
        assert text in reasons, text
    assert len(j["problems"]) == 11 and all(p["row"] and p["line"] for p in j["problems"])
    imp = post_csv(admin, make_csv(rows), step="import").get_json()
    assert imp["imported"] == 1 and imp["invalid"] == 11 and imp["total"] == 12
    assert count(adm_app, "category", "Math") == 2 + 1  # 2 seeded + the one valid row


@pytest.mark.parametrize("header,message", [
    (HEADER[:-1], "exactly these 8 columns"), (HEADER + ["extra"], "exactly these 8 columns"),
    (["id"] + HEADER, "must not contain these columns: id"), (HEADER + ["quiz_mode"], "must not contain these columns: quiz_mode"),
    (list(reversed(HEADER)), "exactly these 8 columns"), (["a", "b"], "exactly these 8 columns")])
def test_header_must_be_exactly_the_eight_columns(admin, header, message):
    r = post_csv(admin, make_csv([row("Some question text here?")], header=header))
    assert r.status_code == 400 and message in r.get_json()["error"]


def test_file_level_validation(adm_app, admin):
    assert "Please upload a .csv file" in post_csv(admin, make_csv([row("Some question text here?")]), name="q.txt").get_json()["error"]
    assert "file is empty" in post_csv(admin, b"").get_json()["error"]
    assert "no questions" in post_csv(admin, make_csv([])).get_json()["error"]
    assert "UTF-8" in post_csv(admin, b"question_text,\xff\xfa\xfb").get_json()["error"]
    assert "text CSV" in post_csv(admin, b"question_text,\x00\x01binary").get_json()["error"]
    assert "text CSV" in post_csv(admin, "question_text,".encode("utf-16")).get_json()["error"]
    assert admin.post("/api/admin/questions/csv/preview", data={"mode": "category", "category": "any"}).status_code == 400  # no file


def test_size_and_row_limits(tmp_path):
    app = make_app(tmp_path, ADMIN_USERNAMES=ADMIN, CSV_MAX_BYTES=2000, CSV_MAX_ROWS=3)
    c = app.test_client()
    register(c, "alice")
    login(c, "alice")
    four = make_csv([row(f"Question number {i} about numbers?") for i in range(4)])
    assert "Too many rows" in post_csv(c, four).get_json()["error"]
    big = make_csv([row("Short question number one?")]) + b"x" * 5000
    r = post_csv(c, big)
    assert r.status_code in (400, 413) and ("too large" in r.get_json()["error"].lower())


def test_kannada_unicode_commas_quotes_and_newlines_round_trip(adm_app, admin):
    kn = ["ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ ಯಾವುದು?", "ಮೈಸೂರು", "ಬೆಂಗಳೂರು", "ಮಂಗಳೂರು", "ಹುಬ್ಬಳ್ಳಿ", "B", "ಬೆಂಗಳೂರು ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ.", "Kannada"]
    tricky = row('Which of these, "quoted", words\nspans two lines, with commas?', 'He said "yes", then left', "plain",
                 "line one\nline two", "a, b, c", "A", 'Explanation with "quotes", commas,\nand a line break.', "English")
    english_in_kannada = row("An English question in the Kannada category?", cat="Kannada")
    data = make_csv([kn, tricky, english_in_kannada], bom=True, newline="\r\n")   # Excel style: BOM + CRLF
    j = post_csv(admin, data, "all").get_json()
    assert (j["valid"], j["invalid"]) == (2, 1) and "must be written in Kannada" in j["problems"][0]["reason"]
    post_csv(admin, data, "all", step="import")
    s = adm_app.extensions["db_sessionmaker"]()
    k = s.scalars(select(Question).where(Question.question_text == kn[0])).one()
    assert (k.option_b, k.explanation, k.pool) == ("ಬೆಂಗಳೂರು", "ಬೆಂಗಳೂರು ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ.", "all")
    t = s.scalars(select(Question).where(Question.pool == "all", Question.category_id == cat_id(adm_app, "English"))
                  .order_by(Question.id.desc())).first()
    assert t.question_text == tricky[0].replace("\r", "") and t.option_a == 'He said "yes", then left' and t.option_c == "line one\nline two"
    s.close()
    html = admin.get("/api/admin/questions/list?mode=all&category=" + str(cat_id(adm_app, "Kannada"))).get_json()
    assert any(i["question"] == kn[0] for i in html["items"])


def test_blank_lines_are_counted_not_hidden(admin):
    data = make_csv([row("First question about numbers?")]) + b"\n\n" + make_csv([row("Second question about numbers?")], header=None)
    j = post_csv(admin, data).get_json()
    assert j["total"] == 2 and j["blank_lines_ignored"] == 2 and j["valid"] == 2


# ===================================================================== duplicates (per mode + category)
KIDNEY = "Which organ in the human body filters the blood to produce urine in adults?"


def kidney(cat="Health & Human Body", q=KIDNEY, ans="B"):
    return row(q, "Heart", "Kidney", "Liver", "Lung", ans, "The kidneys filter blood and produce urine.", cat)


def test_duplicates_are_blocked_inside_a_mode_and_category_only(adm_app, admin):
    data = make_csv([kidney()])
    assert post_csv(admin, data, "category", step="import").get_json()["imported"] == 1
    again = post_csv(admin, data, "category", step="import").get_json()
    assert again["imported"] == 0 and again["duplicates"] == 1                       # same mode + category: blocked
    assert post_csv(admin, data, "all", step="import").get_json()["imported"] == 1   # another mode: independent
    assert post_csv(admin, data, "daily", step="import").get_json()["imported"] == 1
    assert post_csv(admin, make_csv([kidney("Science")]), "category", step="import").get_json()["imported"] == 1  # other category: allowed
    assert len(fetch(adm_app, KIDNEY)) == 4


def test_duplicates_inside_the_same_file_and_text_normalisation(admin):
    rows = [row("What is the capital of France exactly?"), row("what is the CAPITAL of france, exactly"), row("What  is the capital of France exactly??")]
    j = post_csv(admin, make_csv(rows)).get_json()
    assert (j["valid"], j["duplicates"]) == (1, 2) and "exact question already exists" in j["problems"][0]["reason"]


def test_near_duplicates_are_flagged_but_different_facts_are_not(admin):
    post_csv(admin, make_csv([kidney()]), step="import")
    reworded = kidney(q="Which organ in the human body filters the blood to produce the urine in adults?")
    j = post_csv(admin, make_csv([reworded])).get_json()
    assert j["duplicates"] == 1 and "near-duplicate" in j["problems"][0]["reason"]
    # same wording but a different correct answer is a different question
    different_answer = row("Which organ in the human body filters the blood to produce the urine in adults?",
                           "Kidney", "Heart", "Liver", "Lung", "B", "A different answer for the same wording.", "Health & Human Body")
    assert post_csv(admin, make_csv([different_answer])).get_json()["valid"] == 1
    # numbers that differ mean a different fact
    nums = [row("How many degrees are there in a right angle shape 90?", "90", "180", "45", "60", "A", cat="Math"),
            row("How many degrees are there in a right angle shape 91?", "90", "180", "45", "60", "A", cat="Math")]
    assert post_csv(admin, make_csv(nums)).get_json()["valid"] == 2
    short = [row("What is 12 times 12?", "144", "124", "122", "164", "A", cat="Math"),
             row("What is 12 times 13?", "156", "124", "122", "164", "A", cat="Math")]
    assert post_csv(admin, make_csv(short)).get_json()["valid"] == 2


def test_questions_close_to_the_starter_bank_are_caught_too(admin):
    close = row("Which gas do plants absorb from the air for photosynthesis?", "Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen", "C",
                "Plants take in carbon dioxide.", "Science")
    j = post_csv(admin, make_csv([close])).get_json()
    assert j["duplicates"] == 1 and "exact question already exists" in j["problems"][0]["reason"]


def test_existing_questions_are_never_overwritten_or_deleted(adm_app, admin):
    before = count(adm_app)
    s = adm_app.extensions["db_sessionmaker"]()
    first = s.scalars(select(Question).order_by(Question.id)).first()
    snapshot = (first.id, first.question_text, first.explanation)
    s.close()
    post_csv(admin, make_csv([row("A brand new question about numbers?")]), step="import")
    assert count(adm_app) == before + 1
    s = adm_app.extensions["db_sessionmaker"]()
    again = s.get(Question, snapshot[0])
    assert (again.id, again.question_text, again.explanation) == snapshot
    s.close()


def test_import_failure_reports_nothing_saved(adm_app, admin, monkeypatch):
    monkeypatch.setattr(question_bank, "insert_valid", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db password leaked")))
    r = post_csv(admin, make_csv([row("A question that will fail to save?")]), step="import")
    assert r.status_code == 500 and "leaked" not in r.get_data(as_text=True) and "Nothing was imported" in r.get_json()["error"]
    assert count(adm_app, "category", "Math") == 2


# ===================================================================== Gemini generation (mocked)
def gen(client, **body):
    return client.post("/api/admin/questions/generate", json=body)


def batch(prefix, n=10, **over):
    return FakeResponse(payload=gemini_body([good(i, prefix=prefix) for i in range(n)]))


def test_generation_for_category_quiz_saves_to_that_category_only(adm_app, admin):
    install(adm_app, FakeHttp(batch("Cat")))
    before = {m: count(adm_app, m) for m in ("category", "all", "daily")}
    r = gen(admin, mode="category", category=str(cat_id(adm_app, "Science")), count=10, language="auto")
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and (j["saved"], j["generated"], j["duplicates"], j["invalid"]) == (10, 10, 0, 0)
    assert count(adm_app, "category") == before["category"] + 10 and count(adm_app, "all") == before["all"] and count(adm_app, "daily") == before["daily"]
    assert count(adm_app, "category", "Science") == 2 + 10
    s = adm_app.extensions["db_sessionmaker"]()
    new = s.scalars(select(Question).where(Question.source == "ai")).all()
    assert {(q.pool, q.category_id) for q in new} == {("category", cat_id(adm_app, "Science"))}
    s.close()


def test_generation_for_all_quiz_goes_to_the_all_dataset_in_batches(adm_app, admin):
    http = FakeHttp(batch("A1"), batch("A2"), batch("A3", 5))
    install(adm_app, http)
    before = {m: count(adm_app, m) for m in ("category", "all", "daily")}
    j = gen(admin, mode="all", count=25).get_json()
    assert j["ok"] and j["saved"] == 25 and len(http.calls) == 3 and [d["requested"] for d in j["details"]] == [10, 10, 5]
    assert len({d["category"] for d in j["details"]}) == 3                       # spread across categories
    assert count(adm_app, "all") == before["all"] + 25 and count(adm_app, "category") == before["category"] and count(adm_app, "daily") == before["daily"]
    s = adm_app.extensions["db_sessionmaker"]()
    assert {q.pool for q in s.scalars(select(Question).where(Question.source == "ai"))} == {"all"}
    s.close()


def test_generation_for_daily_quiz_is_english_only_and_stays_in_daily(adm_app, admin):
    install(adm_app, FakeHttp(batch("D1"), batch("D2")))
    j = gen(admin, mode="daily", count=20, language="auto").get_json()
    assert j["ok"] and j["saved"] == 20 and "Kannada" not in {d["category"] for d in j["details"]}
    s = adm_app.extensions["db_sessionmaker"]()
    assert {q.pool for q in s.scalars(select(Question).where(Question.source == "ai"))} == {"daily"}
    s.close()


def test_kannada_generation_requires_kannada_everywhere(adm_app, admin):
    items = [kn_good(i) for i in range(3)] + [good(9), {**kn_good(7), "option_c": "Mangaluru"}, {**kn_good(8), "explanation": "Bengaluru is the capital"}]
    http = FakeHttp(FakeResponse(payload=gemini_body(items)))
    install(adm_app, http)
    j = gen(admin, mode="category", category=str(cat_id(adm_app, "Kannada")), count=6, language="auto").get_json()
    assert j["saved"] == 3 and j["invalid"] == 3                                  # English / mixed-language items are rejected
    assert "Kannada" in http.calls[0]["json"]["contents"][0]["parts"][0]["text"]
    assert j["details"][0]["category"] == "Kannada"


def test_language_rules_and_input_validation(adm_app, admin):
    install(adm_app, FakeHttp(batch("L")))
    kn, sci = str(cat_id(adm_app, "Kannada")), str(cat_id(adm_app, "Science"))
    assert gen(admin, mode="category", category=kn, count=5, language="en").status_code == 400
    assert gen(admin, mode="category", category=sci, count=5, language="kn").status_code == 400
    assert gen(admin, mode="category", count=5).status_code == 400                       # category required
    for bad in (0, -1, 31, "abc", None, 2.5, True, ""):
        assert gen(admin, mode="all", count=bad).status_code == 400, bad
    assert gen(admin, mode="weekly", count=5).status_code == 400
    assert gen(admin, mode="category", category="99999", count=5).status_code == 400
    assert gen(admin, mode="all", count=5, language="fr").status_code == 400
    assert admin.post("/api/admin/questions/generate", data="nope", content_type="text/plain").status_code == 400
    j = gen(admin, mode="all", count=10, language="kn").get_json()
    assert [d["category"] for d in j["details"]] == ["Kannada"]                          # Kannada only


def test_invalid_gemini_responses_save_nothing_and_leak_nothing(adm_app, admin):
    for resp in (FakeResponse(payload={"unexpected": 1}), FakeResponse(payload={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}),
                 FakeResponse(status=403, payload={"error": "KEY test-key-123 INVALID"})):
        install(adm_app, FakeHttp(resp))
        r = gen(admin, mode="all", count=10)
        text = r.get_data(as_text=True)
        assert r.status_code == 502 and r.get_json()["ok"] is False and r.get_json()["saved"] == 0
        assert "test-key-123" not in text and "INVALID" not in text and "Gemini could not generate" in r.get_json()["error"]
    assert count(adm_app, "all") == 112


def test_quota_network_and_partial_results(adm_app, admin):
    import requests
    install(adm_app, FakeHttp(FakeResponse(status=429, payload={})))
    r = gen(admin, mode="category", category=str(cat_id(adm_app, "Math")), count=10)
    assert r.status_code == 502 and "quota or rate limit" in r.get_json()["error"]
    install(adm_app, FakeHttp(requests.Timeout("slow")))
    assert "could not generate" in gen(admin, mode="category", category=str(cat_id(adm_app, "Math")), count=10).get_json()["error"]
    install(adm_app, FakeHttp(batch("P1"), FakeResponse(status=429, payload={})))
    j = gen(admin, mode="all", count=20).get_json()                                       # first batch saved, then quota
    assert j["ok"] and j["saved"] == 10 and "quota or rate limit" in j["error"] and "10 question(s) were saved" in j["error"]
    assert count(adm_app, "all") == 112 + 10


def test_generated_duplicates_are_not_saved_twice(adm_app, admin):
    install(adm_app, FakeHttp(batch("Same")))
    c = str(cat_id(adm_app, "History"))
    assert gen(admin, mode="category", category=c, count=10).get_json()["saved"] == 10
    j = gen(admin, mode="category", category=c, count=10).get_json()
    assert j["saved"] == 0 and j["duplicates"] == 10 and j["ok"]
    assert gen(admin, mode="all", count=10).get_json()["saved"] == 10                     # another mode keeps its own copy


def test_gemini_not_configured_still_allows_csv_and_play(adm_app, admin):
    r = gen(admin, mode="all", count=5)
    assert r.status_code == 502 and "not configured" in r.get_json()["error"]
    assert post_csv(admin, make_csv([row("A question imported without Gemini?")]), step="import").get_json()["imported"] == 1
    assert "Gemini is not configured" in admin.get("/admin/questions").get_data(as_text=True)
    g = start(admin, "category", cat_id(adm_app, "Math"))
    assert g and state(admin, g)["total"] >= 2                                            # stored questions remain playable


def test_the_api_key_is_never_in_pages_scripts_or_responses(tmp_path):
    app = make_app(tmp_path, ADMIN_USERNAMES=ADMIN, GEMINI_API_KEY="super-secret-key-999")
    c = app.test_client()
    register(c, "alice")
    login(c, "alice")
    for path in ["/admin/questions", "/static/js/admin_questions.js", "/api/admin/questions/counts", "/"]:
        assert "super-secret-key-999" not in c.get(path).get_data(as_text=True)
    http = FakeHttp(FakeResponse(status=403, payload={"error": "bad key super-secret-key-999"}))
    install(app, http)
    install(app, http).api_key = "super-secret-key-999"
    r = gen(c, mode="all", count=5)
    assert "super-secret-key-999" not in r.get_data(as_text=True)


def test_generation_requests_are_rate_limited(tmp_path):
    app = make_app(tmp_path, ADMIN_USERNAMES=ADMIN, RATELIMIT_ENABLED=True, ADMIN_GENERATE_RATE_LIMIT="2 per minute")
    c = app.test_client()
    register(c, "alice")
    login(c, "alice")
    install(app, FakeHttp(batch("R")))
    codes = [gen(c, mode="all", count=1).status_code for _ in range(4)]
    assert codes[2:] == [429, 429] and 429 not in codes[:2]


# ===================================================================== isolation of the three datasets
def _questions_of(app, gid):
    s = app.extensions["db_sessionmaker"]()
    try:
        game = s.get(QuizGame, gid)
        return {q.pool for q in s.scalars(select(Question).where(Question.id.in_(game.question_ids)))}
    finally:
        s.close()


def test_each_quiz_mode_only_ever_retrieves_its_own_questions(adm_app, admin, fake_clock):
    for mode in ("category", "all", "daily"):                                              # mode-specific questions everywhere
        rows = [row(f"{mode.upper()} only question number {i} about numbers?", cat=cat) for i in range(12) for cat in ("Math", "History")]
        post_csv(admin, make_csv(rows), mode, step="import")
    g1 = start(admin, "category", cat_id(adm_app, "Math"))
    assert _questions_of(adm_app, g1) == {"category"}
    play_through(adm_app, admin, g1, 5)
    api(admin, g1, "finish")
    g2 = start(admin, "all")
    assert _questions_of(adm_app, g2) == {"all"}
    g3 = start(admin, "daily")
    assert _questions_of(adm_app, g3) == {"daily"}
    s = adm_app.extensions["db_sessionmaker"]()
    ds = s.scalars(select(DailyQuestionSet)).one()
    assert {q.pool for q in s.scalars(select(Question).where(Question.id.in_(ds.question_ids)))} == {"daily"}
    assert len(ds.question_ids) <= 50 and s.get(UserCategoryProgress, (1, cat_id(adm_app, "Math"))).pointer == 5
    assert s.get(PlayAllProgress, 1) is None                                               # progress pointers stay independent
    s.close()
    texts = {m: {i["question"] for i in admin.get(f"/api/admin/questions/list?mode={m}").get_json()["items"]} for m in ("category", "all", "daily")}
    assert not any("ALL only" in t or "DAILY only" in t for t in texts["category"])
    assert not any("CATEGORY only" in t or "DAILY only" in t for t in texts["all"])
    assert not any("CATEGORY only" in t or "ALL only" in t for t in texts["daily"])


def test_all_quiz_follows_the_fixed_category_order_from_its_own_dataset(adm_app, admin):
    post_csv(admin, make_csv([row("Only in the category quiz about zebras?", cat="Math")]), "category", step="import")
    g = start(admin, "all")
    s = adm_app.extensions["db_sessionmaker"]()
    game = s.get(QuizGame, g)
    qs = [s.get(Question, i) for i in game.question_ids]
    assert [q.category_id for q in qs][:6] == [1, 2, 3, 4, 5, 6] and {q.pool for q in qs} == {"all"}
    assert "zebras" not in " ".join(q.question_text for q in qs)
    s.close()


def test_counts_and_browse_endpoints_are_mode_specific(adm_app, admin):
    post_csv(admin, make_csv([row("A distinctive all-quiz-only question here?", cat="Math")]), "all", step="import")
    j = admin.get("/api/admin/questions/counts").get_json()
    math = next(r for r in j["rows"] if r["name"] == "Math")
    assert (math["category"], math["all"], math["daily"]) == (2, 3, 2) and len(j["rows"]) == 56
    assert [r["name"] for r in j["rows"]][:3] == ["History", "Math", "Science"]
    assert j["totals"] == {"category": 112, "all": 113, "daily": 110}
    items = admin.get(f"/api/admin/questions/list?mode=all&category={cat_id(adm_app, 'Math')}").get_json()
    assert items["total"] == 3 and {i["mode"] for i in items["items"]} == {"all"}
    assert admin.get("/api/admin/questions/list?mode=category&category=" + str(cat_id(adm_app, "Math"))).get_json()["total"] == 2
    assert admin.get("/api/admin/questions/list?mode=nope").status_code == 400
    assert admin.get("/api/admin/questions/list?mode=all&page=abc").status_code == 400
    assert "question_text,option_a" in admin.get("/api/admin/questions/csv/template").get_data(as_text=True)


def test_seed_bank_is_copied_into_each_mode_once(adm_app):
    s = adm_app.extensions["db_sessionmaker"]()
    assert count(adm_app, "category") == 112 and count(adm_app, "all") == 112 and count(adm_app, "daily") == 110
    from app.services.seed import seed_questions
    assert seed_questions(s) == 0                                                          # re-running adds nothing
    s.close()


# ===================================================================== database upgrade
def _downgrade_sqlite_to_old_schema(path):
    """Rebuild questions with the PREVIOUS version's constraints (no 'all' mode, unique on pool + hash)."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("PRAGMA legacy_alter_table=ON")
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='questions'").fetchone()[0]
    old = (ddl.replace("'category','all','daily'", "'category','daily'")
              .replace("CONSTRAINT uq_questions_pool_cat_hash UNIQUE (pool, category_id, question_hash)",
                       "CONSTRAINT uq_questions_pool_hash UNIQUE (pool, question_hash)"))
    assert old != ddl
    con.execute("DELETE FROM questions WHERE pool = 'all'")
    con.execute("ALTER TABLE questions RENAME TO questions_tmp")
    con.execute("DROP INDEX IF EXISTS ix_questions_pool_cat_id")
    con.execute(old)
    con.execute("INSERT INTO questions SELECT * FROM questions_tmp")
    con.execute("DROP TABLE questions_tmp")
    con.execute("CREATE INDEX ix_questions_pool_cat_id ON questions (pool, category_id, id)")
    con.commit()
    con.close()


@pytest.mark.skipif(bool(__import__("os").getenv("TEST_DATABASE_URL")), reason="SQLite-specific (the PostgreSQL run covers the PG upgrade)")
def test_sqlite_upgrade_preserves_questions_games_answers_and_relationships(tmp_path):
    app1 = make_app(tmp_path)
    c = app1.test_client()
    register(c, "olduser")
    login(c, "olduser")
    g = start(c, "category", cat_id(app1, "Math"))
    play_through(app1, c, g, 2)
    api(c, g, "finish")
    path = tmp_path / "test.db"
    _downgrade_sqlite_to_old_schema(path)
    con = sqlite3.connect(path)
    try:
        con.execute("INSERT INTO questions (pool, category_id, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, difficulty, question_hash, source, created_at) VALUES ('all', 1, 'x', 'a','b','c','d','A','e','easy','h','t','2026-01-01')")
        raise AssertionError("the old schema must reject the 'all' mode")
    except sqlite3.IntegrityError:
        pass
    ids_before = [r[0] for r in con.execute("SELECT id FROM questions ORDER BY id")]
    answers_before = con.execute("SELECT game_id, question_id, is_correct FROM quiz_game_answers ORDER BY id").fetchall()
    con.close()
    app2 = make_app(tmp_path)                                                              # start the NEW version on the OLD database
    con = sqlite3.connect(path)
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='questions'").fetchone()[0]
    assert "'all'" in ddl and "uq_questions_pool_cat_hash" in ddl and "uq_questions_pool_hash" not in ddl
    ids_after = [r[0] for r in con.execute("SELECT id FROM questions WHERE pool IN ('category','daily') ORDER BY id")]
    assert ids_after == ids_before                                                          # every original question and id kept
    assert con.execute("SELECT game_id, question_id, is_correct FROM quiz_game_answers ORDER BY id").fetchall() == answers_before
    assert con.execute("SELECT status, score FROM quiz_games").fetchall() == [("completed", 20)]
    con.execute("PRAGMA foreign_keys=ON")
    assert con.execute("PRAGMA foreign_key_check").fetchall() == [] and con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT COUNT(*) FROM questions WHERE pool='all'").fetchone()[0] == 112  # All Quiz starter bank seeded
    con.close()
    c2 = app2.test_client()
    login(c2, "olduser")
    assert c2.get("/history").status_code == 200 and b"Math" in c2.get("/history").data     # history intact
    make_app(tmp_path)                                                                       # a second start is a no-op


@pytest.mark.skipif(not __import__("os").getenv("TEST_DATABASE_URL"), reason="needs PostgreSQL (TEST_DATABASE_URL)")
def test_postgres_upgrade_is_additive_and_idempotent(tmp_path):
    import os
    from sqlalchemy import create_engine, text
    app1 = make_app(tmp_path)
    eng = create_engine(os.environ["TEST_DATABASE_URL"])
    with eng.begin() as conn:                                                               # put the old constraints back
        conn.execute(text("DELETE FROM questions WHERE pool = 'all'"))
        conn.execute(text("ALTER TABLE questions DROP CONSTRAINT ck_questions_pool"))
        conn.execute(text("ALTER TABLE questions ADD CONSTRAINT ck_questions_pool CHECK (pool IN ('category','daily'))"))
        conn.execute(text("ALTER TABLE questions DROP CONSTRAINT uq_questions_pool_cat_hash"))
        conn.execute(text("ALTER TABLE questions ADD CONSTRAINT uq_questions_pool_hash UNIQUE (pool, question_hash)"))
        before = conn.execute(text("SELECT COUNT(*) FROM questions")).scalar()
    app2 = make_app(tmp_path)
    make_app(tmp_path)
    with eng.begin() as conn:
        names = {r[0] for r in conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid='questions'::regclass"))}
        assert "uq_questions_pool_cat_hash" in names and "uq_questions_pool_hash" not in names
        assert "'all'" in conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_questions_pool'")).scalar()
        assert conn.execute(text("SELECT COUNT(*) FROM questions WHERE pool <> 'all'")).scalar() == before
    eng.dispose()
    assert app1 and app2


# ===================================================================== the admin page script, run in a DOM
def test_admin_page_javascript_end_to_end(adm_app, admin, tmp_path):
    import os
    import shutil
    import subprocess
    env = dict(os.environ)
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, env=env).returncode != 0:
        pytest.skip("node + jsdom not available (npm install jsdom; set NODE_PATH to its node_modules)")
    install(adm_app, FakeHttp(batch("UI")))
    rows = [kidney(), row("Bad answer marker for this question?", ans="Z"), row("Unknown category for this question?", cat="Nope")]
    data = make_csv(rows)
    html = admin.get("/admin/questions").get_data(as_text=True)
    counts_before = admin.get("/api/admin/questions/counts").get_json()
    preview = post_csv(admin, data, "category").get_json()
    imported = post_csv(admin, data, "category", step="import").get_json()
    generated = gen(admin, mode="all", count=10).get_json()
    listing = admin.get("/api/admin/questions/list?mode=all").get_json()
    fixture = {"html": html, "counts": counts_before, "preview": preview, "import": imported, "generate": generated, "list": listing}
    path = tmp_path / "admin.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    r = subprocess.run(["node", "tests/js/admin_ui_check.js", str(path)], capture_output=True, text=True, env=env, cwd=".")
    assert r.returncode == 0 and "admin ui ok" in r.stdout, r.stderr + r.stdout
