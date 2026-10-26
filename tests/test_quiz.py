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


def test_category_slice_wraps_and_never_repeats_within_game():
    ids = [1, 2, 3, 4, 5, 6]
    assert progress.category_slice(ids, 0, 5) == ([1, 2, 3, 4, 5], [0, 1, 2, 3, 4])
    q, pos = progress.category_slice(ids, 4, 5)
    assert q == [5, 6, 1, 2, 3] and len(set(q)) == 5
    assert progress.category_slice([7, 8], 0, 10)[0] == [7, 8]
    assert progress.next_category_pointer(8, 6) == 3 and progress.next_category_pointer(5, 6) == 6


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


def test_category_pointer_wraps_after_end(app, client, user, db):
    cid = cat_id(app, "Chess")  # 2 seeded questions
    g = start(client, "category", cid)
    assert state(client, g)["total"] == 2
    play_through(app, client, g, 2)
    api(client, g, "finish")
    assert db.get(UserCategoryProgress, (1, cid)).pointer == 2  # end reached
    g2 = start(client, "category", cid)  # no Gemini key -> wraps to the start
    assert db.get(QuizGame, g2).question_ids == db.get(QuizGame, g).question_ids


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
