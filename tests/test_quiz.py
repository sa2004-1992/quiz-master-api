from sqlalchemy import select

from app.models import (DailyGameRecord, PlayAllProgress, Question, QuizGame, QuizGameAnswer,
                        UserCategoryProgress)
from app.services import progress, scoring
from tests.conftest import (add_questions, answer, api, cat_id, correct_letter, play_through, start,
                            state, wrong_letter)


# ---------------------------------------------------------------- pure logic
def test_scoring_rules():
    assert scoring.points_for(True, False) == 10 and scoring.points_for(False, False) == -5
    assert scoring.points_for(False, True) == 0 and scoring.points_for(True, True) == 0
    assert scoring.running_scores([-5, 10, -5, -5, -5, 10]) == [0, 10, 5, 0, 0, 10]  # floor at zero
    assert scoring.final_score([]) == 0


def test_category_slice_never_wraps_onto_completed_questions():
    ids = [1, 2, 3, 4, 5, 6]
    assert progress.category_slice(ids, 0, 5) == ([1, 2, 3, 4, 5], [0, 1, 2, 3, 4])
    assert progress.category_slice(ids, 4, 5) == ([5, 6], [4, 5])      # only what is left; no repeat of 1..3
    assert progress.category_slice(ids, 6, 5) == ([], [])               # all completed -> empty, never wraps
    assert progress.category_slice([7, 8], 0, 10)[0] == [7, 8]
    assert progress.next_category_pointer(5, 6) == 6 and progress.next_category_pointer(2, 6) == 3


def test_all_quiz_slice_follows_category_order():
    by = {10: [1, 2], 20: [3, 4], 30: [5]}
    q, pos, needs = progress.all_quiz_slice([10, 20, 30], by, 0, 6)
    assert q[:3] == [1, 3, 5] and pos[:3] == [0, 1, 2]
    q2, _, _ = progress.all_quiz_slice([10, 20, 30], by, 3, 2)
    assert q2 == [2, 4]  # second round continues in the same category order


# ---------------------------------------------------------------- gameplay
def test_answer_scoring_and_locking(app, client, user):
    cid = cat_id(app, "Cricket")
    add_questions(app, "Cricket", 10)  # on top of the 2 seeded
    gid = start(client, "category", cid)
    st = state(client, gid)
    assert st["total"] == 5 and "correct_answer" not in st["question"]  # never leaked before resolving
    r = answer(app, client, gid, correct=False)
    assert r.get_json()["state"]["score"] == 0  # -5 floored at 0
    assert r.get_json()["state"]["question"]["correct_answer"] in "ABCD"
    assert r.get_json()["state"]["question"]["explanation"]
    # duplicate answer rejected, score unchanged
    qid = st["question"]["id"]
    dup = api(client, gid, "answer", question_id=qid, option=correct_letter(app, qid))
    assert dup.status_code == 409 and state(client, gid)["score"] == 0
    api(client, gid, "next")
    assert answer(app, client, gid, correct=True).get_json()["state"]["score"] == 10


def test_next_requires_resolution_and_no_skipping(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    assert api(client, gid, "next").status_code == 409
    assert state(client, gid)["can_next"] is False and state(client, gid)["can_previous"] is False
    assert api(client, gid, "previous").status_code == 400


def test_previous_shows_result_without_rescoring(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    answer(app, client, gid, correct=True)
    api(client, gid, "next")
    answer(app, client, gid, correct=False)
    before = state(client, gid)["score"]
    prev = api(client, gid, "previous").get_json()["state"]
    assert prev["current_index"] == 0 and prev["question"]["resolved"] and prev["question"]["is_correct"]
    qid = prev["question"]["id"]
    again = api(client, gid, "answer", question_id=qid, option=wrong_letter(app, qid))
    assert again.status_code == 409
    assert state(client, gid)["score"] == before


def test_out_of_sync_question_rejected(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    assert api(client, gid, "answer", question_id=999999, option="A").status_code == 409
    assert api(client, gid, "answer", question_id="x", option="A").status_code == 400
    qid = state(client, gid)["question"]["id"]
    assert api(client, gid, "answer", question_id=qid, option="Z").status_code == 400


def test_hints_resolve_without_score_and_are_limited(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))  # HINTS_PER_GAME=3 in tests
    for i in range(3):
        qid = state(client, gid)["question"]["id"]
        r = api(client, gid, "hint", question_id=qid)
        st = r.get_json()["state"]
        assert st["question"]["resolved"] and st["question"]["hint_used"] and st["score"] == 0
        assert st["question"]["correct_answer"] == correct_letter(app, qid)
        assert api(client, gid, "hint", question_id=qid).status_code == 409  # one hint per question
        api(client, gid, "next")
    qid = state(client, gid)["question"]["id"]
    assert api(client, gid, "hint", question_id=qid).status_code == 403
    assert state(client, gid)["hints_left"] == 0
    assert state(client, gid)["hints_used"] == 3  # persisted server-side (survives refresh)


def test_pause_resume_excludes_paused_time(app, client, user, fake_clock):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    fake_clock.advance(seconds=30)
    assert state(client, gid)["elapsed_seconds"] == 30
    api(client, gid, "pause")
    fake_clock.advance(seconds=600)
    st = state(client, gid)
    assert st["paused"] and st["elapsed_seconds"] == 30
    qid = st["question"]["id"]
    assert api(client, gid, "answer", question_id=qid, option="A").status_code == 409  # paused
    api(client, gid, "resume")
    fake_clock.advance(seconds=15)
    assert state(client, gid)["elapsed_seconds"] == 45
    answer(app, client, gid)
    res = api(client, gid, "finish").get_json()["summary"]
    assert res["elapsed_seconds"] == 45  # client time is never trusted


def test_finish_while_paused_excludes_pause(app, client, user, fake_clock):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    fake_clock.advance(seconds=20)
    answer(app, client, gid)
    api(client, gid, "pause")
    fake_clock.advance(seconds=500)
    assert api(client, gid, "finish").get_json()["summary"]["elapsed_seconds"] == 20


def test_exit_discards_everything(app, client, user, db):
    cid = cat_id(app, "Math")
    add_questions(app, "Math", 10)
    gid = start(client, "category", cid)
    answer(app, client, gid)
    r = api(client, gid, "exit")
    assert r.status_code == 200
    assert db.query(QuizGame).count() == 0 and db.query(QuizGameAnswer).count() == 0
    assert db.query(UserCategoryProgress).count() == 0
    assert api(client, gid, "state").status_code == 404
    assert b"No saved games" in client.get("/history").data


def test_finish_saves_and_advances_pointer_by_resolved(app, client, user, db):
    cid = cat_id(app, "Math")
    add_questions(app, "Math", 18)  # 20 total with seeds
    gid = start(client, "category", cid)
    play_through(app, client, gid, 3, correct=True)
    summary = api(client, gid, "finish").get_json()["summary"]
    assert summary["score"] == 30 and summary["resolved"] == 3 and not summary["already_saved"]
    assert db.get(UserCategoryProgress, (1, cid)).pointer == 3
    # retry is idempotent: no double advancement, no duplicate record
    again = api(client, gid, "finish").get_json()["summary"]
    assert again["already_saved"] and again["score"] == 30
    db.expire_all()
    assert db.get(UserCategoryProgress, (1, cid)).pointer == 3 and db.query(QuizGame).count() == 1
    # next game continues where the last stopped, with different questions
    first_ids = db.get(QuizGame, gid).question_ids
    gid2 = start(client, "category", cid)
    ids2 = db.get(QuizGame, gid2).question_ids
    assert ids2[0] == first_ids[3] and gid2 != gid


def test_finish_with_nothing_resolved_creates_no_record(app, client, user, db):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    r = api(client, gid, "finish")
    assert r.status_code == 400
    assert db.query(QuizGame).filter_by(status="completed").count() == 0
    assert db.get(QuizGame, gid).status == "in_progress"


def test_saved_game_cannot_be_modified(app, client, user):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    answer(app, client, gid)
    api(client, gid, "finish")
    qid = state(client, gid)["question"]["id"]
    assert api(client, gid, "answer", question_id=qid, option="A").status_code == 409
    assert client.get(f"/quiz/{gid}").status_code == 302


def test_start_resumes_existing_game(app, client, user):
    add_questions(app, "Math", 10)
    cid = cat_id(app, "Math")
    g1 = start(client, "category", cid)
    answer(app, client, g1)
    assert start(client, "category", cid) == g1
    assert state(client, g1)["resolved_count"] == 1


def test_completed_category_is_not_repeated_automatically(app, client, user, db):
    cid = cat_id(app, "Chess")  # 2 seeded questions, no Gemini key
    g = start(client, "category", cid)
    assert state(client, g)["total"] == 2
    play_through(app, client, g, 2)
    api(client, g, "finish")
    assert db.get(UserCategoryProgress, (1, cid)).pointer == 2  # end reached
    r = client.post(f"/quiz/start/category/{cid}", data={"back": "quizzes"})  # plain Start: refused, nothing repeated
    assert r.status_code == 302 and r.headers["Location"].endswith("/quizzes") and "/quiz/" not in r.headers["Location"]
    assert db.query(QuizGame).filter_by(status="in_progress").count() == 0
    assert "completed all available questions" in client.get("/quizzes").get_data(as_text=True)
    # explicit Play Again restarts from the beginning; saved history is preserved
    g2 = start_restart(client, cid)
    assert db.get(QuizGame, g2).question_ids == db.get(QuizGame, g).question_ids and db.get(QuizGame, g2).start_pointer == 0
    assert db.query(QuizGame).filter_by(status="completed").count() == 1


def start_restart(client, cid):
    import re
    r = client.post(f"/quiz/start/category/{cid}", data={"restart": "1"})
    m = re.search(r"/quiz/(\d+)$", r.headers.get("Location", ""))
    return int(m.group(1)) if m else None


def test_play_again_is_refused_while_questions_remain(app, client, user, db):
    add_questions(app, "Math", 10)  # 12 stored; nothing completed yet
    cid = cat_id(app, "Math")
    g = start_restart(client, cid)
    assert db.get(QuizGame, g).start_pointer == 0 and len(db.get(QuizGame, g).question_ids) == 5
    api(client, g, "exit")
    play = start(client, "category", cid)
    answer(app, client, play)
    api(client, play, "finish")                       # pointer = 1
    g2 = start_restart(client, cid)                   # restart flag on a NOT completed category is ignored
    assert db.get(QuizGame, g2).start_pointer == 1


def test_next_sessions_use_next_unseen_questions_without_repeats(app, client, user, db):
    add_questions(app, "Math", 10)  # 12 questions, 5 per game: 5 + 5 + 2
    cid = cat_id(app, "Math")
    seen = []
    for expected_size in (5, 5, 2):
        g = start(client, "category", cid)
        ids = db.get(QuizGame, g).question_ids
        assert len(ids) == expected_size and not set(ids) & set(seen)   # nothing completed is shown again
        play_through(app, client, g, len(ids))
        api(client, g, "finish")
        seen += ids
    assert len(seen) == len(set(seen)) == 12 and db.get(UserCategoryProgress, (1, cid)).pointer == 12
    assert start(client, "category", cid) is None  # completed: no automatic repeat


def test_unresolved_questions_come_back_but_completed_ones_do_not(app, client, user, db):
    add_questions(app, "Math", 10)
    cid = cat_id(app, "Math")
    g = start(client, "category", cid)
    first = db.get(QuizGame, g).question_ids
    play_through(app, client, g, 2)       # only 2 of 5 resolved
    api(client, g, "finish")
    g2 = start(client, "category", cid)
    ids2 = db.get(QuizGame, g2).question_ids
    assert ids2[0] == first[2] and not set(ids2) & set(first[:2])


def test_quizzes_card_buttons_start_continue_and_after_save(app, client, user, db):
    import re
    add_questions(app, "Math", 10)
    cid = cat_id(app, "Math")

    def card_button(name):
        html = client.get("/quizzes").get_data(as_text=True)
        card = html[html.index(f'class="category-name">{name}</span>'):]
        return re.search(r'<button class="btn btn-primary btn-sm" type="submit">([^<]+)</button>', card).group(1)

    assert card_button("Math") == "Start"
    g = start(client, "category", cid)
    answer(app, client, g)
    assert card_button("Math") == "Continue"             # an unsaved game in progress can be continued
    api(client, g, "exit")
    assert card_button("Math") == "Start"                # exit without saving: progress untouched
    assert db.query(UserCategoryProgress).count() == 0
    g = start(client, "category", cid)
    answer(app, client, g)
    api(client, g, "finish")
    assert card_button("Math") == "Start"                # after Finish & Save: never "Continue"
    assert "Continue" not in client.get("/quizzes").get_data(as_text=True)


def test_completed_card_shows_play_again_and_is_per_user(app, client, user, db):
    import re
    cid = cat_id(app, "Chess")
    g = start(client, "category", cid)
    play_through(app, client, g, 2)
    api(client, g, "finish")
    html = client.get("/quizzes").get_data(as_text=True)
    card = html[html.index('class="category-name">Chess</span>'):]
    assert re.search(r'name="restart" value="1"><button class="btn btn-primary btn-sm" type="submit">Play Again</button>', card)
    from tests.conftest import register, login
    bob = app.test_client()
    register(bob, "bob")
    login(bob, "bob")
    bhtml = bob.get("/quizzes").get_data(as_text=True)
    assert "Play Again" not in bhtml                       # progress is per user and per category
    assert start(bob, "category", cid) is not None


def test_play_all_and_daily_progress_unaffected_by_category_completion(app, client, user, db, fake_clock):
    cid = cat_id(app, "Chess")
    g = start(client, "category", cid)
    play_through(app, client, g, 2)
    api(client, g, "finish")
    assert db.query(PlayAllProgress).count() == 0
    a = start(client, "all")
    assert a is not None and db.get(QuizGame, a).start_pointer == 0
    assert start(client, "daily") is not None


def test_independent_pointers_between_quiz_types(app, client, user, db):
    math, cric = cat_id(app, "Math"), cat_id(app, "Cricket")
    add_questions(app, "Math", 10)
    add_questions(app, "Cricket", 10)
    g1 = start(client, "category", math)
    play_through(app, client, g1, 4)
    api(client, g1, "finish")
    g2 = start(client, "all")
    assert state(client, g2)["quiz_type"] == "all"
    play_through(app, client, g2, 3)
    api(client, g2, "finish")
    assert db.get(UserCategoryProgress, (1, math)).pointer == 4
    assert db.get(UserCategoryProgress, (1, cric)) is None
    assert db.get(PlayAllProgress, 1).pointer == 3
    assert db.query(DailyGameRecord).count() == 0


def test_all_quiz_follows_category_order_and_persists(app, client, user, db):
    gid = start(client, "all")
    game = db.get(QuizGame, gid)
    cats_in_game = [db.get(Question, q).category_id for q in game.question_ids]
    assert cats_in_game == list(range(1, 7))  # first six categories in the required order
    play_through(app, client, gid, 2)
    api(client, gid, "finish")
    gid2 = start(client, "all")
    db.expire_all()
    cats2 = [db.get(Question, q).category_id for q in db.get(QuizGame, gid2).question_ids]
    assert cats2[:2] == [3, 4]


# ---------------------------------------------------------------- daily
def test_daily_uses_dedicated_pool_and_hint_limit(app, client, user, db, fake_clock):
    gid = start(client, "daily")
    game = db.get(QuizGame, gid)
    pools = {db.get(Question, q).pool for q in game.question_ids}
    assert pools == {"daily"} and len(game.question_ids) == 4 and game.hints_max == 2
    qid = state(client, gid)["question"]["id"]
    api(client, gid, "hint", question_id=qid)
    api(client, gid, "next")
    qid = state(client, gid)["question"]["id"]
    api(client, gid, "hint", question_id=qid)
    api(client, gid, "next")
    qid = state(client, gid)["question"]["id"]
    assert api(client, gid, "hint", question_id=qid).status_code == 403


def test_daily_one_completion_per_day_and_streak(app, client, user, db, fake_clock):
    def complete_today():
        gid = start(client, "daily")
        play_through(app, client, gid, 4)
        return api(client, gid, "finish")

    assert complete_today().status_code == 200
    assert start(client, "daily") is None  # already completed -> refused
    assert b"Completed Today" in client.get("/").data
    # a second manual attempt through the API/db cannot create another record
    assert db.query(DailyGameRecord).count() == 1
    from app.models import UserDailyStreak
    s = db.get(UserDailyStreak, 1)
    assert (s.current_streak, s.longest_streak) == (1, 1)
    fake_clock.advance(days=1)
    assert complete_today().status_code == 200
    db.expire_all()
    assert (db.get(UserDailyStreak, 1).current_streak, db.get(UserDailyStreak, 1).longest_streak) == (2, 2)
    fake_clock.advance(days=3)  # missed days
    assert complete_today().status_code == 200
    db.expire_all()
    s = db.get(UserDailyStreak, 1)
    assert (s.current_streak, s.longest_streak) == (1, 2)  # reset, longest preserved


def test_daily_incomplete_cannot_be_saved_and_exit_allows_retry(app, client, user, db, fake_clock):
    gid = start(client, "daily")
    play_through(app, client, gid, 2)
    r = api(client, gid, "finish")
    assert r.status_code == 400 and db.query(QuizGame).filter_by(status="completed").count() == 0
    assert api(client, gid, "exit").status_code == 200
    from app.models import UserDailyStreak
    assert db.get(UserDailyStreak, 1) is None  # exit never touches the streak
    assert start(client, "daily") is not None  # may start again (nothing was completed)


def test_daily_set_is_shared_per_day_and_rotates(app, client, user, db, fake_clock):
    g1 = start(client, "daily")
    ids_today = db.get(QuizGame, g1).question_ids
    api(client, g1, "exit")
    g2 = start(client, "daily")
    assert db.get(QuizGame, g2).question_ids == ids_today  # same set all day
    api(client, g2, "exit")
    fake_clock.advance(days=1)
    g = start(client, "daily")
    assert set(db.get(QuizGame, g).question_ids).isdisjoint(ids_today)  # unused questions first


def test_daily_not_affecting_other_pointers(app, client, user, db, fake_clock):
    gid = start(client, "daily")
    play_through(app, client, gid, 4)
    api(client, gid, "finish")
    assert db.query(UserCategoryProgress).count() == 0 and db.query(PlayAllProgress).count() == 0


def test_streak_display_resets_when_day_missed(app, client, user, db, fake_clock):
    gid = start(client, "daily")
    play_through(app, client, gid, 4)
    api(client, gid, "finish")
    fake_clock.advance(days=2)
    html = client.get("/").get_data(as_text=True)
    assert "0 days" in html and "Longest streak" in html


def test_endless_category_quiz_extends_without_repeats(app, client, user, db):
    cid = cat_id(app, "Math")
    add_questions(app, "Math", 18)  # 20 stored in total
    gid = start(client, "category", cid)
    assert state(client, gid)["total"] == 5
    play_through(app, client, gid, 5)
    assert api(client, gid, "next").status_code == 200  # end of batch -> more questions appended
    st = state(client, gid)
    assert st["total"] == 10 and st["current_index"] == 5
    for _ in range(15):
        answer(app, client, gid)
        if api(client, gid, "next").status_code != 200:
            break
    ids = db.get(QuizGame, gid)
    db.refresh(ids)
    assert len(ids.question_ids) == len(set(ids.question_ids)) == 20  # all questions, never a repeat
    summary = api(client, gid, "finish").get_json()["summary"]
    assert summary["resolved"] >= 15
    db.expire_all()
    g = db.get(QuizGame, gid)
    expected = g.seq_positions[summary["resolved"] - 1] + 1
    assert db.get(UserCategoryProgress, (1, cid)).pointer == (expected % 20 if expected > 20 else expected)


def test_category_with_few_questions_stops_instead_of_repeating(app, client, user):
    gid = start(client, "category", cat_id(app, "Chess"))  # only 2 stored questions
    answer(app, client, gid)
    api(client, gid, "next")
    answer(app, client, gid)
    r = api(client, gid, "next")
    assert r.status_code == 400 and "Finish" in r.get_json()["error"]


def test_all_quiz_is_endless_and_daily_is_capped(app, client, user, db, fake_clock):
    gid = start(client, "all")
    play_through(app, client, gid, 6)
    assert api(client, gid, "next").status_code == 200  # All Quiz keeps going (next round)
    assert state(client, gid)["total"] > 6
    d = start(client, "daily")
    play_through(app, client, d, 4)
    assert api(client, d, "next").status_code == 400  # Daily stays a fixed set
