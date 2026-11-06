"""Validation + hashing for AI-generated (or seeded) questions."""
import hashlib
import re
import unicodedata

VALID_DIFFICULTIES = ("easy", "medium", "hard")
_TIME_SENSITIVE = re.compile(
    r"\b(current(ly)?|latest|recent(ly)?|today|this year|right now|at present|presently|"
    r"as of|reigning|defending champion|newest|upcoming|so far this)\b", re.I)
_KANNADA = re.compile(r"[\u0C80-\u0CFF]")


class ValidationError(ValueError):
    pass


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _clean(value, field, max_len, min_len=1):
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n"))  # keep line breaks
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if len(value) < min_len:
        raise ValidationError(f"{field} is empty or too short")
    if len(value) > max_len:
        raise ValidationError(f"{field} is too long")
    return value


def kannada_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return (len(_KANNADA.findall(text)) / len(letters)) if letters else 0.0


def validate_question(raw, language="en", check_time_sensitive=True):
    """Return a normalized dict ready to store or raise ValidationError.

    ``raw`` may use ``question`` or ``question_text`` for the question. Kannada categories need the question,
    all four options and the explanation in Kannada (options that are only digits are fine); every other
    category must be in English. Only the option markers A-D stay in English."""
    if not isinstance(raw, dict):
        raise ValidationError("question is not an object")
    q = _clean(raw.get("question") if raw.get("question") is not None else raw.get("question_text"), "question", 500, 8)
    opts = {k: _clean(raw.get(f"option_{k.lower()}"), f"option_{k.lower()}", 200) for k in "ABCD"}
    if len({normalize_text(v) for v in opts.values()}) != 4:
        raise ValidationError("options must be distinct")
    correct = raw.get("correct_answer")
    correct = correct.strip().upper() if isinstance(correct, str) else ""
    if correct not in ("A", "B", "C", "D"):
        raise ValidationError("correct_answer must be A, B, C or D")
    explanation = _clean(raw.get("explanation"), "explanation", 1200, 10)
    difficulty = str(raw.get("difficulty") or "medium").strip().lower()
    if difficulty not in VALID_DIFFICULTIES:
        raise ValidationError("invalid difficulty")
    if check_time_sensitive and (_TIME_SENSITIVE.search(q) or _TIME_SENSITIVE.search(explanation)):
        raise ValidationError("time-sensitive wording rejected")
    fields = [("question", q)] + [(f"option_{k.lower()}", v) for k, v in opts.items()] + [("explanation", explanation)]
    for name, text in fields:
        if language == "kn":
            if any(c.isalpha() for c in text) and kannada_ratio(text) < 0.5:
                raise ValidationError(f"{name} must be written in Kannada for the Kannada category")
        elif kannada_ratio(text) > 0.2:
            raise ValidationError(f"{name} must be in English for this category")
    return {
        "question_text": q, "option_a": opts["A"], "option_b": opts["B"], "option_c": opts["C"],
        "option_d": opts["D"], "correct_answer": correct, "explanation": explanation,
        "difficulty": difficulty, "question_hash": question_hash(q),
    }
