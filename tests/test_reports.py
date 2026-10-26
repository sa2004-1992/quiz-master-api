from datetime import datetime

from sqlalchemy import select

from app.models import (Bookmark, Category, PlayAllProgress, Question, QuizGame, QuizGameAnswer, User,
                        UserCategoryProgress, UserPreference)
from tests.conftest import (add_questions, api, answer, cat_id, login, make_app, play_through, register,
                            start, state)


def saved_game(app, user_id, quiz_type="category", category="Math", score=50, elapsed=100,
               finished=datetime(2026, 3, 10, 2, 0), difficulty="Easy"):
    s = app.extensions["db_sessionmaker"]()
    try:
        g = QuizGame(user_id=user_id, quiz_type=quiz_type,
                     category_id=cat_id(app, category) if quiz_type == "category" else None,
                     status="completed", active_key=None, question_ids=[1], seq_positions=[0],
                     resolved_count=5, correct_count=5, score=score, elapsed_seconds=elapsed,
                     started_at=finished, finished_at=finished, difficulty=difficulty)
        s.add(g)
        s.commit()
        return g.id
    finally:
        s.close()


def second_user(app, name="bob"):
    c = app.test_client()
    register(c, name)
    login(c, name)
    return c


def test_history_only_saved_own_games_labels_and_pagination(app, client, user, fake_clock):
    for i in range(25):
        saved_game(app, 1, finished=datetime(2026, 3, 1, 2, 0, i))
    saved_game(app, 1, "all", score=7, finished=datetime(2026, 3, 2))
    saved_game(app, 1, "daily", score=9, finished=datetime(2026, 3, 3))
    bob = second_user(app)
    saved_game(app, 2, score=999)
    html = client.get("/history").get_data(as_text=True)
    assert html.count("<tr>") - 1 == 20 and "999" not in html
    assert "Daily Quiz" in html
    p2 = client.get("/history?page=2").get_data(as_text=True)
    assert p2.count("<tr>") - 1 == 7 and "Page 2 of 2" in p2
    assert client.get("/history?page=abc").status_code == 200
    assert client.get("/history?page=999").status_code == 200  # clamped
    assert "999" in bob.get("/history").get_data(as_text=True)
    first = client.get("/history").get_data(as_text=True)
    assert first.index("Daily Quiz") < first.index("Math")  # newest first
    for col in ["Date", "Game", "Category Name", "Difficulty", "Time", "Score"]:
        assert f"<th>{col}</th>" in first or f'<th class="num">{col}</th>' in first


def test_history_excludes_in_progress_and_other_users_games_api(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    answer(app, client, gid)
    assert b"No saved games" in client.get("/history").data
    bob = second_user(app)
    assert bob.get(f"/api/games/{gid}/state").status_code == 404
    assert api(bob, gid, "finish").status_code == 404
    assert api(bob, gid, "exit").status_code == 404
    assert bob.get(f"/quiz/{gid}").status_code == 404


def test_leaderboard_ranking_tiebreak_filters_and_privacy(app, client, user, fake_clock):
    bob = second_user(app)
    # now = 2026-03-10 06:00 UTC (Tuesday, 11:30 IST)
    saved_game(app, 1, score=50, elapsed=100, finished=datetime(2026, 3, 10, 2, 0))   # today
    saved_game(app, 2, score=50, elapsed=90, finished=datetime(2026, 3, 9, 20, 0))    # today (IST)
    saved_game(app, 1, "daily", score=80, elapsed=300, finished=datetime(2026, 3, 8, 12, 0))  # last week
    saved_game(app, 2, score=500, elapsed=50, finished=datetime(2026, 2, 20, 12, 0))  # last month
    import re

    def rows(range_):
        html = client.get(f"/leaderboard?range={range_}").get_data(as_text=True)
        return re.findall(r"<tr[^>]*>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(\w+)</td>\s*<td[^>]*>([^<]+)</td>"
                          r"\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(\d+)</td>", html)

    today = rows("today")
    assert [(r[0], r[1]) for r in today] == [("1", "bob"), ("2", "alice")]  # equal score -> lower time wins
    week = rows("week")
    assert len(week) == 2 and week[0][3] == "1"
    month = rows("month")
    assert {r[2] for r in month} == {"Math", "Daily Quiz"}
    allt = rows("all")
    assert allt[0][1] == "bob" and allt[0][4] == "550" and allt[0][3] == "2"
    assert client.get("/leaderboard?range=yesterday").status_code == 400
    html = client.get("/leaderboard").get_data(as_text=True)
    assert "alice@example.com" not in html and "password" not in html.lower().replace("passwords", "")
    for col in ["Rank", "Username", "Quiz Type", "Games Played", "Total Score", "Total Time"]:
        assert col in html


def test_leaderboard_pagination_and_rank_offset(app, client, user, fake_clock):
    cats = list(range(1, 4))
    for i in range(25):
        saved_game(app, 1, category="Math", score=1000 - i, finished=datetime(2026, 3, 10, 2, 0, i))
        # distinct users to create distinct rows
    s = app.extensions["db_sessionmaker"]()
    for i in range(25):
        u = User(full_name=f"U {i}", email=f"u{i}@x.com", username=f"user{i:02d}", username_lower=f"user{i:02d}",
                 gender="Other", password_hash="x")
        s.add(u)
        s.flush()
        s.add(QuizGame(user_id=u.id, quiz_type="all", status="completed", question_ids=[1], seq_positions=[0],
                       score=2000 - i, elapsed_seconds=10, started_at=datetime(2026, 3, 10), finished_at=datetime(2026, 3, 10, 3, 0)))
    s.commit()
    s.close()
    p2 = client.get("/leaderboard?page=2").get_data(as_text=True)
    assert "Page 2 of 2" in p2 and "<td data-label=\"Rank\">21</td>" in p2


def test_profile_stats_are_category_quiz_only(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    play_through(app, client, gid, 3, correct=True)
    api(client, gid, "finish")
    g2 = start(client, "all")
    play_through(app, client, g2, 2, correct=True)
    api(client, g2, "finish")
    html = client.get("/profile").get_data(as_text=True)
    assert "Alice Smith" in html and "alice@example.com" in html and "Female" in html
    assert "Clear All Data" in html
    import re
    vals = re.findall(r'<span class="stat-label">([^<]+)</span><strong>([^<]+)</strong>', html)
    d = dict(vals)
    assert d["Games played"] == "1" and d["Questions answered"] == "3" and d["Total score"] == "30"
    home = dict(re.findall(r'<span class="stat-label">([^<]+)</span><strong>([^<]+)</strong>', client.get("/").get_data(as_text=True)))
    assert home["Total questions answered"] == "5" and home["Last category played"] == "Math"


def test_home_stats_use_only_own_data(app, client, user):
    bob = second_user(app)
    add_questions(app, "Cricket", 10)
    g = start(bob, "category", cat_id(app, "Cricket"))
    play_through(app, bob, g, 3)
    api(bob, g, "finish")
    html = client.get("/").get_data(as_text=True)
    assert "Cricket" not in html and "Welcome, Alice Smith!" in html


def test_clear_all_data_scopes_to_current_user(app, client, user, db):
    bob = second_user(app)
    add_questions(app, "Math", 10)
    for c in (client, bob):
        g = start(c, "category", cat_id(app, "Math"))
        play_through(app, c, g, 2)
        api(c, g, "finish")
        g = start(c, "category", cat_id(app, "Math"))
        a = answer(app, c, g)
        c.post(f"/api/games/{g}/bookmark", json={"question_id": a.get_json()["state"]["question"]["id"]})
    questions_before = db.query(Question).count()
    assert client.post("/profile/clear-data", data={"confirm": "nope"}).status_code == 302
    assert db.query(QuizGame).filter_by(user_id=1).count() == 2  # wrong confirmation: nothing deleted
    client.post("/profile/clear-data", data={"confirm": "DELETE"})
    db.expire_all()
    assert db.query(QuizGame).filter_by(user_id=1).count() == 0
    assert db.query(QuizGameAnswer).join(QuizGame).filter(QuizGame.user_id == 1).count() == 0
    assert db.query(UserCategoryProgress).filter_by(user_id=1).count() == 0
    assert db.query(Bookmark).filter_by(user_id=1).count() == 0
    # other user and shared data untouched; account kept
    assert db.query(QuizGame).filter_by(user_id=2).count() == 2
    assert db.query(UserCategoryProgress).filter_by(user_id=2).count() == 1
    assert db.query(Bookmark).filter_by(user_id=2).count() == 1
    assert db.query(Question).count() == questions_before and db.query(Category).count() == 56
    u = db.get(User, 1)
    assert u.email == "alice@example.com" and u.password_hash and u.gender == "Female"
    assert db.get(UserPreference, 1) is not None
    assert client.get("/profile").status_code == 200  # still logged in
    # progress restarted from the beginning
    g = start(client, "category", cat_id(app, "Math"))
    assert db.get(QuizGame, g).start_pointer == 0


def test_bookmarks_only_for_resolved_questions(app, client, user):
    add_questions(app, "Math", 10)
    g = start(client, "category", cat_id(app, "Math"))
    qid = state(client, g)["question"]["id"]
    assert client.post(f"/api/games/{g}/bookmark", json={"question_id": qid}).status_code == 409
    answer(app, client, g)
    assert client.post(f"/api/games/{g}/bookmark", json={"question_id": qid}).get_json()["bookmarked"] is True
    assert b'class="card bookmark"' in client.get("/bookmarks").data
    client.post(f"/bookmarks/{qid}/remove")
    assert b"No bookmarked questions" in client.get("/bookmarks").data


def test_other_pages_render_and_feedback(app, client, user):
    for path in ["/performance", "/achievements", "/all-quiz", "/feedback"]:
        assert client.get(path).status_code == 200
    r = client.post("/feedback", data={"message": "ab"})
    assert r.status_code == 400
    assert client.post("/feedback", data={"message": "Great quiz app!", "rating": "5"}).status_code == 302


def test_persistence_after_simulated_restart(tmp_path):
    app1 = make_app(tmp_path)
    c1 = app1.test_client()
    register(c1)
    login(c1)
    add_questions(app1, "Math", 10)
    cid = cat_id(app1, "Math")
    g = start(c1, "category", cid)
    play_through(app1, c1, g, 3)
    api(c1, g, "finish")
    g_all = start(c1, "all")
    answer(app1, c1, g_all)
    before_q = app1.extensions["db_sessionmaker"]().query(Question).count()
    # "restart": new application instance on the same database
    app2 = make_app(tmp_path)
    c2 = app2.test_client()
    assert login(c2).status_code == 302
    s = app2.extensions["db_sessionmaker"]()
    assert s.get(UserCategoryProgress, (1, cid)).pointer == 3
    assert s.query(Question).count() == before_q  # seeding is idempotent
    assert s.query(Category).count() == 56
    assert start(c2, "all") == g_all and state(c2, g_all)["resolved_count"] == 1  # in-progress state restored
    assert s.query(QuizGame).filter_by(status="completed").count() == 1
