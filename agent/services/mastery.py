"""
Topic mastery scoring. EWMA (exponentially weighted moving average) scoring
with decay, always rebuilt from scratch by replaying quiz_history.json (the
append-only event log — source of truth) into mastery_scores.json (a
derived, disposable view — never hand-edited, never itself authoritative).

No async/API calls here — this is pure local computation, so unlike the
other services there's no client.py involvement.
"""

from datetime import datetime, timezone

from . import storage

ALPHA = 0.3  # weight given to the most recent attempt; higher = reacts faster to recent performance
NEUTRAL_SCORE = 0.5  # a topic's score before any attempts are recorded for it
WEAK_THRESHOLD = 0.4
STRONG_THRESHOLD = 0.7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_for_score(score: float) -> str:
    if score < WEAK_THRESHOLD:
        return "weak"
    if score >= STRONG_THRESHOLD:
        return "strong"
    return "developing"


def rebuild_scores(course_id: str) -> dict:
    """Replays quiz_history.json from scratch into mastery_scores.json. Safe
    to call repeatedly — this is a pure function of the event log, never
    incremental state that could drift from it."""
    history = storage.read_quiz_history(course_id)
    attempts = sorted(history.get("attempts", []), key=lambda a: a.get("timestamp") or "")

    running = {}  # topic -> {"score": float, "attempts": int, "last_seen": str}
    for a in attempts:
        topic = a.get("topic")
        if not topic:
            continue
        correct = 1.0 if a.get("correct") else 0.0
        state = running.setdefault(topic, {"score": NEUTRAL_SCORE, "attempts": 0, "last_seen": None})
        state["score"] = ALPHA * correct + (1 - ALPHA) * state["score"]
        state["attempts"] += 1
        state["last_seen"] = a.get("timestamp")

    scores = [
        {
            "topic": topic,
            "score": round(state["score"], 4),
            "attempts": state["attempts"],
            "last_seen": state["last_seen"],
            "status": _status_for_score(state["score"]),
        }
        for topic, state in running.items()
    ]
    scores.sort(key=lambda s: s["score"])  # weakest first — the useful default order for quiz.py's bias

    data = {"course_id": course_id, "rebuilt_at": _now(), "scores": scores}
    storage.write_mastery_scores(course_id, data)
    return data


def weak_topics(course_id: str, limit: int = None) -> list:
    """Returns this course's scored topics, weakest-first. [] if
    mastery_scores.json hasn't been built yet (call rebuild_scores() first) —
    that's a "no data yet" state distinct from "everything's strong", so
    callers shouldn't treat an empty result as good news without checking."""
    data = storage.read_mastery_scores(course_id)
    if data is None:
        return []
    scores = sorted(data.get("scores", []), key=lambda s: s["score"])
    return scores[:limit] if limit else scores
