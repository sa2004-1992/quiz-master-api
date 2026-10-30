from datetime import datetime

from sqlalchemy import select

from app.models import (Bookmark, Category, PlayAllProgress, Question, QuizGame, QuizGameAnswer, User,
                        UserCategoryProgress, UserPreference)
from tests.conftest import (add_questions, api, answer, cat_id, login, make_app, play_through, register,
                            start, state)


def saved_game(app, user_id, quiz_type="category", category="Math", score=50, elapsed=100,
               finished=datetime(2026, 3, 10, 2, 0), difficulty="Easy", answered=5, correct=None):
    s = app.extensions["db_sessionmaker"]()
    try:
        g = QuizGame(user_id=user_id, quiz_type=quiz_type,
                     category_id=cat_id(app, category) if quiz_type == "category" else None,
                     status="completed", active_key=None, question_ids=[1], seq_positions=[0],
                     resolved_count=answered, answered_count=answered,
                     correct_count=answered if correct is None else correct,
                     wrong_count=answered - (answered if correct is None else correct), score=score, elapsed_seconds=elapsed,
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
    table = first[first.index("<tbody>"):]
    assert table.index("Daily Quiz") < table.index("Math")  # newest first
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


def _lb_rows(client, query=""):
    import re
    from html import unescape
    html = client.get("/leaderboard" + query).get_data(as_text=True)
    rows = []
    for tr in re.findall(r"<tr class=[^>]*>(.*?)</tr>", html, flags=re.S):
        cells = [unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
        cells[1] = re.search(r'class="lb-name">([^<]+)<', tr).group(1)  # username only (no avatar initial / crown)
        rows.append(cells)
    return rows


def test_leaderboard_one_combined_row_per_user_across_all_modes(app, client, user, fake_clock):
    bob = second_user(app)
    # alice: 3 Quiz 1 + 2 All Quiz + 1 Daily = 6 games; bob: nothing
    for _ in range(3):
        saved_game(app, 1, "category", "Math", score=10, elapsed=10, answered=2, correct=1)
    for _ in range(2):
        saved_game(app, 1, "all", score=20, elapsed=20, answered=3, correct=2)
    saved_game(app, 1, "daily", score=30, elapsed=30, answered=4, correct=3)
    rows = _lb_rows(client)
    assert len(rows) == 1  # ONE row for the user, not one per mode or per game
    rank, name, score, answered, games, time = rows[0]
    assert (name, score, answered, games, time) == ("alice", "100", "16", "6", "1m 40s")
    assert rank == "\U0001F947"


def test_leaderboard_each_mode_alone_appears(app, client, user, fake_clock):
    carol, dave = second_user(app, "carol"), second_user(app, "dave")
    saved_game(app, 1, "category", "Math", score=11)
    saved_game(app, 2, "all", score=22)
    saved_game(app, 3, "daily", score=33)
    names = {r[1]: r[2] for r in _lb_rows(client)}
    assert names == {"alice": "11", "carol": "22", "dave": "33"}


def test_leaderboard_total_players_counts_registered_users_once(app, client, user, fake_clock):
    second_user(app, "bob"), second_user(app, "carol")
    saved_game(app, 1, score=5)
    saved_game(app, 1, "daily", score=5)
    html = client.get("/leaderboard").get_data(as_text=True)
    import re
    assert re.search(r"Total Players</span><strong>3</strong>", html)  # registered users, not ranked rows
    assert "Showing 1 to 1 of 1 player" in html


def test_leaderboard_columns_order_headings_and_medals(app, client, user, fake_clock):
    for i, name in enumerate(["bob", "carol", "dave"]):
        second_user(app, name)
    for uid, score in [(1, 50), (2, 400), (3, 300), (4, 200)]:
        saved_game(app, uid, score=score)
    html = client.get("/leaderboard").get_data(as_text=True)
    assert "&#127942; Leaderboard" in html and "See how you rank against other players." in html
    heads = ["Rank", "Player User Name", "Total Score", "Total Questions Played", "Total Games Played", "Total Time Spent"]
    pos = [html.index(f"<th>{h}</th>") for h in heads]
    assert pos == sorted(pos)
    for ticker in ["All Time", "This Month", "This Week", "Today"]:
        assert ticker in html
    rows = _lb_rows(client)
    assert [r[0] for r in rows] == ["\U0001F947", "\U0001F948", "\U0001F949", "4"]
    assert [r[1] for r in rows] == ["bob", "carol", "dave", "alice"]
    assert html.count("&#128081;") == 1 and 'class="gold' in html and 'class="silver' in html and 'class="bronze' in html
    assert "Your rank: <strong>#4</strong> of 4 players" in html
    assert html.count(" me\"") == 1  # exactly one highlighted row: the current user


def test_leaderboard_tie_breaks(app, client, user, fake_clock):
    for n in ["bob", "carol", "dave", "erin"]:
        second_user(app, n)
    saved_game(app, 1, score=100, answered=10, correct=6, elapsed=50)   # alice
    saved_game(app, 2, score=100, answered=10, correct=8, elapsed=90)   # bob: more correct -> ahead
    saved_game(app, 3, score=100, answered=12, correct=6, elapsed=90)   # carol: same correct as alice, more played
    saved_game(app, 4, score=100, answered=10, correct=6, elapsed=40)   # dave: same as alice but faster
    saved_game(app, 5, score=100, answered=10, correct=6, elapsed=50)   # erin: identical to alice -> username
    order = [r[1] for r in _lb_rows(client)]
    assert order == ["bob", "carol", "dave", "alice", "erin"]


def test_leaderboard_filters_and_boundaries(app, client, user, fake_clock):
    bob = second_user(app)
    # now = 2026-03-10 06:00 UTC (Tuesday, 11:30 IST)
    saved_game(app, 1, score=50, finished=datetime(2026, 3, 10, 2, 0))           # today
    saved_game(app, 2, "daily", score=60, finished=datetime(2026, 3, 9, 20, 0))  # today in IST (01:30 on the 10th)
    saved_game(app, 1, "all", score=80, finished=datetime(2026, 3, 9, 12, 0))    # this week (Monday 9th IST), not today
    saved_game(app, 2, score=500, finished=datetime(2026, 3, 8, 12, 0))          # last week, this month
    saved_game(app, 2, score=900, finished=datetime(2026, 2, 20, 12, 0))         # last month
    def totals(q):
        return {r[1]: (r[2], r[4]) for r in _lb_rows(client, q)}
    assert totals("?range=today") == {"alice": ("50", "1"), "bob": ("60", "1")}
    assert totals("?range=week") == {"alice": ("130", "2"), "bob": ("60", "1")}
    assert totals("?range=month") == {"alice": ("130", "2"), "bob": ("560", "2")}
    assert totals("?range=all") == {"alice": ("130", "2"), "bob": ("1,460", "3")}
    assert client.get("/leaderboard?range=yesterday").status_code == 400
    assert client.get("/leaderboard?range=today&page=7").status_code == 200  # clamped


def test_saving_a_game_updates_the_combined_leaderboard(app, client, user, fake_clock):
    add_questions(app, "Math", 10)
    assert "No results for this period yet." in client.get("/leaderboard").get_data(as_text=True)
    g = start(client, "category", cat_id(app, "Math"))
    play_through(app, client, g, 3)
    assert "No results for this period yet." in client.get("/leaderboard").get_data(as_text=True)  # unsaved: not counted
    fake_clock.advance(seconds=40)
    api(client, g, "finish")
    assert _lb_rows(client)[0][2:] == ["30", "3", "1", "40s"]
    g2 = start(client, "all")
    answer(app, client, g2, correct=True)
    fake_clock.advance(seconds=20)
    api(client, g2, "finish")
    assert _lb_rows(client)[0][2:] == ["40", "4", "2", "1m 0s"]
    g3 = start(client, "daily")
    play_through(app, client, g3, 4)
    fake_clock.advance(seconds=5)
    api(client, g3, "finish")
    row = _lb_rows(client)[0]
    assert row[2:] == ["80", "8", "3", "1m 5s"] and len(_lb_rows(client)) == 1
    api(client, g3, "finish")  # a retried save never counts twice
    assert _lb_rows(client)[0][2:] == ["80", "8", "3", "1m 5s"]


def test_unsaved_and_other_users_unfinished_games_excluded(app, client, user, fake_clock):
    bob = second_user(app)
    add_questions(app, "Math", 10)
    g = start(bob, "category", cat_id(app, "Math"))
    answer(app, bob, g)  # bob never saves
    saved_game(app, 1, score=7)
    rows = _lb_rows(client)
    assert len(rows) == 1 and rows[0][2] == "7"


def test_leaderboard_pagination_ranks_and_footer(app, client, user, fake_clock):
    s = app.extensions["db_sessionmaker"]()
    for i in range(25):
        u = User(full_name=f"Private Name {i}", email=f"secret{i}@private.example", username=f"user{i:02d}",
                 username_lower=f"user{i:02d}", gender="Other", password_hash="x")
        s.add(u)
        s.flush()
        s.add(QuizGame(user_id=u.id, quiz_type=("all", "daily", "category")[i % 3], category_id=1 if i % 3 == 2 else None,
                       status="completed", question_ids=[1], seq_positions=[0], score=2000 - i, answered_count=1,
                       correct_count=1, elapsed_seconds=10, started_at=datetime(2026, 3, 10), finished_at=datetime(2026, 3, 10, 3, 0)))
    s.commit()
    s.close()
    html = client.get("/leaderboard").get_data(as_text=True)
    assert len(_lb_rows(client)) == 20 and "Showing 1 to 20 of 25 players" in html
    p2 = client.get("/leaderboard?page=2").get_data(as_text=True)
    assert len(_lb_rows(client, "?page=2")) == 5 and "Showing 21 to 25 of 25 players" in p2
    assert _lb_rows(client, "?page=2")[0][0] == "21"
    assert "secret" not in html + p2 and "Private Name" not in html + p2 and "private.example" not in p2  # public data only
    assert 'href="/leaderboard?range=all&amp;page=2"' in html or "page=2" in html


def _play_three_modes(app, client, fake_clock):
    add_questions(app, "Math", 10)
    # Category Quiz: 3 correct, 1 wrong -> score 25, 100 s
    g1 = start(client, "category", cat_id(app, "Math"))
    play_through(app, client, g1, 3, correct=True)
    api(client, g1, "next")
    answer(app, client, g1, correct=False)
    fake_clock.advance(seconds=100)
    api(client, g1, "finish")
    # All Quiz: pos0 wrong, pos1-4 correct, pos5 hint -> score 40, 300 s (+ a 500 s pause that must not count)
    g2 = start(client, "all")
    answer(app, client, g2, correct=False)
    for _ in range(4):
        api(client, g2, "next")
        answer(app, client, g2, correct=True)
    api(client, g2, "next")
    api(client, g2, "hint", question_id=state(client, g2)["question"]["id"])
    fake_clock.advance(seconds=300)
    api(client, g2, "pause")
    fake_clock.advance(seconds=500)
    api(client, g2, "finish")
    # Daily Quiz: 4 correct -> score 40, 50 s
    g3 = start(client, "daily")
    play_through(app, client, g3, 4, correct=True)
    fake_clock.advance(seconds=50)
    api(client, g3, "finish")


def test_profile_overview_is_quiz1_only(app, client, user, fake_clock, db):
    from app.services import reports
    _play_three_modes(app, client, fake_clock)
    o = reports.profile_overview(db, 1)  # Category Quiz games only: All Quiz and Daily are never mixed in
    assert o["stats"] == {"games": 1, "correct": 3, "wrong": 1, "score": 25, "answered": 4, "time": 100}
    p = o["performance"]
    assert p["accuracy"] == p["correct_rate"] == 75.0 and p["wrong_rate"] == 25.0
    assert p["avg_time"] == 100 and p["avg_score"] == 25.0 and p["avg_questions"] == 4.0
    r = o["records"]
    assert r["score"] == (25, "Math") and r["answered"] == (4, "Math") and r["time"] == (100, "Math")
    by = {c["name"]: c for c in o["played"] + o["unplayed"]}
    assert len(by) == 56
    assert (by["Math"]["questions"], by["Math"]["correct"], by["Math"]["wrong"], by["Math"]["best"]) == (4, 3, 1, 25)
    assert sum(c["questions"] for c in by.values()) == 4  # the 9 All Quiz / Daily answers are not here
    assert by["History"]["played"] is False and by["Kannada"]["played"] is False


def test_profile_page_renders_sections_and_all_categories(app, client, user, fake_clock):
    import re
    from html import unescape
    from app.categories import CATEGORY_NAMES
    html = client.get("/profile").get_data(as_text=True)
    assert "No records yet" in html
    assert "Total Games Played" in html and "Clear All Data" in html and "alice@example.com" in html
    assert "0.0%" in html and "0s" in html  # safe empty state, no division errors
    _play_three_modes(app, client, fake_clock)
    html = client.get("/profile").get_data(as_text=True)
    for label in ["Quiz Statistics", "Overall Performance", "Personal Records (In One Game)", "Category Performance",
                  "Total Correct Answers", "Total Wrong Answers", "Total Time Spent", "Highest Time Spent",
                  "Average Time per Game", "Wrong Answer Rate", "same measure"]:
        assert label in html, label
    assert "1m 40s" in html and "Mixed Categories" not in html
    names = [unescape(n) for n in re.findall(r'</span>([^<]+)</h4>', html)]
    assert sorted(names) == sorted(CATEGORY_NAMES)
    for key in ["questions", "name", "accuracy", "best", "bogus"]:
        assert client.get(f"/profile?sort={key}").status_code == 200


def test_profile_ignores_other_users_and_unsaved_games(app, client, user, fake_clock, db):
    from app.services import reports
    bob = second_user(app)
    _play_three_modes(app, bob, fake_clock)
    add_questions(app, "Math", 5, prefix="Z")
    g = start(client, "category", cat_id(app, "Math"))
    answer(app, client, g)  # unsaved game
    o = reports.profile_overview(db, 1)
    assert o["stats"]["games"] == 0 and o["records"] is None and len(o["unplayed"]) == 56


def test_human_duration_filter(app):
    f = app.jinja_env.filters["human_duration"]
    assert f(0) == "0s" and f(45) == "45s" and f(2720) == "45m 20s" and f(12 * 3600 + 35 * 60) == "12h 35m"


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


def test_profile_hero_shows_real_user_details(app, client, user, db):
    from html import unescape
    from app.models import User
    html = client.get("/profile").get_data(as_text=True)
    hero = html[html.index('class="profile-hero"'):html.index("Quiz Statistics")]
    assert ">A</div>" in hero  # first initial of "Alice Smith"
    assert "Alice Smith" in hero and "@alice" in hero and "alice@example.com" in hero
    assert "Joined on 10 Mar 2026" in hero or "Joined on" in hero
    assert "Female" in hero and "&#128105;" in hero
    assert "data-open-clear" in hero and "Clear All Data" in hero  # button lives in the hero, same hook as before
    assert "Country" not in hero  # no country is stored, so none is invented
    u = db.get(User, 1)
    u.full_name = "Zed <b>x</b>"
    db.commit()
    assert "<b>x</b>" not in client.get("/profile").get_data(as_text=True)  # escaped


def test_joined_date_uses_app_timezone(app, client, user, db, fake_clock):
    from datetime import datetime
    from app.models import User
    u = db.get(User, 1)
    u.created_at = datetime(2026, 10, 14, 20, 0)  # 01:30 on 15 Oct in Asia/Kolkata
    db.commit()
    assert "Joined on 15 Oct 2026" in client.get("/profile").get_data(as_text=True)


def test_category_cards_match_design_and_use_real_numbers(app, client, user, fake_clock):
    from app.categories import CATEGORY_EMOJI, CATEGORY_NAMES
    _play_three_modes(app, client, fake_clock)
    html = client.get("/profile?sort=name").get_data(as_text=True)
    assert html.count('class="card cat-card') == 56 and html.count('class="cat-progress"') == 56
    assert len(CATEGORY_EMOJI) == 56 and all(CATEGORY_EMOJI[n] for n in CATEGORY_NAMES)
    for label in ["Questions:", "Correct:", "Wrong:", "Accuracy:", "Best Score:"]:
        assert html.count(label) == 56
    math = html[html.index("</span>Math</h4>"):]
    math = math[:math.index("</article>")]
    assert "Accuracy:</dt><dd>" in math and "%</dd>" in math and 'value="' in math
    assert 'cat-card unplayed' in html  # unplayed categories remain visible, dimmed, with zero values


# ---------------------------------------------------------------- Quiz 2 (All Quiz) page
def test_all_quiz_overview_is_independent_of_other_modes(app, client, user, fake_clock, db):
    from app.services import reports
    _play_three_modes(app, client, fake_clock)
    o = reports.all_quiz_overview(db, 1)
    assert o["stats"] == {"games": 1, "correct": 4, "wrong": 1, "score": 40, "answered": 5, "time": 300}
    p = o["performance"]  # the hint-resolved 6th question is neither correct nor wrong
    assert p["accuracy"] == p["correct_rate"] == 80.0 and p["wrong_rate"] == 20.0
    assert (p["avg_time"], p["avg_score"], p["avg_questions"]) == (300, 40.0, 5.0)
    assert o["records"] == {"score": 40, "answered": 5, "correct": 4, "wrong": 1, "time": 300}


def test_all_quiz_records_come_from_single_games(app, client, user, fake_clock, db):
    from app.services import reports
    for correct_n, wrong_n, secs in [(5, 0, 100), (2, 3, 400), (3, 1, 60)]:
        g = start(client, "all")
        for i in range(correct_n + wrong_n):
            answer(app, client, g, correct=i < correct_n)
            if i < correct_n + wrong_n - 1:
                api(client, g, "next")
        fake_clock.advance(seconds=secs)
        api(client, g, "finish")
    o = reports.all_quiz_overview(db, 1)
    assert o["stats"]["games"] == 3 and o["stats"]["time"] == 560 and o["stats"]["answered"] == 14
    assert o["records"]["time"] == 400 and o["records"]["correct"] == 5 and o["records"]["wrong"] == 3
    assert o["records"]["answered"] == 5  # highest in ONE game, not the sum of games


def test_all_quiz_page_shows_only_quiz2_data(app, client, user, fake_clock):
    import re
    html = client.get("/all-quiz").get_data(as_text=True)
    assert "Complete quiz statistics and performance overview (Play All Quiz)." in html
    assert "No records yet" in html and "Not played yet" not in html
    _play_three_modes(app, client, fake_clock)
    html = client.get("/all-quiz").get_data(as_text=True)
    from html import unescape
    stats = {unescape(k): v for k, v in re.findall(r'<span class="stat-label">([^<]+)</span><strong>([^<]+)</strong>', html)}
    assert stats["\U0001F3AE Total Games Played"] == "1" and stats["\u2753 Total Questions Played"] == "5"
    assert stats["\U0001F3C6 Total Score"] == "40" and stats["\u2705 Total Correct Answers"] == "4"
    assert stats["\u274C Total Wrong Answers"] == "1" and stats["\u23F1\uFE0F Total Time Spent"] == "5m 0s"
    for label in ["Highest Score in One Game", "Highest Questions Played in One Game",
                  "Highest Correct Answers in One Game", "Highest Wrong Answers in One Game",
                  "Highest Time Spent in One Game", "Overall Accuracy", "Wrong Answer Rate"]:
        assert label in html, label
    assert "Category Performance" not in html and "cat-card" not in html  # no Quiz 1 statistics here


def test_all_quiz_zero_state_has_no_errors(app, client, user):
    html = client.get("/all-quiz").get_data(as_text=True)
    assert "nan" not in html.lower().replace("finance", "") and "0.0%" in html and "0s" in html


def test_all_quiz_stats_ignore_other_users(app, client, user, fake_clock, db):
    from app.services import reports
    bob = second_user(app)
    _play_three_modes(app, bob, fake_clock)
    assert reports.all_quiz_overview(db, 1)["stats"]["games"] == 0
    assert reports.all_quiz_overview(db, 2)["stats"]["games"] == 1


def test_unfinished_all_quiz_not_counted_and_updates_after_save(app, client, user, fake_clock, db):
    from app.services import reports
    g = start(client, "all")
    answer(app, client, g)
    assert reports.all_quiz_overview(db, 1)["stats"]["games"] == 0
    api(client, g, "finish")
    db.expire_all()
    assert reports.all_quiz_overview(db, 1)["stats"]["games"] == 1


def test_game_record_stores_per_game_counts(app, client, user, fake_clock, db):
    _play_three_modes(app, client, fake_clock)
    g = db.query(QuizGame).filter_by(quiz_type="all").one()  # quiz_type 'all' is the play_all mode
    assert (g.user_id, g.answered_count, g.correct_count, g.wrong_count, g.score, g.elapsed_seconds) == (1, 5, 4, 1, 40, 300)
    assert g.finished_at is not None and g.status == "completed"


def test_clear_all_quiz_data_only_clears_quiz2(app, client, user, fake_clock, db):
    bob = second_user(app)
    _play_three_modes(app, client, fake_clock)
    g = start(bob, "all")
    answer(app, bob, g)
    api(bob, g, "finish")
    assert client.post("/all-quiz/clear-data", data={"confirm": "no"}).status_code == 302
    assert db.query(QuizGame).filter_by(user_id=1, quiz_type="all").count() == 1  # wrong confirmation: kept
    client.post("/all-quiz/clear-data", data={"confirm": "DELETE"})
    db.expire_all()
    assert db.query(QuizGame).filter_by(user_id=1, quiz_type="all").count() == 0
    assert db.get(PlayAllProgress, 1) is None
    assert db.query(QuizGame).filter_by(user_id=1, quiz_type="category").count() == 1   # Quiz 1 kept
    assert db.query(QuizGame).filter_by(user_id=1, quiz_type="daily").count() == 1      # Daily kept
    assert db.query(UserCategoryProgress).filter_by(user_id=1).count() == 1
    assert db.query(QuizGame).filter_by(user_id=2, quiz_type="all").count() == 1        # other users kept
    assert db.get(PlayAllProgress, 2) is not None and db.get(User, 1).email == "alice@example.com"
    assert "Total Games Played" in client.get("/all-quiz").get_data(as_text=True)
    g2 = start(client, "all")
    assert db.get(QuizGame, g2).start_pointer == 0  # progress reset


def test_upgrade_adds_columns_and_backfills_old_database(tmp_path):
    import sqlite3
    from app import create_app
    from tests.conftest import BASE_CFG
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE quiz_games (id INTEGER PRIMARY KEY, user_id INTEGER, quiz_type VARCHAR(10), status VARCHAR(12),
        correct_count INTEGER, resolved_count INTEGER, score INTEGER);
      CREATE TABLE quiz_game_answers (id INTEGER PRIMARY KEY, game_id INTEGER, question_id INTEGER, position INTEGER,
        selected_option VARCHAR(1), is_correct BOOLEAN, hint_used BOOLEAN, points INTEGER);
      INSERT INTO quiz_games VALUES (1, 1, 'all', 'completed', 2, 4, 15);
      INSERT INTO quiz_game_answers VALUES (1,1,1,0,'A',1,0,10),(2,1,2,1,'B',1,0,10),(3,1,3,2,'C',0,0,-5),(4,1,4,3,NULL,0,1,0);
    """)
    con.commit()
    con.close()
    create_app(dict(BASE_CFG, DATABASE_URL=f"sqlite:///{path}"))
    con = sqlite3.connect(path)
    assert con.execute("SELECT answered_count, wrong_count FROM quiz_games WHERE id=1").fetchone() == (3, 1)
    con.close()
    create_app(dict(BASE_CFG, DATABASE_URL=f"sqlite:///{path}"))  # second start: idempotent


# ---------------------------------------------------------------- History search + filters
def _history_rows(html):
    import re
    from html import unescape
    return [(unescape(a), unescape(b)) for a, b in re.findall(
        r'<td data-label="Game">([^<]+)</td><td data-label="Category Name">([^<]+)</td>', html)]


def _seed_history(app):
    saved_game(app, 1, category="Cricket", finished=datetime(2026, 3, 10, 2, 0))            # 10 Mar IST
    saved_game(app, 1, category="Math", finished=datetime(2026, 3, 5, 12, 0))                # 5 Mar
    saved_game(app, 1, "all", finished=datetime(2026, 3, 8, 12, 0))                          # 8 Mar
    saved_game(app, 1, "daily", finished=datetime(2026, 3, 9, 12, 0))                        # 9 Mar
    saved_game(app, 1, category="Cricket", finished=datetime(2026, 2, 1, 12, 0))             # 1 Feb


def test_history_heading_and_filter_bar_order(app, client, user):
    html = client.get("/history").get_data(as_text=True)
    assert "&#128344; History" in html and "View all your previously played quiz games." in html
    order = [html.index(x) for x in ['placeholder="Search by game or category..."', 'name="category"',
                                      'name="start"', 'name="end"', ">Filter</button>"]]
    assert order == sorted(order)
    assert html.index("Filter</button>") < html.index("No saved games yet")  # filter bar sits above the content
    from app.categories import CATEGORY_NAMES
    from html import unescape
    import re
    opts = [unescape(o) for o in re.findall(r"<option[^>]*>([^<]+)</option>", html[html.index('id="hcat"'):html.index("</select>")])]
    assert opts == ["All Categories"] + CATEGORY_NAMES


def test_history_unfiltered_content_unchanged(app, client, user):
    _seed_history(app)
    html = client.get("/history").get_data(as_text=True)
    assert [r[0] for r in _history_rows(html)] == ["Category Quiz", "Daily Quiz", "All Quiz", "Category Quiz", "Category Quiz"]
    for col in ["Date", "Game", "Category Name", "Difficulty", "Time", "Score"]:
        assert f"<th>{col}</th>" in html or f'<th class="num">{col}</th>' in html
    assert "Clear filters" not in html


def test_history_search_by_game_and_category(app, client, user):
    _seed_history(app)
    assert _history_rows(client.get("/history?q=cric").get_data(as_text=True)) == [("Category Quiz", "Cricket")] * 2
    assert _history_rows(client.get("/history?q=daily").get_data(as_text=True)) == [("Daily Quiz", "Daily Quiz")]
    assert _history_rows(client.get("/history?q=ALL QUIZ").get_data(as_text=True)) == [("All Quiz", "All Quiz")]
    assert len(_history_rows(client.get("/history?q=quiz").get_data(as_text=True))) == 5  # every game label contains "quiz"
    assert "No quiz history found." in client.get("/history?q=zzzz").get_data(as_text=True)
    # '%' is matched literally, not as a wildcard
    assert _history_rows(client.get("/history?q=%25").get_data(as_text=True)) == []


def test_history_category_and_date_filters_combine(app, client, user):
    _seed_history(app)
    cricket = cat_id(app, "Cricket")
    assert len(_history_rows(client.get(f"/history?category={cricket}").get_data(as_text=True))) == 2
    r = client.get(f"/history?category={cricket}&start=2026-03-01&end=2026-03-31").get_data(as_text=True)
    assert _history_rows(r) == [("Category Quiz", "Cricket")] and "Clear filters" in r
    inclusive = client.get("/history?start=2026-03-10&end=2026-03-10").get_data(as_text=True)  # IST day boundaries
    assert _history_rows(inclusive) == [("Category Quiz", "Cricket")]
    assert len(_history_rows(client.get("/history?start=2026-03-08").get_data(as_text=True))) == 3
    assert len(_history_rows(client.get("/history?end=2026-03-05").get_data(as_text=True))) == 2
    both = client.get("/history?q=cricket&start=2026-03-01").get_data(as_text=True)
    assert _history_rows(both) == [("Category Quiz", "Cricket")]
    none = client.get(f"/history?category={cat_id(app, 'Math')}&start=2026-03-06").get_data(as_text=True)
    assert "No quiz history found." in none


def test_history_date_validation_messages(app, client, user):
    _seed_history(app)
    r = client.get("/history?start=2026-03-20&end=2026-03-01").get_data(as_text=True)
    assert "Start date must be on or before the end date." in r and len(_history_rows(r)) == 5
    r = client.get("/history?start=not-a-date").get_data(as_text=True)
    assert "Start date is not a valid date." in r and client.get("/history?category=abc").status_code == 200
    assert "Please choose a valid category." in client.get("/history?category=99999").get_data(as_text=True)
    assert client.get("/history?q=" + "x" * 500).status_code == 200


def test_history_filters_stay_in_own_data_and_pagination_keeps_them(app, client, user):
    for i in range(25):
        saved_game(app, 1, category="Cricket", finished=datetime(2026, 3, 1, 2, 0, i))
    bob = second_user(app)
    saved_game(app, 2, category="Cricket", score=777)
    html = client.get("/history?q=cricket").get_data(as_text=True)
    assert "777" not in html and len(_history_rows(html)) == 20 and "Page 1 of 2" in html
    assert "page=2" in html and "q=cricket" in html  # next link keeps the search
    p2 = client.get("/history?q=cricket&page=2").get_data(as_text=True)
    assert len(_history_rows(p2)) == 5
    assert "777" in bob.get("/history?q=cricket").get_data(as_text=True)


def test_history_requires_login_with_filters(client):
    assert client.get("/history?q=x").status_code == 302


# ---------------------------------------------------------------- My Performance
def _perf_games(app):
    saved_game(app, 1, "category", "Math", score=30, elapsed=100, answered=4, correct=3, finished=datetime(2026, 3, 1, 3, 0))
    saved_game(app, 1, "category", "Cricket", score=10, elapsed=50, answered=2, correct=1, finished=datetime(2026, 3, 2, 3, 0))
    saved_game(app, 1, "all", score=40, elapsed=300, answered=5, correct=4, finished=datetime(2026, 3, 3, 3, 0))
    saved_game(app, 1, "daily", score=20, elapsed=60, answered=4, correct=2, finished=datetime(2026, 3, 4, 3, 0))


def test_performance_combined_and_by_type_numbers(app, client, user, db):
    from app.services import reports
    _perf_games(app)
    with app.app_context():
        d = reports.performance(db, 1)
    o = d["overall"]
    assert (o["games"], o["score"], o["best_game"], o["best_time"]) == (4, 100, 40, 50)
    assert (o["answered"], o["correct"], o["wrong"], o["accuracy"]) == (15, 10, 5, 66.7)  # 10 / 15
    cat, allq, daily = d["by_type"]
    assert [b["label"] for b in d["by_type"]] == ["Category Quizzes", "All Quiz", "Daily Quiz"]
    assert (cat["games"], cat["answered"], cat["correct"], cat["wrong"], cat["accuracy"], cat["score"], cat["time"]) == (2, 6, 4, 2, 66.7, 40, 150)
    assert (allq["games"], allq["answered"], allq["correct"], allq["wrong"], allq["accuracy"], allq["score"], allq["time"]) == (1, 5, 4, 1, 80.0, 40, 300)
    assert (daily["games"], daily["answered"], daily["correct"], daily["wrong"], daily["accuracy"], daily["score"], daily["time"]) == (1, 4, 2, 2, 50.0, 20, 60)
    for key in ("games", "answered", "correct", "wrong", "score", "time"):  # modes add up to the combined totals
        assert sum(b[key] for b in d["by_type"]) == o[key if key != "games" else "games"]


def test_performance_zero_state_and_unplayed_mode(app, client, user, db):
    from app.services import reports
    with app.app_context():
        d = reports.performance(db, 1)
    assert d["overall"] == {"games": 0, "answered": 0, "correct": 0, "wrong": 0, "accuracy": 0.0, "score": 0,
                            "time": 0, "best_game": 0, "best_time": 0}
    assert all(b["games"] == 0 and b["accuracy"] == 0.0 and b["time"] == 0 for b in d["by_type"]) and d["chart"] == []
    html = client.get("/performance").get_data(as_text=True)
    assert "nan" not in html.lower().replace("finance", "") and "0.0%" in html
    saved_game(app, 1, "category", "Math", score=10, answered=2, correct=2)
    with app.app_context():
        by = {b["label"]: b for b in reports.performance(db, 1)["by_type"]}
    assert by["All Quiz"]["games"] == 0 and by["Daily Quiz"]["score"] == 0 and by["Category Quizzes"]["games"] == 1


def test_performance_page_structure_and_hidden_chart(app, client, user):
    _perf_games(app)
    html = client.get("/performance").get_data(as_text=True)
    assert "&#128202; My Performance" in html and 'href="/profile"' in html and "@alice" in html
    labels = ["Games Saved", "Total Score", "Best Game", "Best Time", "Accuracy"]
    pos = [html.index(l) for l in labels]
    assert pos == sorted(pos)
    heads = ["Quiz Type", "Games", "Answered", "Correct", "Wrong", "Accuracy", "Score", "Time"]
    import re
    ths = re.findall(r"<th[^>]*>([^<]+)</th>", html[html.index("perf-table"):])
    assert ths == heads
    rows = re.findall(r'<td data-label="Quiz Type">([^<]+)</td>', html)
    assert rows == ["Category Quizzes", "All Quiz", "Daily Quiz"]
    assert html.index("By Quiz Type") < html.index("Last 10 Game Scores") and "Bar Chart" in html and "Pie Chart" in html
    # no chart exists until the user chooses one: the area is hidden and empty, no <svg> rendered server-side
    assert 'id="chartArea" hidden' in html and "<svg class=\"chart-svg" not in html
    seg = html[html.index('class="seg"'):html.index('id="chartHint"')]
    assert seg.count('aria-pressed="false"') == 2 and 'aria-pressed="true"' not in seg  # neither type is selected
    assert "Select a chart type" in html
    assert "performance.js" in html


def test_performance_chart_data_is_last_10_of_this_user_oldest_first(app, client, user, db):
    import json, re
    from app.services import reports
    bob = second_user(app)
    saved_game(app, 2, score=999)  # another user's game must never appear
    for i in range(12):
        saved_game(app, 1, "category", "Math", score=i, finished=datetime(2026, 3, 1, 3, i))
    saved_game(app, 1, "daily", score=77, finished=datetime(2026, 3, 2, 3, 0))
    html = client.get("/performance").get_data(as_text=True)
    data = json.loads(re.search(r'id="perfChartData">(.*?)</script>', html, re.S).group(1))
    assert len(data) == 10 and [g["n"] for g in data] == list(range(1, 11))
    scores = [g["score"] for g in data]
    assert scores == [3, 4, 5, 6, 7, 8, 9, 10, 11, 77] and 999 not in scores
    assert data[-1]["quiz"] == "Daily Quiz" and data[0]["quiz"] == "Category Quiz \u2014 Math" and data[0]["date"]


def test_performance_updates_after_saving_and_ignores_unsaved(app, client, user, fake_clock):
    import re
    add_questions(app, "Math", 10)
    g = start(client, "category", cat_id(app, "Math"))
    play_through(app, client, g, 3)
    assert "<strong>0</strong>" in client.get("/performance").get_data(as_text=True)  # unsaved: nothing counted
    api(client, g, "finish")
    html = client.get("/performance").get_data(as_text=True)
    cards = dict(re.findall(r'<span class="stat-label">([^<]+)</span><strong>([^<]+)</strong>', html))
    assert any(v == "30" for v in cards.values()) and any(v == "100.0%" for v in cards.values())
    api(client, g, "finish")  # retry: not double counted
    assert "<strong>1</strong>" in client.get("/performance").get_data(as_text=True)


def test_performance_requires_login(client):
    assert client.get("/performance").status_code == 302


def test_chart_javascript_renders_bar_and_pie_correctly():
    import json, shutil, subprocess, textwrap
    if not shutil.which("node"):
        import pytest
        pytest.skip("node not available")
    script = textwrap.dedent("""
      const c = require('./app/static/js/performance.js');
      const g = (n, s, q) => ({n, score: s, quiz: q || 'Daily Quiz', date: '10 Mar 2026'});
      const ok = (cond, msg) => { if (!cond) { console.error('FAIL ' + msg); process.exit(1); } };
      const games = [g(1, 20), g(2, 20), g(3, 10), g(4, 0), g(5, 0, 'Category Quiz <b>x</b>')];
      const bar = c.bar(games);
      ok((bar.match(/class="chart-bar"/g) || []).length === 5, 'one bar per game');
      ok(bar.includes('>20<') && bar.includes('>0<'), 'actual score labels');
      ok(!bar.includes('<b>x</b>') && bar.includes('&lt;b&gt;x'), 'tooltip text escaped');
      ok(c.bar([g(1, 0)]).includes('chart-bar'), 'all-zero bar chart is safe');
      const pie = c.pie(games);
      ok((pie.match(/class="pie-seg"/g) || []).length === 3, 'only positive scores get segments');
      ok(pie.includes('#4 ') && pie.includes('#5 '), 'zero-score games still listed in the legend');
      ok(!pie.includes('style='), 'no inline styles (CSP)');
      ok(c.pie([g(1, 0), g(2, 0)]).includes('nothing to show'), 'all-zero pie shows a message');
      ok(c.pie([g(1, 0), g(2, 50)]).includes('<circle'), 'single positive segment is a full circle');
      ok(!/NaN|Infinity/.test(bar + pie + c.pie([g(1, 5)])), 'no NaN');
      const ten = Array.from({length: 10}, (_, i) => g(i + 1, i * 3));
      ok((c.bar(ten).match(/class="chart-bar"/g) || []).length === 10, 'ten bars');
      ok(c.bar([g(1, 5), g(2, 7)]).includes('chart-bar'), 'fewer than 10 games');
      console.log('chart js ok');
    """)
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=".")
    assert r.returncode == 0 and "chart js ok" in r.stdout, r.stderr
