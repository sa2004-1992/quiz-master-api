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
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) < min_len:
        raise ValidationError(f"{field} is empty or too short")
    if len(value) > max_len:
        raise ValidationError(f"{field} is too long")
    return value


def kannada_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return (len(_KANNADA.findall(text)) / len(letters)) if letters else 0.0


def validate_question(raw, language="en") -> dict:
    """Return a normalized dict ready to store or raise ValidationError."""
    if not isinstance(raw, dict):
        raise ValidationError("question is not an object")
    q = _clean(raw.get("question"), "question", 500, 8)
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
    if _TIME_SENSITIVE.search(q) or _TIME_SENSITIVE.search(explanation):
        raise ValidationError("time-sensitive wording rejected")
    ratio = kannada_ratio(q)
    if language == "kn" and ratio < 0.5:
        raise ValidationError("Kannada category requires a Kannada question")
    if language != "kn" and ratio > 0.2:
        raise ValidationError("non-Kannada category requires an English question")
    return {
        "question_text": q, "option_a": opts["A"], "option_b": opts["B"], "option_c": opts["C"],
        "option_d": opts["D"], "correct_answer": correct, "explanation": explanation,
        "difficulty": difficulty, "question_hash": question_hash(q),
    }
