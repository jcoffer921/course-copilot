"""
Quiz generation from a course's chunked notes, with wrong-answer tracking
into quiz_history.json (the append-only event log mastery.py replays).
Every recorded attempt triggers an immediate mastery rebuild, so
mastery_scores.json never lags behind what's actually been answered.
"""

import json
import random
import re
from datetime import datetime, timezone

from asgiref.sync import sync_to_async

from . import mastery, storage
from .client import MODEL_DEFAULT as MODEL, get_client
from .storage import CourseNotFoundError

QUIZ_SYSTEM_PROMPT = """You write ONE multiple-choice quiz question from a single \
chunk of course material. The question must be answerable using ONLY the \
provided chunk text — never test knowledge the chunk doesn't contain, and \
never pad with generic textbook facts about the topic that aren't stated in \
this specific chunk.

Rules:
- Write exactly one question with exactly 4 answer choices, exactly one of \
which is correct.
- The correct answer and all three distractors must be plausible — don't \
make wrong answers obviously silly filler. A student who only skimmed the \
chunk should have to actually think, not guess by elimination.
- Do not ask about anything not explicitly stated in the provided chunk.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown \
fences, no commentary.

Schema:
{
  "question": "string",
  "choices": ["string", "string", "string", "string"],
  "correct_answer": "string"
}

"correct_answer" must be an exact copy of one of the four "choices" strings.
"""


class NoChunksAvailableError(Exception):
    """Raised when there's nothing to quiz from yet — no chunked notes exist
    for this course (or for the requested topic/chunk)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _all_chunks(course_id: str) -> list:
    """Returns [{"lecture_id", "chunk_id", "topic", "text"}, ...] flattened
    across every lecture's chunked notes for this course."""
    chunks = []
    for lecture in storage.read_notes(course_id):
        for c in lecture.get("chunks", []):
            chunks.append({
                "lecture_id": lecture.get("lecture_id"),
                "chunk_id": c.get("id"),
                "topic": c.get("topic"),
                "text": c.get("text"),
            })
    return chunks


def pick_chunk(course_id: str, topic: str = None) -> dict:
    """Picks a chunk to quiz next. If topic is given, only considers chunks
    for that topic. Otherwise biases toward the weakest scored topic (per
    mastery.weak_topics) that actually has chunks available, falling back to
    any random chunk when there's no mastery data yet (a brand-new course
    has nothing to bias from)."""
    chunks = _all_chunks(course_id)
    if not chunks:
        raise NoChunksAvailableError(f"no chunked notes found for course '{course_id}' — run chunk_notes first")

    if topic:
        matching = [c for c in chunks if c["topic"] == topic]
        if not matching:
            raise NoChunksAvailableError(f"no chunks found for topic {topic!r} in course '{course_id}'")
        return random.choice(matching)

    for w in mastery.weak_topics(course_id):  # weakest first
        matching = [c for c in chunks if c["topic"] == w["topic"]]
        if matching:
            return random.choice(matching)

    return random.choice(chunks)


async def generate_question_async(course_id: str, topic: str = None, chunk_id: str = None) -> dict:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    if chunk_id:
        chunks = await sync_to_async(_all_chunks)(course_id)
        chunk = next((c for c in chunks if c["chunk_id"] == chunk_id), None)
        if chunk is None:
            raise NoChunksAvailableError(f"no chunk '{chunk_id}' found for course '{course_id}'")
    else:
        chunk = await sync_to_async(pick_chunk)(course_id, topic)

    user_prompt = f"Chunk text:\n---\n{chunk['text']}\n---"

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=QUIZ_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    choices = data.get("choices", [])
    correct_answer = data.get("correct_answer", "")
    if correct_answer not in choices:
        raise ValueError(f"model's correct_answer isn't among its own choices: {data}")

    return {
        "lecture_id": chunk["lecture_id"],
        "chunk_id": chunk["chunk_id"],
        "topic": chunk["topic"],
        "question": data.get("question", ""),
        "choices": choices,
        "correct_answer": correct_answer,
    }


def record_attempt(
    course_id: str, lecture_id: str, chunk_id: str, topic: str,
    question: str, correct_answer: str, user_answer: str,
) -> dict:
    """Logs one quiz attempt to quiz_history.json and immediately rebuilds
    mastery_scores.json from it, so mastery is always current with what's
    actually been answered — callers never need to remember to rebuild."""
    correct = user_answer == correct_answer

    attempt = {
        "lecture_id": lecture_id,
        "chunk_id": chunk_id,
        "topic": topic,
        "question": question,
        "correct_answer": correct_answer,
        "user_answer": user_answer,
        "correct": correct,
        "timestamp": _now(),
    }
    storage.append_quiz_attempt(course_id, attempt)
    mastery.rebuild_scores(course_id)

    return {"correct": correct, "correct_answer": correct_answer}
