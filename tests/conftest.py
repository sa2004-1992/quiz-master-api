import os
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import create_app
from app.models import Category, Question
from app.utils import clock

BASE_CFG = {
    "TESTING": True, "WTF_CSRF_ENABLED": False, "RATELIMIT_ENABLED": False,
    "SESSION_COOKIE_SECURE": False, "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1000",
    "QUESTIONS_PER_GAME": 5, "ALL_QUIZ_QUESTIONS": 6, "DAILY_QUESTION_COUNT": 4,
    "HINTS_PER_GAME": 3, "DAILY_HINTS": 2, "GEMINI_API_KEY": "", "APP_TIMEZONE": "Asia/Kolkata",
}


PG_URL = os.getenv("TEST_DATABASE_URL")  # e.g. postgresql+psycopg2://user:pw@localhost/quiztest


def make_app(tmp_path, **extra):
    url = PG_URL or f"sqlite:///{tmp_path}/test.db"
    cfg = dict(BASE_CFG, DATABASE_URL=url, **extra)
    return create_app(cfg)


@pytest.fixture(autouse=True)
def _clean_postgres():
    """When testing against PostgreSQL, start every test from an empty schema."""
    if PG_URL:
        from sqlalchemy import create_engine, text
        eng = create_engine(PG_URL)
        with eng.begin() as conn:
            # drop connections leaked by the previous test's app instances (idle-in-transaction locks)
            conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                              "WHERE datname = current_database() AND pid <> pg_backend_pid()"))
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        eng.dispose()
    yield


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    s = app.extensions["db_sessionmaker"]()
    yield s
    s.close()


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 3, 10, 6, 0, 0, tzinfo=timezone.utc)  # 11:30 IST

    def __call__(self):
        return self.now

    def advance(self, **kw):
        from datetime import timedelta
        self.now += timedelta(**kw)

    def set(self, y, m, d, h=6, mi=0):
        self.now = datetime(y, m, d, h, mi, tzinfo=timezone.utc)


@pytest.fixture
def fake_clock(monkeypatch):
    fc = FakeClock()
    monkeypatch.setattr(clock, "_now", fc)
    return fc


def register(client, username="alice", email=None, password="secret1", full_name="Alice Smith", gender="Female"):
    return client.post("/register", data=dict(
        full_name=full_name, email=email or f"{username}@example.com", username=username,
        gender=gender, password=password, confirm_password=password))


def login(client, identifier="alice", password="secret1", **kw):
    return client.post("/login", data=dict(identifier=identifier, password=password, **kw))


@pytest.fixture
def user(client):
    register(client)
    login(client)
    return "alice"


def add_questions(app, category_name, n, pool="category", prefix="Q"):
    """Insert n valid questions (correct answer cycles A..D). Returns their ids."""
    s = app.extensions["db_sessionmaker"]()
    try:
        cat = s.scalars(select(Category).where(Category.name == category_name)).one()
        ids = []
        for i in range(n):
            n_existing = s.query(Question).count()
            text = f"{prefix} {category_name} {pool} number {n_existing + i}"
            from app.services.question_validator import question_hash
            q = Question(pool=pool, category_id=cat.id, question_text=text, option_a="Alpha", option_b="Beta",
                         option_c="Gamma", option_d="Delta", correct_answer="ABCD"[(n_existing + i) % 4],
                         explanation="Because it is so.", difficulty="medium", question_hash=question_hash(text),
                         source="test")
            s.add(q)
            s.flush()
            ids.append(q.id)
        s.commit()
        return ids
    finally:
        s.close()


def cat_id(app, name):
    s = app.extensions["db_sessionmaker"]()
    try:
        return s.scalars(select(Category.id).where(Category.name == name)).one()
    finally:
        s.close()


def correct_letter(app, qid):
    s = app.extensions["db_sessionmaker"]()
    try:
        return s.get(Question, qid).correct_answer
    finally:
        s.close()


def wrong_letter(app, qid):
    return "A" if correct_letter(app, qid) != "A" else "B"


def start(client, kind="category", category_id=None):
    url = {"category": f"/quiz/start/category/{category_id}", "all": "/quiz/start/all",
           "daily": "/quiz/start/daily"}[kind]
    r = client.post(url)
    m = re.search(r"/quiz/(\d+)$", r.headers.get("Location", ""))
    return int(m.group(1)) if m else None


def api(client, gid, action, **payload):
    if action == "state":
        return client.get(f"/api/games/{gid}/state")
    return client.post(f"/api/games/{gid}/{action}", json=payload)


def state(client, gid):
    return api(client, gid, "state").get_json()["state"]


def answer(app, client, gid, correct=True):
    st = state(client, gid)
    qid = st["question"]["id"]
    letter = correct_letter(app, qid) if correct else wrong_letter(app, qid)
    return api(client, gid, "answer", question_id=qid, option=letter)


def play_through(app, client, gid, n, correct=True):
    for i in range(n):
        r = answer(app, client, gid, correct)
        assert r.status_code == 200, r.get_json()
        if i < n - 1:
            assert api(client, gid, "next").status_code == 200
