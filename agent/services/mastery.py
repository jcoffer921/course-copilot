"""
Topic mastery scoring (v2). EWMA (exponentially weighted moving average)
scoring with decay, always rebuilt from scratch by replaying quiz_history (the
append-only event log — source of truth) into MasteryScore rows (a derived,
disposable view — never hand-edited, never itself authoritative).

v2 keeps the quiz-only EWMA numeric contract from v1 unchanged whenever a
topic has quiz attempts (quiz.py's chunk-picking weight, and any consumer
comparing scores over time, still see the same number) but blends in a
flashcard-rating signal when quiz data is absent or thin, and expands status
from three values (weak/developing/strong) into six that also account for
recency and attempt count: not_started, learning, needs_review, proficient,
at_risk, exam_ready. Each row also gets a short human-readable "reason" built
directly from the same facts used to pick its status.

No async/API calls here — this is pure local computation, so unlike the
other services there's no client.py involvement.
"""

from datetime import datetime, timezone
from django.db import transaction

from . import storage

ALPHA = 0.3  # weight given to the most recent quiz attempt; higher = reacts faster to recent performance
NEUTRAL_SCORE = 0.5  # a topic's quiz score before any quiz attempts are recorded for it
WEAK_THRESHOLD = 0.4
STRONG_THRESHOLD = 0.7
EXAM_READY_THRESHOLD = 0.85

MIN_ATTEMPTS_PROFICIENT = 3
MIN_ATTEMPTS_EXAM_READY = 5
AT_RISK_STALE_DAYS = 14

# Quiz correctness is a more rigorous signal than a self-rated flashcard, so
# it dominates the blend whenever both exist for a topic.
QUIZ_WEIGHT_WHEN_BOTH = 0.7
FLASHCARD_WEIGHT_WHEN_BOTH = 0.3

NOT_STARTED = "not_started"
LEARNING = "learning"
NEEDS_REVIEW = "needs_review"
PROFICIENT = "proficient"
AT_RISK = "at_risk"
EXAM_READY = "exam_ready"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value) -> datetime:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _days_since(last_seen_iso, now: datetime):
    parsed = _parse_iso(last_seen_iso)
    if parsed is None:
        return None
    return max(0, (now - parsed).days)


def _quiz_scores_by_topic(course_id: str, user) -> dict:
    """Replays quiz_history in chronological order into an EWMA per topic —
    identical math to v1, so a topic with only quiz attempts gets exactly the
    same `score` it always has."""
    history = storage.read_quiz_history(course_id, user=user)
    attempts = sorted(history.get("attempts", []), key=lambda a: a.get("timestamp") or "")

    running = {}
    for a in attempts:
        topic = a.get("topic")
        if not topic:
            continue
        correct = 1.0 if a.get("correct") else 0.0
        state = running.setdefault(topic, {"score": NEUTRAL_SCORE, "attempts": 0, "last_seen": None})
        state["score"] = ALPHA * correct + (1 - ALPHA) * state["score"]
        state["attempts"] += 1
        state["last_seen"] = a.get("timestamp")
    return running


def _combine(quiz_state: dict, flashcard_state: dict) -> dict:
    """Blends a topic's quiz EWMA (if any) with its flashcard rating average
    (if any) into one score/attempts/last_seen. Either input may be absent —
    a topic with only one kind of activity uses that signal alone, so this
    never changes the v1 quiz-only result for a topic with no flashcards."""
    quiz_score = quiz_state["score"] if quiz_state else None
    quiz_attempts = quiz_state["attempts"] if quiz_state else 0
    flashcard_score = flashcard_state["avg_rating"] if flashcard_state else None
    flashcard_count = flashcard_state["count"] if flashcard_state else 0

    if quiz_attempts and flashcard_count:
        score = round(QUIZ_WEIGHT_WHEN_BOTH * quiz_score + FLASHCARD_WEIGHT_WHEN_BOTH * flashcard_score, 4)
    elif quiz_attempts:
        score = round(quiz_score, 4)
    else:
        score = round(flashcard_score, 4)

    last_seen_candidates = [v for v in (
        quiz_state["last_seen"] if quiz_state else None,
        flashcard_state["last_reviewed"] if flashcard_state else None,
    ) if v]
    last_seen = max(last_seen_candidates) if last_seen_candidates else None

    return {
        "score": score,
        "attempts": quiz_attempts + flashcard_count,
        "last_seen": last_seen,
    }


def _status_and_reason(score: float, attempts: int, last_seen_iso, now: datetime) -> tuple[str, str]:
    # attempts is always >= 1 here: rebuild_scores() only ever builds a row
    # for a topic that has at least one quiz attempt or one rated flashcard.
    # A topic with neither never gets a MasteryScore row at all — callers
    # that need to represent "no data yet" (recommendations.py, for topics
    # pulled from a syllabus rather than mastery's own output) use
    # NOT_STARTED directly rather than calling this function.
    pct = round(score * 100)
    stale_days = _days_since(last_seen_iso, now)

    if score < WEAK_THRESHOLD:
        return LEARNING, f"{pct}% mastery over {attempts} attempt(s) — still building understanding."

    if score < STRONG_THRESHOLD:
        return NEEDS_REVIEW, f"{pct}% mastery over {attempts} attempt(s) — needs more practice."

    # score >= STRONG_THRESHOLD from here on.
    if stale_days is not None and stale_days > AT_RISK_STALE_DAYS:
        return AT_RISK, f"{pct}% mastery, but not reviewed in {stale_days} days — due for a refresh before it fades."

    if attempts < MIN_ATTEMPTS_PROFICIENT:
        return NEEDS_REVIEW, f"{pct}% mastery so far, but only {attempts} attempt(s) — a few more will confirm it."

    if score >= EXAM_READY_THRESHOLD and attempts >= MIN_ATTEMPTS_EXAM_READY:
        return EXAM_READY, f"{pct}% mastery over {attempts} attempts, reviewed recently — ready for an exam on this topic."

    return PROFICIENT, f"{pct}% mastery over {attempts} attempts — solid understanding."


def rebuild_scores(course_id: str, user=None, now: datetime = None) -> dict:
    """Replays quiz_history and current flashcard ratings from scratch into
    MasteryScore rows. Safe to call repeatedly — this is a pure function of
    those two inputs, never incremental state that could drift from them.

    `now` is injectable so recency-driven status (at_risk) is deterministic
    under a fixed clock in tests; defaults to the real current time."""
    now = now or datetime.now(timezone.utc)
    with transaction.atomic():
        if getattr(user, "is_authenticated", False):
            user.__class__.objects.select_for_update().get(pk=user.pk)
        return _rebuild_scores_locked(course_id, user, now)


def _rebuild_scores_locked(course_id: str, user, now: datetime) -> dict:
    """Replay and publish while the authenticated owner's rebuild lock is held."""
    quiz_by_topic = _quiz_scores_by_topic(course_id, user=user)
    flashcard_by_topic = storage.flashcard_topic_stats(course_id, user=user)

    scores = []
    for topic in set(quiz_by_topic) | set(flashcard_by_topic):
        combined = _combine(quiz_by_topic.get(topic), flashcard_by_topic.get(topic))
        status, reason = _status_and_reason(combined["score"], combined["attempts"], combined["last_seen"], now)
        scores.append({
            "topic": topic,
            "score": combined["score"],
            "attempts": combined["attempts"],
            "last_seen": combined["last_seen"],
            "status": status,
            "reason": reason,
        })
    scores.sort(key=lambda s: s["score"])  # weakest first — the useful default order for quiz.py's bias

    data = {"course_id": course_id, "rebuilt_at": _now(), "scores": scores}
    storage.write_mastery_scores(course_id, data, user=user)
    return data


def weak_topics(course_id: str, limit: int = None, user=None) -> list:
    """Returns this course's scored topics, weakest-first. [] if mastery
    hasn't been built yet (call rebuild_scores() first) — that's a "no data
    yet" state distinct from "everything's strong", so callers shouldn't
    treat an empty result as good news without checking."""
    data = storage.read_mastery_scores(course_id, user=user)
    if data is None:
        return []
    scores = sorted(data.get("scores", []), key=lambda s: s["score"])
    return scores[:limit] if limit else scores
