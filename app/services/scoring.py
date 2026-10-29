"""Scoring rules (server-side only)."""
POINTS_CORRECT = 10
POINTS_INCORRECT = -5


def points_for(is_correct: bool, hint_used: bool) -> int:
    """Nominal points for one resolved question. Hints never change the score."""
    if hint_used:
        return 0
    return POINTS_CORRECT if is_correct else POINTS_INCORRECT


def running_scores(points_in_order):
    """Cumulative score after each answer, never dropping below zero."""
    total, out = 0, []
    for p in points_in_order:
        total = max(0, total + p)
        out.append(total)
    return out


def final_score(points_in_order) -> int:
    scores = running_scores(points_in_order)
    return scores[-1] if scores else 0
