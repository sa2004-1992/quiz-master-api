from urllib.parse import quote

from sqlalchemy import select

from app.models import Question
from app.services.question_sources import OpenTriviaDB, SourceError, TriviaAPI, import_all, to_raw
from tests.test_ai import FakeResponse


class FakeGet:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def otdb_item(i):
    enc = lambda s: quote(s, safe="")
    return {"question": enc(f"Which planet is number {i} in the Solar System?"), "correct_answer": enc(f"Right {i}"),
            "incorrect_answers": [enc(f"Wrong A {i}"), enc(f"Wrong B {i}"), enc(f"Wrong C {i}")], "difficulty": "easy"}


def test_to_raw_shuffles_and_keeps_correct_letter():
    seen = set()
    for _ in range(40):
        raw = to_raw("Question text here?", "RIGHT", ["a", "b", "c"], "hard")
        assert raw["option_" + raw["correct_answer"].lower()] == "RIGHT"
        seen.add(raw["correct_answer"])
    assert len(seen) > 1 and raw["difficulty"] == "hard"


def test_opentdb_decodes_token_and_rate_limit_retry():
    sleeps = []
    http = FakeGet(FakeResponse(payload={"response_code": 0, "token": "tok"}),
                   FakeResponse(payload={"response_code": 5, "results": []}),
                   FakeResponse(payload={"response_code": 0, "results": [otdb_item(1), otdb_item(2)]}))
    api = OpenTriviaDB(http=http, sleep=sleeps.append, min_interval=0)
    out = api.fetch(17)
    assert len(out) == 2 and "Solar System" in out[0]["question"]
    assert http.calls[1][1]["token"] == "tok" and http.calls[1][1]["type"] == "multiple" and http.calls[1][1]["amount"] == 50
    assert 6 in sleeps


def test_opentdb_empty_and_failures():
    assert OpenTriviaDB(http=FakeGet(FakeResponse(payload={"response_code": 0, "token": "t"}),
                                     FakeResponse(payload={"response_code": 4, "results": []})), min_interval=0).fetch(9) == []
    bad = OpenTriviaDB(http=FakeGet(FakeResponse(status=500, payload={})), min_interval=0)
    try:
        bad.fetch(9)
        assert False
    except SourceError:
        pass


def test_trivia_api_parsing():
    payload = [{"category": "science", "correctAnswer": "Oxygen", "incorrectAnswers": ["Gold", "Iron", "Neon"],
                "question": {"text": "Which gas do humans need to breathe?"}, "difficulty": "easy", "type": "text_choice"},
               {"broken": True}]
    out = TriviaAPI(http=FakeGet(FakeResponse(payload=payload))).fetch("science")
    assert len(out) == 1 and out[0]["explanation"].startswith("The correct answer is")


def test_import_all_stores_dedupes_and_survives_provider_failure(app, db):
    otdb = OpenTriviaDB(http=FakeGet(FakeResponse(payload={"response_code": 0, "token": "t"}),
                                     FakeResponse(payload={"response_code": 0, "results": [otdb_item(i) for i in range(5)]})),
                        min_interval=0, sleep=lambda s: None)
    tapi = TriviaAPI(http=FakeGet(FakeResponse(status=503, payload={})))
    s = app.extensions["db_sessionmaker"]()
    first = import_all(s, ("opentdb", "trivia_api"), opentdb=otdb, trivia=tapi)
    assert first["inserted"] == 5  # the first mapped category got the batch; later calls repeat the same fake data
    rows = db.scalars(select(Question).where(Question.source == "opentdb")).all()
    assert len(rows) == 5 and len({r.question_hash for r in rows}) == 5
    again = import_all(s, ("opentdb",), opentdb=OpenTriviaDB(
        http=FakeGet(FakeResponse(payload={"response_code": 0, "token": "t"}),
                     FakeResponse(payload={"response_code": 0, "results": [otdb_item(i) for i in range(5)]})),
        min_interval=0, sleep=lambda s: None))
    assert again["inserted"] == 0  # duplicates rejected by hash
    s.close()


def test_import_command_registered(app):
    runner = app.test_cli_runner()
    assert "import-questions" in runner.invoke(args=["--help"]).output
