import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import Category, Question, QuizGame
from app.services.question_validator import question_hash
from tests.conftest import add_questions, api, cat_id, start, state

Q_TEXT = ("A survey has results 80, 62, 29, 61 across four categories A, B, C, D respectively. "
          "What percentage of the total does Category D represent (rounded)?")
EXPL = ("Total = 80 + 62 + 29 + 61 = 232. Category D percentage = (61 \u00f7 232) \u00d7 100 = 26.29%, "
        "which rounds to 26%.")


def add_survey_question(app, category="Math"):
    s = app.extensions["db_sessionmaker"]()
    try:
        cat = s.scalars(select(Category).where(Category.name == category)).one()
        q = Question(pool="category", category_id=cat.id, question_text=Q_TEXT, option_a="31%", option_b="26%",
                     option_c="21%", option_d="36%", correct_answer="B", explanation=EXPL, difficulty="medium",
                     question_hash=question_hash(Q_TEXT + category), source="test")
        s.add(q)
        s.commit()
        return q.id
    finally:
        s.close()


def game_with_first_question(app, user_id, quiz_type, first_qid, other_qids):
    s = app.extensions["db_sessionmaker"]()
    try:
        cid = s.scalars(select(Category.id).where(Category.name == "Math")).one() if quiz_type == "category" else None
        ids = [first_qid] + other_qids
        g = QuizGame(user_id=user_id, quiz_type=quiz_type, category_id=cid, status="in_progress",
                     active_key={"category": f"cat:{cid}", "all": "all", "daily": "daily"}[quiz_type],
                     question_ids=ids, seq_positions=list(range(len(ids))), hints_max=10 if quiz_type != "daily" else 5)
        s.add(g)
        s.commit()
        return g.id
    finally:
        s.close()


def setup(app, client, quiz_type):
    first = add_survey_question(app)
    others = add_questions(app, "Math", 3, prefix="Other")
    return game_with_first_question(app, 1, quiz_type, first, others), first


MODES = [("category", "Category Quiz"), ("all", "All Quiz"), ("daily", "Daily Quiz")]


@pytest.mark.parametrize("mode,label", MODES)
def test_wrong_answer_reveals_correct_option_and_explanation_in_every_mode(app, client, user, mode, label):
    gid, qid = setup(app, client, mode)
    st = state(client, gid)
    assert st["quiz_label"] == label and st["question"]["category"] == "Math"
    assert "correct_answer" not in st["question"] and "explanation" not in st["question"]  # hidden until answered
    assert (st["correct"], st["wrong"], st["score"]) == (0, 0, 0)
    r = api(client, gid, "answer", question_id=qid, option="C")
    q = r.get_json()["state"]["question"]
    assert r.status_code == 200 and q["selected"] == "C" and q["correct_answer"] == "B" and q["is_correct"] is False
    assert q["explanation"] == EXPL
    after = r.get_json()["state"]
    assert (after["correct"], after["wrong"], after["score"]) == (0, 1, 0)  # -5 is floored at 0
    dup = api(client, gid, "answer", question_id=qid, option="B")           # cannot change the answer
    assert dup.status_code == 409
    again = state(client, gid)
    assert (again["correct"], again["wrong"]) == (0, 1) and again["question"]["selected"] == "C"


@pytest.mark.parametrize("mode,label", MODES)
def test_correct_answer_updates_counters_once(app, client, user, mode, label):
    gid, qid = setup(app, client, mode)
    s1 = api(client, gid, "answer", question_id=qid, option="B").get_json()["state"]
    assert s1["question"]["is_correct"] is True and (s1["correct"], s1["wrong"], s1["score"]) == (1, 0, 10)
    assert api(client, gid, "answer", question_id=qid, option="B").status_code == 409
    assert state(client, gid)["score"] == 10  # the score is never calculated twice
    api(client, gid, "next")
    nq = state(client, gid)["question"]
    assert nq["resolved"] is False and "correct_answer" not in nq and "explanation" not in nq  # next question stays hidden


def test_counters_with_hint_and_previous_question(app, client, user):
    gid, qid = setup(app, client, "category")
    api(client, gid, "answer", question_id=qid, option="A")                 # wrong
    api(client, gid, "next")
    q2 = state(client, gid)["question"]["id"]
    api(client, gid, "hint", question_id=q2)                                # hint: neither correct nor wrong
    api(client, gid, "next")
    q3 = state(client, gid)["question"]["id"]
    from tests.conftest import correct_letter
    api(client, gid, "answer", question_id=q3, option=correct_letter(app, q3))
    st = state(client, gid)
    assert (st["correct"], st["wrong"], st["score"]) == (1, 1, 10)
    api(client, gid, "previous")
    api(client, gid, "previous")
    first = state(client, gid)["question"]
    assert first["selected"] == "A" and first["correct_answer"] == "B" and first["explanation"] == EXPL  # feedback restored


def test_feedback_belongs_only_to_the_active_game(app, client, user):
    gid, qid = setup(app, client, "category")
    api(client, gid, "answer", question_id=qid, option="C")
    other_game = start(client, "all")                       # a different game of the same user
    st = state(client, other_game)
    assert st["quiz_type"] == "all" and st["question"]["id"] != qid and "explanation" not in st["question"]
    from tests.conftest import login, register
    bob = app.test_client()
    register(bob, "bob")
    login(bob, "bob")
    assert bob.get(f"/api/games/{gid}/state").status_code == 404            # nobody else can see this game's answers
    assert bob.post(f"/api/games/{gid}/answer", json={"question_id": qid, "option": "B"}).status_code == 404


def test_top_bar_has_all_counters_and_existing_items(client, user, app):
    gid, _ = setup(app, client, "category")
    html = client.get(f"/quiz/{gid}").get_data(as_text=True)
    for ident in ["qType", "qCategory", "qNumber", "qScore", "qTimer", "qHints", "qCorrect", "qWrong"]:
        assert f'id="{ident}"' in html, ident
    for label in ["Question", "Score", "Time", "Hints left", "Correct", "Wrong"]:
        assert f'<span class="stat-label">{label}</span>' in html
    for btn in ["prevBtn", "hintBtn", "pauseBtn", "nextBtn", "exitBtn", "finishBtn"]:
        assert f'id="{btn}"' in html


# ------------------------------------------------------------ the real JavaScript, run in a DOM (jsdom)
def _jsdom_available(env):
    node = shutil.which("node")
    return bool(node) and subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, env=env).returncode == 0


@pytest.mark.parametrize("mode,label", MODES)
@pytest.mark.parametrize("click,outcome,counters", [("C", "wrong", (0, 1, 0)), ("B", "correct", (1, 0, 10))])
def test_quiz_page_javascript_shows_correct_and_wrong_feedback(app, client, user, tmp_path, mode, label, click, outcome, counters):
    env = dict(os.environ)
    if not _jsdom_available(env):
        pytest.skip("node + jsdom not available (npm install jsdom; set NODE_PATH to its node_modules)")
    gid, qid = setup(app, client, mode)
    html = client.get(f"/quiz/{gid}").get_data(as_text=True)
    state0 = api(client, gid, "state").get_json()
    answered = api(client, gid, "answer", question_id=qid, option=click).get_json()  # the real server response
    fixture = {"html": html, "state0": state0, "answer": answered, "click": click, "delayMs": 150,
               "expect": {"quizLabel": label, "category": "Math", "correctKey": "B", "outcome": outcome, "explanation": EXPL,
                          "counters": {"correct": counters[0], "wrong": counters[1], "score": counters[2]}}}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    r = subprocess.run(["node", "tests/js/quiz_dom_check.js", str(path)], capture_output=True, text=True, env=env, cwd=".")
    assert r.returncode == 0 and "dom ok" in r.stdout, r.stderr + r.stdout


# ------------------------------------------------------------ Finish & Save result popup: Home + View History
def _answered_game(app, client, mode):
    gid, qid = setup(app, client, mode)
    api(client, gid, "answer", question_id=qid, option="C")        # wrong
    api(client, gid, "next")
    q2 = state(client, gid)["question"]["id"]
    from tests.conftest import correct_letter
    api(client, gid, "answer", question_id=q2, option=correct_letter(app, q2))  # correct
    if mode == "daily":  # a Daily Challenge can only be saved once every question is resolved
        while not state(client, gid)["all_resolved"]:
            api(client, gid, "next")
            qid = state(client, gid)["question"]["id"]
            api(client, gid, "answer", question_id=qid, option=correct_letter(app, qid))
    return gid


def test_result_popup_markup_has_home_then_view_history(app, client, user):
    gid, _ = setup(app, client, "category")
    html = client.get(f"/quiz/{gid}").get_data(as_text=True)
    box = html[html.index('id="resultDialog"'):html.index("</dialog>", html.index('id="resultDialog"'))]
    assert "Quiz saved!" in box and 'id="resultBody"' in box
    assert box.index(">Home</a>") < box.index(">View History</a>")
    assert 'id="resultHome" href="/home"' in box or 'id="resultHome" href="/"' in box  # the existing Home route


@pytest.mark.parametrize("mode,label", MODES)
def test_home_and_history_work_after_a_saved_game(app, client, user, mode, label, db):
    gid = _answered_game(app, client, mode)
    summary = api(client, gid, "finish").get_json()
    sm = summary["summary"]
    assert summary["ok"] and sm["resolved"] == (4 if mode == "daily" else 2) and sm["correct"] == (3 if mode == "daily" else 1)
    assert summary["redirect"].endswith("/history")
    home = client.get("/home")
    assert home.status_code == 200 and b"Welcome" in home.data                      # Home opens the dashboard
    assert db.query(QuizGame).filter_by(id=gid, status="completed").count() == 1   # the saved game is untouched
    assert client.get("/").status_code == 200 and db.query(QuizGame).filter_by(status="in_progress").count() == 0  # nothing new started
    hist = client.get("/history").get_data(as_text=True)
    body = hist[hist.index("<tbody>"):]
    assert {"category": "Category Quiz", "all": "All Quiz", "daily": "Daily Quiz"}[mode] in body
    import re
    row = re.search(r'<td data-label="Score" class="num">(-?\d+)</td>', body)
    assert row and int(row.group(1)) == sm["score"] == (30 if mode == "daily" else 10)  # the saved score is shown as-is
    stats = client.get("/").get_data(as_text=True)
    assert "Games saved" in stats and ">1<" in stats.replace(" ", "")


def test_second_finish_does_not_create_a_second_record(app, client, user, db):
    gid = _answered_game(app, client, "category")
    a = api(client, gid, "finish").get_json()["summary"]
    b = api(client, gid, "finish").get_json()["summary"]
    assert a["already_saved"] is False and b["already_saved"] is True and a["score"] == b["score"] == 10
    assert db.query(QuizGame).filter_by(status="completed").count() == 1


@pytest.mark.parametrize("mode,label", MODES)
@pytest.mark.parametrize("scenario", ["success", "failure"])
def test_result_popup_javascript(app, client, user, tmp_path, mode, label, scenario):
    env = dict(os.environ)
    if not _jsdom_available(env):
        pytest.skip("node + jsdom not available (npm install jsdom; set NODE_PATH to its node_modules)")
    gid = _answered_game(app, client, mode)
    page = client.get(f"/quiz/{gid}").get_data(as_text=True)
    state0 = api(client, gid, "state").get_json()
    if scenario == "success":
        resp = api(client, gid, "finish")
        finish, status = resp.get_json(), 200
        s = finish["summary"]
        m, sec = divmod(s["elapsed_seconds"], 60)
        body = f"Score: {s['score']} \u00b7 Answered: {s['resolved']} of {s['total']} \u00b7 Correct: {s['correct']} \u00b7 Time: {m:02d}:{sec:02d}"
        hist = finish["redirect"]
    else:
        finish, status, body, hist = {"ok": False, "error": "Could not save the game. Please try again.", "code": "save_failed"}, 500, "", "/history"
    home_href = "/home" if 'id="resultHome" href="/home"' in page else "/"
    path = tmp_path / "popup.json"
    path.write_text(json.dumps({"html": page, "state0": state0, "finish": finish, "finishStatus": status, "mode": scenario,
                                "expectBody": body, "homeHref": home_href, "historyHref": hist}), encoding="utf-8")
    r = subprocess.run(["node", "tests/js/result_popup_check.js", str(path)], capture_output=True, text=True, env=env, cwd=".")
    assert r.returncode == 0 and "popup ok" in r.stdout, r.stderr + r.stdout


# ------------------------------------------------------------ question counter per quiz mode
def _states_for_number_test(app, client, mode):
    gid, qid = setup(app, client, mode)
    page = client.get(f"/quiz/{gid}").get_data(as_text=True)
    state0 = api(client, gid, "state").get_json()
    answered = api(client, gid, "answer", question_id=qid, option="B").get_json()
    nxt = api(client, gid, "next").get_json()
    prev = api(client, gid, "previous").get_json()
    return gid, page, {"state0": state0, "answered": answered, "next": nxt, "prev": prev}


@pytest.mark.parametrize("mode", ["category", "all", "daily"])
def test_total_count_stays_in_the_state_for_every_mode(app, client, user, mode):
    gid, _, st = _states_for_number_test(app, client, mode)
    assert st["state0"]["state"]["total"] == 4 and st["next"]["state"]["question"]["number"] == 2
    assert st["prev"]["state"]["question"]["number"] == 1           # the real total is kept for progression/finish


@pytest.mark.parametrize("mode,expect", [("category", ["1", "2"]), ("all", ["1", "2"]), ("daily", ["1 / 4", "2 / 4"])])
def test_question_counter_javascript_per_mode(app, client, user, tmp_path, mode, expect):
    env = dict(os.environ)
    if not _jsdom_available(env):
        pytest.skip("node + jsdom not available (npm install jsdom; set NODE_PATH to its node_modules)")
    gid, page, states = _states_for_number_test(app, client, mode)
    path = tmp_path / "num.json"
    path.write_text(json.dumps({"html": page, "states": states, "expect": expect}), encoding="utf-8")
    r = subprocess.run(["node", "tests/js/question_number_check.js", str(path)], capture_output=True, text=True, env=env, cwd=".")
    assert r.returncode == 0 and "number ok" in r.stdout, r.stderr + r.stdout


def test_daily_quiz_shows_one_of_fifty_with_the_real_daily_size(tmp_path):
    from tests.conftest import login, make_app, register
    env = dict(os.environ)
    if not _jsdom_available(env):
        pytest.skip("node + jsdom not available (npm install jsdom; set NODE_PATH to its node_modules)")
    app = make_app(tmp_path, DAILY_QUESTION_COUNT=50)
    c = app.test_client()
    register(c)
    login(c)
    gid = start(c, "daily")
    st = state(c, gid)
    assert st["total"] == 50 and st["quiz_type"] == "daily"
    page = c.get(f"/quiz/{gid}").get_data(as_text=True)
    qid = st["question"]["id"]
    from tests.conftest import correct_letter
    c.post(f"/api/games/{gid}/answer", json={"question_id": qid, "option": correct_letter(app, qid)})
    states = {"state0": api(c, gid, "state").get_json(), "answered": api(c, gid, "state").get_json(),
              "next": api(c, gid, "next").get_json(), "prev": api(c, gid, "previous").get_json()}
    states["state0"]["state"]["question"]["resolved"] = False
    path = tmp_path / "num50.json"
    path.write_text(json.dumps({"html": page, "states": states, "expect": ["1 / 50", "2 / 50"]}), encoding="utf-8")
    r = subprocess.run(["node", "tests/js/question_number_check.js", str(path)], capture_output=True, text=True, env=env, cwd=".")
    assert r.returncode == 0 and "number ok" in r.stdout, r.stderr + r.stdout
