from sqlalchemy import select
from werkzeug.security import check_password_hash

from app.categories import CATEGORY_NAMES
from app.models import User
from tests.conftest import login, make_app, register


def test_register_success_and_password_is_hashed(client, db):
    r = register(client)
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    u = db.scalars(select(User).where(User.username == "alice")).one()
    assert u.password_hash != "secret1" and "secret1" not in u.password_hash
    assert check_password_hash(u.password_hash, "secret1")
    assert u.preferences is not None and u.preferences.dark_mode is False


def test_duplicate_username_and_email(client):
    register(client)
    r = register(client, username="ALICE", email="other@example.com")
    assert r.status_code == 400 and b"already taken" in r.data
    r = register(client, username="bob", email="Alice@Example.com")
    assert r.status_code == 400 and b"already exists" in r.data


def test_registration_validation(client):
    assert b"at least 6" in register(client, password="12345").data
    r = client.post("/register", data=dict(full_name="A B", email="a@b.co", username="abc", gender="Male",
                                           password="secret1", confirm_password="different"))
    assert b"do not match" in r.data
    r = client.post("/register", data=dict(full_name="A B", email="a@b.co", username="abc", gender="Robot",
                                           password="secret1", confirm_password="secret1"))
    assert r.status_code == 400
    assert client.post("/register", data={}).status_code == 400


def test_registration_field_order(client):
    html = client.get("/register").get_data(as_text=True)
    order = [html.index(f'name="{n}"') for n in
             ["full_name", "email", "username", "gender", "password", "confirm_password"]]
    assert order == sorted(order)


def test_login_by_username_or_email_and_generic_error(client):
    register(client)
    assert login(client, "alice").status_code == 302
    client.post("/logout")
    assert login(client, "ALICE@example.com").status_code == 302
    client.post("/logout")
    bad_pw = login(client, "alice", "wrong-pass")
    unknown = login(client, "nobody", "wrong-pass")
    assert bad_pw.status_code == unknown.status_code == 401
    assert b"Invalid username/email or password." in bad_pw.data
    assert b"Invalid username/email or password." in unknown.data


def test_logout_requires_post_and_clears_session(client, user):
    assert client.get("/logout").status_code == 405
    assert client.get("/").status_code == 200
    client.post("/logout")
    assert client.get("/").status_code == 302


def test_protected_routes_and_api(client):
    for path in ["/", "/quizzes", "/all-quiz", "/history", "/leaderboard", "/profile", "/performance",
                 "/achievements", "/bookmarks", "/feedback"]:
        r = client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"], path
    assert client.get("/api/games/1/state").status_code == 401
    assert client.post("/api/preferences/theme", json={"dark": True}).status_code == 401
    assert client.post("/quiz/start/all").status_code == 302


def test_open_redirect_blocked(client):
    register(client)
    r = client.post("/login?next=//evil.example", data=dict(identifier="alice", password="secret1"))
    assert r.headers["Location"] in ("/", "/home")
    assert "evil" not in r.headers["Location"]


def test_session_renewed_on_login(client):
    register(client)
    with client.session_transaction() as s:
        s["junk"] = "pre-login"
    login(client)
    with client.session_transaction() as s:
        assert "junk" not in s and "uid" in s


def test_rate_limit_on_login(tmp_path):
    app = make_app(tmp_path, RATELIMIT_ENABLED=True, LOGIN_RATE_LIMIT="3 per minute")
    c = app.test_client()
    codes = [login(c, "x", "y").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429


def test_csrf_protection(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    c = app.test_client()
    assert c.post("/register", data={}).status_code == 400  # no token
    html = c.get("/login").get_data(as_text=True)
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    r = c.post("/login", data=dict(identifier="x", password="y", csrf_token=token))
    assert r.status_code == 401  # passed CSRF, failed credentials


def test_csrf_on_state_changing_api(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    c = app.test_client()
    import re
    tok = lambda path: re.search(r'name="csrf_token" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)
    c.post("/register", data=dict(full_name="Al Ice", email="a@x.com", username="alice", gender="Male",
                                  password="secret1", confirm_password="secret1", csrf_token=tok("/register")))
    c.post("/login", data=dict(identifier="alice", password="secret1", csrf_token=tok("/login")))
    assert c.post("/api/preferences/theme", json={"dark": True}).status_code == 400
    meta = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").get_data(as_text=True)).group(1)
    assert c.post("/api/preferences/theme", json={"dark": True}, headers={"X-CSRFToken": meta}).status_code == 200


def test_categories_order_and_search(client, user):
    html = client.get("/quizzes").get_data(as_text=True)
    import re
    from html import unescape
    names = [unescape(n) for n in re.findall(r'class="category-name">([^<]+)<', html)]
    assert names == CATEGORY_NAMES and len(names) == 56
    assert "description" not in html.lower()
    found = [unescape(n) for n in re.findall(r'class="category-name">([^<]+)<', client.get("/quizzes?q=cric").get_data(as_text=True))]
    assert found == ["Cricket"]


def test_dark_mode_persists_across_logout(client, user):
    assert b'data-theme="light"' in client.get("/").data
    assert client.post("/api/preferences/theme", json={"dark": True}).status_code == 200
    assert client.post("/api/preferences/theme", json={"dark": "yes"}).status_code == 400
    client.post("/logout")
    login(client)
    assert b'data-theme="dark"' in client.get("/").data


def test_health_endpoint(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


def test_security_headers(client):
    r = client.get("/login")
    assert r.headers["X-Frame-Options"] == "DENY" and "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_env_placeholders_are_ignored_and_bad_url_is_clear(monkeypatch):
    import importlib

    import config
    monkeypatch.setenv("DATABASE_URL", "replace_with_supabase_postgresql_connection_string")
    monkeypatch.setenv("GEMINI_MODEL", "replace_with_supported_model_name")
    monkeypatch.setenv("GEMINI_API_KEY", "replace_with_your_gemini_api_key")
    cfg = importlib.reload(config).Config
    assert cfg.DATABASE_URL == "" and cfg.GEMINI_API_KEY == "" and cfg.GEMINI_MODEL == "gemini-3.1-flash-lite"
    monkeypatch.setenv("DATABASE_URL", "not a url")
    importlib.reload(config)
    import pytest
    from flask import Flask
    app = Flask("x")
    app.config.from_object(config.Config)
    app.config["TESTING"] = False
    app.config["IS_PRODUCTION"] = False
    with pytest.raises(RuntimeError, match="not a valid database URL"):
        config.finalize(app)
    monkeypatch.undo()
    importlib.reload(config)
