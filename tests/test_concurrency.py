import threading

from app.models import PlayAllProgress, QuizGame, QuizGameAnswer, UserCategoryProgress
from tests.conftest import (add_questions, answer, api, cat_id, correct_letter, play_through, start, state)


def clone_client(app, uid=1):
    c = app.test_client()
    with c.session_transaction() as s:
        s["uid"] = uid
    return c


def run_parallel(fns):
    barrier = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def wrap(i, fn):
        barrier.wait()
        out[i] = fn()

    ts = [threading.Thread(target=wrap, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def test_concurrent_duplicate_answers_count_once(app, client, user, db):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    qid = state(client, gid)["question"]["id"]
    letter = correct_letter(app, qid)
    clients = [clone_client(app) for _ in range(4)]
    res = run_parallel([lambda c=c: api(c, gid, "answer", question_id=qid, option=letter).status_code for c in clients])
    assert sorted(res) == [200, 409, 409, 409]
    assert db.query(QuizGameAnswer).filter_by(game_id=gid).count() == 1
    assert state(client, gid)["score"] == 10 and state(client, gid)["resolved_count"] == 1


def test_concurrent_hint_requests_use_one_hint(app, client, user, db):
    add_questions(app, "Math", 10)
    gid = start(client, "category", cat_id(app, "Math"))
    qid = state(client, gid)["question"]["id"]
    clients = [clone_client(app) for _ in range(3)]
    res = run_parallel([lambda c=c: api(c, gid, "hint", question_id=qid).status_code for c in clients])
    assert res.count(200) == 1
    assert state(client, gid)["hints_used"] == 1


def test_concurrent_finish_saves_and_advances_once(app, client, user, db):
    cid = cat_id(app, "Math")
    add_questions(app, "Math", 10)
    gid = start(client, "category", cid)
    play_through(app, client, gid, 3)
    clients = [clone_client(app) for _ in range(4)]
    res = run_parallel([lambda c=c: api(c, gid, "finish") for c in clients])
    assert all(r.status_code == 200 for r in res)
    saved_flags = [r.get_json()["summary"]["already_saved"] for r in res]
    assert saved_flags.count(False) == 1
    db.expire_all()
    assert db.get(UserCategoryProgress, (1, cid)).pointer == 3
    assert db.query(QuizGame).filter_by(status="completed").count() == 1
    assert all(r.get_json()["summary"]["score"] == 30 for r in res)


def test_concurrent_starts_create_one_game(app, client, user, db):
    add_questions(app, "Math", 10)
    cid = cat_id(app, "Math")
    clients = [clone_client(app) for _ in range(4)]
    ids = run_parallel([lambda c=c: start(c, "category", cid) for c in clients])
    assert len(set(ids)) == 1 and db.query(QuizGame).count() == 1


def test_concurrent_daily_starts_one_record(app, client, user, db, fake_clock):
    from app.models import DailyGameRecord
    clients = [clone_client(app) for _ in range(4)]
    ids = run_parallel([lambda c=c: start(c, "daily") for c in clients])
    assert len(set(i for i in ids if i)) == 1
    assert db.query(DailyGameRecord).count() == 1
