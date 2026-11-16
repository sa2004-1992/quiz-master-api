"""The shared question bank: three independent datasets (quiz modes) in one table.

A question belongs to exactly one mode (stored in ``questions.pool``): 'category' (Quiz 1), 'all' (Quiz 2) or
'daily' (Quiz 3). CSV import and Gemini generation both go through the same pipeline here:
validate -> duplicate check (inside ONE mode + category only) -> insert. Nothing is ever copied between modes
and existing questions are never modified or deleted.
"""
import csv
import io
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..categories import DATASET_NAMES, dataset_name
from ..models import Category, Question
from .question_validator import ValidationError, normalize_text, question_hash, validate_question

MODES = ("category", "all", "daily")
MODE_LABELS = {"category": "Category Quiz", "all": "All Quiz", "daily": "Daily Quiz"}
CSV_COLUMNS = ["question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation",
               "category_name"]
KN_TEMPLATE_ROW = [
    "\u0C95\u0CA8\u0CCD\u0CA8\u0CA1\u0CA6 \u0CAE\u0CCA\u0CA6\u0CB2 \u0C95\u0CB5\u0CBF \u0CAF\u0CBE\u0CB0\u0CC1?",
    "\u0CAA\u0C82\u0CAA", "\u0CB0\u0CA8\u0CCD\u0CA8", "\u0C9C\u0CA8\u0CCD\u0CA8", "\u0CB9\u0CB0\u0CBF\u0CB9\u0CB0", "A",
    "\u0CAA\u0C82\u0CAA \u0C95\u0CA8\u0CCD\u0CA8\u0CA1\u0CA6 \u0C86\u0CA6\u0CBF\u0C95\u0CB5\u0CBF\u0C97\u0CB3\u0CB2\u0CCD\u0CB2\u0CBF "
    "\u0C92\u0CAC\u0CCD\u0CAC\u0CB0\u0CC1.", DATASET_NAMES["Kannada"]]


def _template():
    buf = io.StringIO()
    buf.write(",".join(CSV_COLUMNS) + "\n")  # plain header line, quoted example rows
    w = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL)
    w.writerow(["What is the capital of India?", "Mumbai", "New Delhi", "Bengaluru", "Chennai", "B",
                "New Delhi is the capital of India.", "General Knowledge (GK)"])
    w.writerow(KN_TEMPLATE_ROW)  # Kannada questions use the dataset name for the category
    return buf.getvalue()


CSV_TEMPLATE = _template()


# ----------------------------------------------------------------------------- duplicate detection
def _tokens(norm):
    return set(norm.split())


class DuplicateIndex:
    """Duplicates inside ONE (mode, category). Exact match = same normalized question text (hash). Near-duplicate
    = a reworded question about the same fact: very similar wording, same numbers and the same correct answer.
    This is a reasonable heuristic, not a guarantee; nothing is ever deleted automatically."""

    def __init__(self):
        self.hashes = {}
        self.items = []  # (normalized text, token set, numbers, normalized correct answer, display text)

    def add(self, question_text, correct_text):
        norm = normalize_text(question_text)
        toks = _tokens(norm)
        self.hashes[question_hash(question_text)] = question_text
        self.items.append((norm, toks, frozenset(t for t in toks if t.isdigit()), normalize_text(correct_text),
                           question_text))

    def check(self, question_text, correct_text):
        """Return None, or a human-readable reason this question is a duplicate."""
        h = question_hash(question_text)
        if h in self.hashes:
            return "duplicate: this exact question already exists in this quiz mode and category"
        norm = normalize_text(question_text)
        toks = _tokens(norm)
        if len(toks) < 6:
            return None  # too short for a meaningful similarity comparison; only exact matches count
        nums, correct = frozenset(t for t in toks if t.isdigit()), normalize_text(correct_text)
        for o_norm, o_toks, o_nums, o_correct, o_text in self.items:
            if o_correct != correct or o_nums != nums or len(o_toks) < 6:
                continue
            union = len(toks | o_toks)
            jac = len(toks & o_toks) / union if union else 0.0
            if jac >= 0.8 or (jac >= 0.6 and abs(len(norm) - len(o_norm)) <= 0.2 * max(len(norm), len(o_norm))
                               and SequenceMatcher(None, norm, o_norm).ratio() >= 0.92):
                return f"near-duplicate of an existing question: \"{o_text[:70]}\""
        return None


def load_index(session, pool, category_id):
    idx = DuplicateIndex()
    rows = session.execute(select(Question.question_text, Question.option_a, Question.option_b, Question.option_c,
                                  Question.option_d, Question.correct_answer)
                           .where(Question.pool == pool, Question.category_id == category_id)).all()
    for q, a, b, c, d, ans in rows:
        idx.add(q, {"A": a, "B": b, "C": c, "D": d}[ans])
    return idx


# ----------------------------------------------------------------------------- validate + dedupe + insert
def check_rows(session, pool, entries, check_time_sensitive=True):
    """Classify entries without writing anything.

    ``entries``: list of dicts {"ref": any label, "category": Category|None, "raw": dict, "errors": [str]}.
    Returns a list of {"ref", "category", "status": 'valid'|'invalid'|'duplicate', "reason", "data"}."""
    indexes, out = {}, []
    for e in entries:
        cat, base = e["category"], {"ref": e["ref"], "category": e["category"], "data": None, "reason": ""}
        if e.get("errors"):
            out.append({**base, "status": "invalid", "reason": "; ".join(e["errors"])})
            continue
        try:
            data = validate_question(e["raw"], cat.language, check_time_sensitive)
        except ValidationError as exc:
            out.append({**base, "status": "invalid", "reason": str(exc)})
            continue
        idx = indexes.get(cat.id)
        if idx is None:
            idx = indexes[cat.id] = load_index(session, pool, cat.id)
        correct_text = data["option_" + data["correct_answer"].lower()]
        dup = idx.check(data["question_text"], correct_text)
        if dup:
            out.append({**base, "status": "duplicate", "reason": dup})
            continue
        idx.add(data["question_text"], correct_text)  # later rows in the same batch are compared with this one too
        out.append({**base, "status": "valid", "data": data})
    return out


def insert_valid(session, pool, results, source):
    """Insert the 'valid' results into ``pool``. Returns (inserted_ids, race_duplicates). Commits."""
    rows = [Question(pool=pool, category_id=r["category"].id, source=source, **r["data"])
            for r in results if r["status"] == "valid"]
    if not rows:
        return [], 0
    session.add_all(rows)
    try:
        session.commit()
        return [q.id for q in rows], 0
    except IntegrityError:  # another request inserted one of them meanwhile: retry one by one
        session.rollback()
    ids, dups = [], 0
    for r in results:
        if r["status"] != "valid":
            continue
        q = Question(pool=pool, category_id=r["category"].id, source=source, **r["data"])
        session.add(q)
        try:
            session.commit()
            ids.append(q.id)
        except IntegrityError:
            session.rollback()
            dups += 1
    return ids, dups


def store_detailed(session, category, pool, items, source="ai", check_time_sensitive=True):
    """Validate, de-duplicate and store raw question dicts for ONE category in ONE mode."""
    entries = [{"ref": i + 1, "category": category, "raw": raw, "errors": []} for i, raw in enumerate(items)]
    results = check_rows(session, pool, entries, check_time_sensitive)
    ids, race = insert_valid(session, pool, results, source)
    return {"inserted": len(ids), "ids": ids,
            "duplicates": sum(r["status"] == "duplicate" for r in results) + race,
            "invalid": sum(r["status"] == "invalid" for r in results),
            "problems": [{"ref": r["ref"], "status": r["status"], "reason": r["reason"]}
                         for r in results if r["status"] != "valid"]}


# ----------------------------------------------------------------------------- CSV
class CsvError(Exception):
    """A problem with the file as a whole (shown to the administrator)."""


def _norm_category(name):
    """Tolerant comparison key: Unicode NFC, no zero-width characters, collapsed spaces, case-insensitive."""
    name = unicodedata.normalize("NFC", name or "")
    name = re.sub("[\u200b\u200c\u200d\u2060\ufeff]", "", name)
    return re.sub(r"\s+", " ", name).strip().casefold()


def _category_lookup(session):
    """Dataset category name -> Category. Accepts the website name ("Kannada") and the dataset name
    (the Kannada-script name) for the SAME existing category; no second category is ever created."""
    out = {}
    for c in session.scalars(select(Category)):
        out[_norm_category(c.name)] = c
        out[_norm_category(dataset_name(c.name))] = c
    return out


def analyze_csv(session, data, filename, mode, selected_category=None, max_bytes=2 * 1024 * 1024, max_rows=2000):
    """Parse and validate an uploaded CSV for one quiz mode. Writes nothing. Returns a report dict whose
    ``results`` can be passed to insert_valid. Raises CsvError for whole-file problems."""
    if mode not in MODES:
        raise CsvError("Choose a valid quiz mode.")
    if not (filename or "").lower().endswith(".csv"):
        raise CsvError("Please upload a .csv file.")
    if not data:
        raise CsvError("The file is empty.")
    if len(data) > max_bytes:
        raise CsvError(f"The file is too large (limit {max_bytes // (1024 * 1024)} MB).")
    if b"\x00" in data:
        raise CsvError("This does not look like a text CSV file.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvError("The file must be saved as UTF-8 (in Excel: Save As > CSV UTF-8).")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
    except csv.Error as exc:
        raise CsvError(f"The CSV could not be read: {exc}")
    if header is None:
        raise CsvError("The file is empty.")
    header = [h.strip().lower() for h in header]
    extras = [h for h in header if h in ("id", "quiz_mode")]
    if extras:
        raise CsvError(f"The CSV must not contain these columns: {', '.join(extras)}. The database generates ids and the "
                       "quiz mode is chosen on this page.")
    if header != CSV_COLUMNS:
        raise CsvError("The header must be exactly these 8 columns, in this order: " + ", ".join(CSV_COLUMNS))
    categories = _category_lookup(session)
    entries, blank, prev_line = [], 0, reader.line_num
    try:
        for fields in reader:
            start_line = prev_line + 1
            prev_line = reader.line_num
            if not fields or all(not f.strip() for f in fields):
                blank += 1
                continue
            if len(entries) >= max_rows:
                raise CsvError(f"Too many rows (limit {max_rows} per file). Split the file and import it in parts.")
            errors, raw, cat = [], None, None
            if len(fields) != 8:
                errors.append(f"expected 8 columns but found {len(fields)}")
            else:
                raw = dict(zip(CSV_COLUMNS, [f.strip() for f in fields]))
                raw["question"] = raw["question_text"]
                for col in CSV_COLUMNS[:5] + ["explanation"]:
                    if not raw[col]:
                        errors.append(f"{col} is missing")
                if raw["correct_answer"] not in ("A", "B", "C", "D"):
                    errors.append("correct_answer must be exactly A, B, C or D")
                name = raw["category_name"]
                cat = categories.get(_norm_category(name)) if name else None
                if not name:
                    errors.append("category_name is missing")
                elif cat is None:
                    errors.append(f"unknown category_name \"{name}\"")
                elif selected_category is not None and cat.id != selected_category.id:
                    errors.append(f"category_name \"{name}\" does not match the selected category \"{selected_category.name}\"")
            entries.append({"ref": len(entries) + 1, "line": start_line, "category": cat, "raw": raw or {}, "errors": errors})
    except csv.Error as exc:
        raise CsvError(f"The CSV is malformed near line {reader.line_num}: {exc}")
    if not entries:
        raise CsvError("The file has a header but no questions.")
    # rows with problems already known skip validation but keep their place in the report
    ready = [e for e in entries if not e["errors"]]
    results_ready = iter(check_rows(session, mode, ready, check_time_sensitive=False))
    results = []
    for e in entries:
        if e["errors"]:
            results.append({"ref": e["ref"], "category": e["category"], "status": "invalid", "reason": "; ".join(e["errors"]),
                            "data": None, "line": e["line"]})
        else:
            r = next(results_ready)
            r["line"] = e["line"]
            results.append(r)
    counts = defaultdict(int)
    for r in results:
        counts[r["status"]] += 1
    return {"mode": mode, "total": len(results), "valid": counts["valid"], "invalid": counts["invalid"],
            "duplicates": counts["duplicate"], "blank_lines_ignored": blank, "results": results}


def public_report(report, limit_rows=50, limit_problems=100):
    """JSON-safe preview of an analyze_csv report."""
    def row(r):
        d = r["data"] or {}
        return {"row": r["ref"], "line": r["line"], "status": r["status"], "reason": r["reason"],
                "category": dataset_name(r["category"].name) if r["category"] else "",
                "question": (d.get("question_text") or "")[:160], "answer": d.get("correct_answer", "")}
    problems = [row(r) for r in report["results"] if r["status"] != "valid"]
    return {"mode": report["mode"], "mode_label": MODE_LABELS[report["mode"]], "total": report["total"],
            "valid": report["valid"], "invalid": report["invalid"], "duplicates": report["duplicates"],
            "blank_lines_ignored": report["blank_lines_ignored"],
            "preview": [row(r) for r in report["results"][:limit_rows]],
            "problems": problems[:limit_problems], "problems_truncated": len(problems) > limit_problems}


# ----------------------------------------------------------------------------- reads
def counts_by_mode(session):
    """{category_id: {'category': n, 'all': n, 'daily': n}} for every category."""
    out = {c.id: {m: 0 for m in MODES} for c in session.scalars(select(Category))}
    for cid, pool, n in session.execute(select(Question.category_id, Question.pool, func.count(Question.id))
                                        .group_by(Question.category_id, Question.pool)):
        out[cid][pool] = n
    return out


def questions_for(session, mode, category_id=None, page=1, page_size=20):
    """Questions of ONE mode (optionally one category), by id, with paging. Never mixes modes."""
    if mode not in MODES:
        raise ValueError("invalid mode")
    where = [Question.pool == mode] + ([Question.category_id == category_id] if category_id else [])
    total = session.scalar(select(func.count(Question.id)).where(*where)) or 0
    pages = max(1, -(-total // page_size))
    page = min(max(page, 1), pages)
    rows = session.execute(select(Question, Category.name).join(Category, Category.id == Question.category_id)
                           .where(*where).order_by(Question.id).limit(page_size).offset((page - 1) * page_size)).all()
    items = [{"id": q.id, "mode": q.pool, "category": name, "question": q.question_text, "options": q.options(),
              "correct_answer": q.correct_answer, "explanation": q.explanation, "source": q.source} for q, name in rows]
    return {"items": items, "page": page, "pages": pages, "total": total}


def export_csv(session, mode, category_id=None, ids=None):
    """The 8-column CSV of stored questions of ONE mode (optionally one category / specific ids), as UTF-8 with a BOM
    (Excel-friendly; the importer accepts it). category_name uses the dataset name (Kannada-script name for Kannada)."""
    if mode not in MODES:
        raise ValueError("invalid mode")
    where = [Question.pool == mode]
    if category_id:
        where.append(Question.category_id == category_id)
    if ids:
        where.append(Question.id.in_(ids))
    rows = session.execute(select(Question, Category.name).join(Category, Category.id == Question.category_id)
                           .where(*where).order_by(Question.id)).all()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for q, cname in rows:
        w.writerow([q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.correct_answer, q.explanation,
                    dataset_name(cname)])
    return ("\ufeff" + buf.getvalue()).encode("utf-8"), len(rows)
