"""Importers for ready-made question banks (Open Trivia DB, The Trivia API).

They feed the same validate -> de-duplicate -> store pipeline as Gemini, so every provider ends up
in one PostgreSQL table. Neither provider supplies explanations, so a short factual explanation
("The correct answer is ...") is stored; Gemini questions carry real explanations.

Licensing (check the providers' current terms before launch):
* Open Trivia DB: CC BY-SA 4.0 - attribution required (see the page footer).
* The Trivia API: free for non-commercial use only; commercial use needs a paid plan.
"""
import logging
import random
import time
from urllib.parse import unquote

import requests
from sqlalchemy import select

from ..models import Category
from .ai_question_generator import store_questions

log = logging.getLogger(__name__)
UA = {"User-Agent": "QuizMaster/1.0"}

# Open Trivia DB category id -> our category (only clear fits; the rest come from Gemini).
OPENTDB_MAP = {
    9: "General Knowledge (GK)", 11: "Cinema", 16: "Board Games", 17: "Science",
    18: "Computer Basics", 19: "Math", 22: "Countries & Capitals", 23: "History",
    24: "Social Science", 26: "Famous People", 27: "Animals", 30: "Technology",
}
# The Trivia API category slug -> our category.
TRIVIA_API_MAP = {
    "general_knowledge": "General Knowledge (GK)", "history": "History", "science": "Science",
    "film_and_tv": "Cinema", "geography": "Countries & Capitals",
}


class SourceError(Exception):
    pass


def to_raw(question, correct, incorrect, difficulty):
    """Build the dict expected by validate_question, shuffling so the answer letter varies."""
    options = [correct] + list(incorrect)
    if len(options) != 4:
        raise SourceError("expected exactly 4 options")
    random.shuffle(options)
    return {
        "question": question, "option_a": options[0], "option_b": options[1],
        "option_c": options[2], "option_d": options[3], "correct_answer": "ABCD"[options.index(correct)],
        "explanation": f"The correct answer is {correct}.",
        "difficulty": difficulty if difficulty in ("easy", "medium", "hard") else "medium",
    }


class OpenTriviaDB:
    BASE = "https://opentdb.com"

    def __init__(self, http=None, sleep=time.sleep, min_interval=5.5, timeout=15):
        self.http, self.sleep, self.min_interval, self.timeout = http or requests, sleep, min_interval, timeout
        self.token, self._last = None, 0.0

    def _get(self, path, params):
        wait = self.min_interval - (time.monotonic() - self._last)  # API allows 1 request / 5 s per IP
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self.http.get(f"{self.BASE}/{path}", params=params, headers=UA, timeout=self.timeout)
            if resp.status_code != 200:
                raise SourceError(f"opentdb HTTP {resp.status_code}")
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceError(f"opentdb request failed: {type(exc).__name__}") from exc

    def _new_token(self):
        data = self._get("api_token.php", {"command": "request"})
        self.token = data.get("token")

    def fetch(self, category_id, amount=50, difficulty=None, retries=2):
        """Return raw question dicts (may be empty if the category/token is exhausted)."""
        if self.token is None:
            self._new_token()
        params = {"amount": min(amount, 50), "category": category_id, "type": "multiple",
                  "encode": "url3986", "token": self.token}
        if difficulty:
            params["difficulty"] = difficulty
        for _ in range(retries + 1):
            data = self._get("api.php", params)
            code = data.get("response_code")
            if code == 0:
                out = []
                for item in data.get("results", []):
                    try:
                        out.append(to_raw(unquote(item["question"]), unquote(item["correct_answer"]),
                                          [unquote(x) for x in item["incorrect_answers"]],
                                          unquote(item.get("difficulty", "medium"))))
                    except (KeyError, SourceError):
                        continue
                return out
            if code in (1, 4):  # no results / token has returned everything available
                return []
            if code == 3:  # token expired
                self._new_token()
                params["token"] = self.token
                continue
            if code == 5:  # rate limited: wait and retry
                self.sleep(6)
                continue
            raise SourceError(f"opentdb response_code {code}")
        raise SourceError("opentdb rate limit persisted")


class TriviaAPI:
    URL = "https://the-trivia-api.com/v2/questions"

    def __init__(self, http=None, timeout=15):
        self.http, self.timeout = http or requests, timeout

    def fetch(self, category_slug, limit=50, difficulty=None):
        params = {"limit": min(limit, 50), "categories": category_slug, "types": "text_choice"}
        if difficulty:
            params["difficulties"] = difficulty
        try:
            resp = self.http.get(self.URL, params=params, headers=UA, timeout=self.timeout)
            if resp.status_code != 200:
                raise SourceError(f"trivia_api HTTP {resp.status_code}")
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceError(f"trivia_api request failed: {type(exc).__name__}") from exc
        out = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(to_raw(item["question"]["text"], item["correctAnswer"], item["incorrectAnswers"],
                                  item.get("difficulty", "medium")))
            except (KeyError, TypeError, SourceError):
                continue
        return out


def import_all(session, sources=("opentdb", "trivia_api"), rounds=1, pool="category",
               opentdb=None, trivia=None, progress=lambda msg: None):
    """Import from the chosen providers. Returns {'inserted': n, 'rejected': n}. Never raises on provider failure."""
    cats = {c.name: c for c in session.scalars(select(Category))}
    totals = {"inserted": 0, "rejected": 0}

    def store(cat_name, raws, source):
        cat = cats.get(cat_name)
        if cat is None or not raws:
            return
        ins, rej = store_questions(session, cat, pool, raws, source=source)
        totals["inserted"] += ins
        totals["rejected"] += rej
        progress(f"{source}: {cat_name} +{ins} (skipped {rej})")

    for _ in range(rounds):
        if "opentdb" in sources:
            otdb = opentdb or OpenTriviaDB()
            opentdb = otdb
            for cid, name in OPENTDB_MAP.items():
                try:
                    store(name, otdb.fetch(cid), "opentdb")
                except SourceError as exc:
                    log.warning("Open Trivia DB failed for %s: %s", name, exc)
        if "trivia_api" in sources:
            tapi = trivia or TriviaAPI()
            trivia = tapi
            for slug, name in TRIVIA_API_MAP.items():
                try:
                    store(name, tapi.fetch(slug), "trivia_api")
                except SourceError as exc:
                    log.warning("The Trivia API failed for %s: %s", name, exc)
    return totals
