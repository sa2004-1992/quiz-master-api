"""Deterministic question sequencing and progress pointers.

Pointers are indexes into an ordered, stable question list (ORDER BY id).
* Quiz Type 1: pointer into the category's own list; wraps modulo the list size.
* Quiz Type 2: one global counter ``g``; position g -> category ``g % C`` (C=56, in the required
  order), round ``g // C``, question ``round % len(category_questions)``.
"""


def category_slice(ids, pointer, count):
    """Return (question_ids, raw_positions) for a category game."""
    n = len(ids)
    if n == 0:
        return [], []
    if pointer >= n:
        pointer %= n
    count = min(count, n)  # never repeat a question inside one game
    positions = [pointer + i for i in range(count)]
    return [ids[p % n] for p in positions], positions


def next_category_pointer(last_position, n):
    """Pointer after consuming up to raw position ``last_position`` (inclusive)."""
    nxt = last_position + 1
    if n and nxt > n:
        nxt %= n
    return nxt


def all_quiz_slice(ordered_category_ids, ids_by_category, pointer, count):
    """Return (question_ids, positions, categories_needing_more).

    ``categories_needing_more`` lists category ids whose stored questions are exhausted (or empty)
    for the rounds touched, so the caller can try to generate more before wrapping.
    """
    c_total = len(ordered_category_ids)
    qids, positions, needs, seen = [], [], [], set()
    scan_limit = pointer + c_total * 3
    g = pointer
    while len(qids) < count and g < scan_limit:
        cat_id = ordered_category_ids[g % c_total]
        rnd = g // c_total
        ids = ids_by_category.get(cat_id, [])
        if not ids:
            if cat_id not in needs:
                needs.append(cat_id)
        else:
            if rnd >= len(ids) and cat_id not in needs:
                needs.append(cat_id)
            qid = ids[rnd % len(ids)]
            if qid not in seen:
                seen.add(qid)
                qids.append(qid)
                positions.append(g)
        g += 1
    return qids, positions, needs
