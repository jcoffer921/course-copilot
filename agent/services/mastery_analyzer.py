"""Interprets (never computes) mastery data. agent/services/mastery.py owns
the deterministic EWMA scoring — this module only reasons over the pattern
across recent quiz attempts that a topic's score summarizes.

See agent/services/cora_skills/mastery_analyzer.py for the full routing
contract and validation rules this implements.
"""

import json

from asgiref.sync import sync_to_async

from . import mastery, quiz
from .client import CORA_MODELS, get_client
from .cora_json import parse_model_json

SYSTEM_PROMPT = """You are Cora's mastery-interpretation tool for OnTrack. You are given a topic's \
deterministically-computed mastery score(s) plus the student's actual recent quiz attempts for that \
topic (question/correct_answer/user_answer/correct). Your job is to explain the PATTERN behind the \
numbers, not to recompute or restate them.

Classify what a wrong answer actually reflects, the same three ways OnTrack's quiz pipeline does:
- Concept gap: a genuine misunderstanding of the underlying idea (wrong mechanism, wrong definition, \
confused two related concepts).
- Carelessness/slip: the student's answer suggests they know the material but made an unrelated error \
(misread the question, right concept named incorrectly).
- Ambiguous/poorly-scoped question: the wrong answer is defensible given the question's phrasing.

Rules:
- Never state a pattern the supplied attempts don't actually support — if there are too few attempts \
to see a real pattern, say so plainly rather than inventing one.
- Never default every miss to "concept gap" just because it's the safe-sounding assumption — look at \
each user_answer's actual content.
- Don't infer a broader pattern across an entire unit/course from a handful of attempts on one topic.
- "confidence" must reflect how much attempt data actually exists — low with only one or two attempts.
- "recommended_action" should be one concrete next step (e.g. "review base-case recursion definitions \
before attempting more tracing problems"), not generic encouragement.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{"insight": "string", "recommended_action": "string", "confidence": "high|medium|low"}
"""


class NoMasteryDataError(Exception):
    """Raised when there's no mastery/quiz-attempt data yet to interpret."""


def _build_context(course_id: str, topic: str, user) -> tuple[list, list]:
    scores = mastery.weak_topics(course_id, user=user)
    if topic:
        scores = [row for row in scores if row["topic"] == topic]

    attempts = quiz.recent_attempts(course_id, limit=200, user=user)
    if topic:
        attempts = [a for a in attempts if a.get("topic") == topic]
    return scores, attempts[:15]


async def analyze(user, course_id: str, topic: str = None) -> dict:
    scores, attempts = await sync_to_async(_build_context)(course_id, topic, user)
    if not scores and not attempts:
        target = f"course '{course_id}'" + (f", topic '{topic}'" if topic else "")
        raise NoMasteryDataError(f"no mastery data yet for {target}")

    client = get_client()
    context = {"mastery_scores": scores, "recent_attempts": attempts}
    response = await client.messages.create(
        model=CORA_MODELS["reasoning"],
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(context, default=str)}],
    )
    raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    data = parse_model_json(raw, required_keys={"insight", "recommended_action", "confidence"})
    confidence = data.get("confidence") if data.get("confidence") in {"high", "medium", "low"} else "low"
    return {
        "insight": str(data.get("insight", "")).strip(),
        "recommended_action": str(data.get("recommended_action", "")).strip(),
        "confidence": confidence,
    }
