"""
Quiz generation from a course's chunked notes, with wrong-answer tracking
into quiz_history.json (the append-only event log mastery.py replays).
Every recorded attempt triggers an immediate mastery rebuild, so
mastery_scores.json never lags behind what's actually been answered.
"""

import json
import random
import re
from html import unescape
from datetime import datetime, timezone

from asgiref.sync import sync_to_async

from . import mastery, storage
from .client import MODEL_DEFAULT as MODEL_ASSESSMENT, MODEL_HAIKU, get_client
from .storage import CourseNotFoundError

FLASHCARD_SYSTEM_PROMPT = """You are the low-cost data gatherer and flashcard maker for OnTrack. \
Create quick, definition-focused study flashcards from the provided course material and, only when \
web_search is available, from the scoped web results for the approved domains.

Rules:
- Prefer concise vocabulary, API names, concepts, and distinctions a student should memorize.
- Use the provided course chunk first. Use web search only to fill in compact definitions or context \
that directly matches the chunk's topic.
- Keep each card short: one term, one direct definition, and optionally one source label or URL.
- Do not include raw XML/HTML citation tags such as <cite ...>...</cite> in term or definition text.
- If web_search returns cited text, write the definition as plain student-facing text and put the URL in "url".
- Do not make advanced exam questions here. These are lightweight recall cards.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "flashcards": [
    {"term": "string", "definition": "string", "source": "course|web|course+web", "url": "string|null"}
  ]
}
"""


ASSESSMENT_SYSTEM_PROMPT = """You are the assessment specialist for OnTrack. Write ONE \
quiz question from the provided source material. The question must require understanding, \
discrimination, or application — not just matching a vocabulary word to its definition.

Rules:
- Respect the requested question_type.
- For multiple_choice, write exactly 4 answer choices, exactly one of which is correct.
- For true_false, write a statement-style question and use choices ["True", "False"].
- For open_ended, write no choices and provide a concise expected answer.
- For multiple_choice, the correct answer and all three distractors must be plausible — don't make wrong answers obviously silly filler.
- Do not ask about anything not supported by the provided source material.
- If flashcards are provided, use them as vocabulary/source context for the question, but do not \
write a simple "What does TERM mean?" card check unless the source material cannot support anything \
more advanced.
- Write a short "explanation" (one or two sentences) of why the correct answer is correct, \
grounded only in the provided source material.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown \
fences, no commentary.

Schema:
{
  "question": "string",
  "question_type": "multiple_choice|true_false|open_ended",
  "choices": ["string"],
  "correct_answer": "string",
  "explanation": "string"
}

"correct_answer" must be an exact copy of one choice when choices are present.
"""


WEB_SEARCH_MAX_USES = 3


class NoChunksAvailableError(Exception):
    """Raised when there's nothing to quiz from yet — no chunked notes exist
    for this course (or for the requested topic/chunk)."""


class InvalidChunkReferenceError(Exception):
    """Raised when a quiz submission references a lecture/chunk that isn't
    actually part of this course for this user — blocks forging quiz/mastery
    history against a chunk from another course or another user's data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    raw = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()
    decoder = json.JSONDecoder()
    candidates = [raw]
    candidates += [raw[i:] for i, ch in enumerate(raw) if ch == "{"]
    last_error = None
    for candidate in candidates:
        try:
            data, _ = decoder.raw_decode(candidate.strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as e:
            last_error = e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {last_error or e}\n\nRaw output:\n{raw}")


def clean_flashcard_text(value: str) -> str:
    """Removes model/web-search citation markup from student-facing card text."""
    text = unescape(str(value or ""))
    text = re.sub(r"<\s*cite\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*/\s*cite\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_flashcard_url(value) -> str | None:
    text = clean_flashcard_text(value)
    markdown_link = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text)
    if markdown_link:
        text = markdown_link.group(2)
    return text if text.startswith(("http://", "https://")) else None


def _build_web_search_tool(approved_domains: list[str]) -> dict | None:
    if not approved_domains:
        return None
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": approved_domains,
        "max_uses": WEB_SEARCH_MAX_USES,
    }


def _all_chunks(course_id: str, user) -> list:
    """Returns [{"lecture_id", "chunk_id", "topic", "text"}, ...] flattened
    across every lecture's chunked notes for this course."""
    chunks = []
    for lecture in storage.read_notes(course_id, user):
        for c in lecture.get("chunks", []):
            chunks.append({
                "lecture_id": lecture.get("lecture_id"),
                "chunk_id": c.get("id"),
                "topic": c.get("topic"),
                "text": c.get("text"),
            })
    return chunks


def _topic_quiz_weight(score) -> float:
    """Lower mastery scores should be sampled more often, but strong topics
    should not disappear entirely. Unassessed topics sit between weak and
    developing so new material gets exposure without drowning out known weak
    spots."""
    if score is None:
        return 3.5
    try:
        normalized = max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        return 3.5
    return max(0.35, ((1.0 - normalized) ** 2) * 8.0 + 0.35)


def pick_chunk(course_id: str, topic: str = None, user=None) -> dict:
    """Picks a chunk to quiz next. If topic is given, only considers chunks
    for that topic. Otherwise samples by topic mastery: weak topics get much
    higher weight, developing topics moderate weight, and strong topics low
    but nonzero weight."""
    chunks = _all_chunks(course_id, user)
    if not chunks:
        raise NoChunksAvailableError(f"no chunked notes found for course '{course_id}' — run chunk_notes first")

    if topic:
        matching = [c for c in chunks if c["topic"] == topic]
        if not matching:
            raise NoChunksAvailableError(f"no chunks found for topic {topic!r} in course '{course_id}'")
        return random.choice(matching)

    chunks_by_topic = {}
    for chunk in chunks:
        chunk_topic = chunk.get("topic") or "Untitled topic"
        chunks_by_topic.setdefault(chunk_topic, []).append(chunk)

    scored_topics = {
        row.get("topic"): row
        for row in mastery.weak_topics(course_id, user=user)
        if row.get("topic")
    }
    topic_names = list(chunks_by_topic.keys())
    topic_weights = [
        _topic_quiz_weight(scored_topics.get(topic_name, {}).get("score"))
        for topic_name in topic_names
    ]

    if topic_names:
        chosen_topic = random.choices(topic_names, weights=topic_weights, k=1)[0]
        return random.choice(chunks_by_topic[chosen_topic])

    return random.choice(chunks)


async def generate_question_async(course_id: str, topic: str = None, chunk_id: str = None, user=None) -> dict:
    return await generate_assessment_question_async(course_id, topic=topic, chunk_id=chunk_id, user=user)


async def generate_flashcards_async(
    course_id: str, topic: str = None, chunk_id: str = None, count: int = 8, user=None,
) -> dict:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id, user)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    if chunk_id:
        chunks = await sync_to_async(_all_chunks)(course_id, user)
        chunk = next((c for c in chunks if c["chunk_id"] == chunk_id), None)
        if chunk is None:
            raise NoChunksAvailableError(f"no chunk '{chunk_id}' found for course '{course_id}'")
    else:
        chunk = await sync_to_async(pick_chunk)(course_id, topic, user=user)

    approved_domains = await sync_to_async(storage.read_trusted_domains)(course_id, user)
    user_prompt = (
        f"Course: {syllabus.get('course_name', course_id)}\n"
        f"Topic: {chunk['topic']}\n"
        f"Desired flashcard count: {max(1, min(int(count or 8), 12))}\n\n"
        f"Course chunk text:\n---\n{chunk['text']}\n---"
    )

    create_kwargs = {
        "model": MODEL_HAIKU,
        "max_tokens": 2048,
        "system": FLASHCARD_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    web_search_tool = _build_web_search_tool(approved_domains)
    if web_search_tool:
        create_kwargs["tools"] = [web_search_tool]

    response = await client.messages.create(**create_kwargs)
    last_non_text = max((i for i, b in enumerate(response.content) if b.type != "text"), default=-1)
    raw = "".join(
        block.text for block in response.content[last_non_text + 1:] if block.type == "text"
    ).strip()
    data = _parse_json(raw)

    flashcards = []
    for card in data.get("flashcards", []):
        if not isinstance(card, dict):
            continue
        term = clean_flashcard_text(card.get("term", ""))
        definition = clean_flashcard_text(card.get("definition", ""))
        if not term or not definition:
            continue
        source = str(card.get("source") or "course").strip()
        url = clean_flashcard_url(card.get("url"))
        flashcards.append({
            "term": term,
            "definition": definition,
            "source": source if source in {"course", "web", "course+web"} else "course",
            "url": url,
        })

    if not flashcards:
        raise ValueError(f"model did not return any usable flashcards: {data}")

    await sync_to_async(storage.remember_generated_flashcards)(course_id, flashcards, user=user, topic=chunk["topic"])

    return {
        "lecture_id": chunk["lecture_id"],
        "chunk_id": chunk["chunk_id"],
        "topic": chunk["topic"],
        "model": MODEL_HAIKU,
        "flashcards": flashcards,
    }


async def generate_assessment_question_async(
    course_id: str, topic: str = None, chunk_id: str = None, flashcards: list = None,
    question_type: str = "multiple_choice", previous_questions: list[str] = None, user=None,
) -> dict:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id, user)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    chunks = None
    if chunk_id:
        chunks = await sync_to_async(_all_chunks)(course_id, user)
        chunk = next((c for c in chunks if c["chunk_id"] == chunk_id), None)
        if chunk is None:
            raise NoChunksAvailableError(f"no chunk '{chunk_id}' found for course '{course_id}'")
    else:
        chunk = await sync_to_async(pick_chunk)(course_id, topic, user=user)

    previous_normalized = {
        re.sub(r"\s+", " ", str(q or "").strip()).casefold()
        for q in (previous_questions or [])
        if str(q or "").strip()
    }

    last_data = None
    for attempt_index in range(3):
        if attempt_index and not chunk_id:
            chunk = await sync_to_async(pick_chunk)(course_id, topic, user=user)

        flashcard_context = flashcards
        if flashcard_context is None:
            try:
                deck = await generate_flashcards_async(course_id, topic=topic, chunk_id=chunk["chunk_id"], count=6, user=user)
                flashcard_context = deck["flashcards"]
            except ValueError:
                flashcard_context = []

        user_prompt = (
            f"Course: {syllabus.get('course_name', course_id)}\n"
            f"Topic: {chunk['topic']}\n\n"
            f"question_type: {question_type}\n\n"
            f"Questions already asked in this quiz. Do not repeat these exactly or rephrase the same idea:\n"
            f"{json.dumps(previous_questions or [], indent=2)}\n\n"
            f"Course chunk text:\n---\n{chunk['text']}\n---\n\n"
            f"Haiku-generated flashcards to use as vocabulary/source context:\n"
            f"{json.dumps(flashcard_context or [], indent=2)}"
        )

        response = await client.messages.create(
            model=MODEL_ASSESSMENT,
            max_tokens=1024,
            system=ASSESSMENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw = "".join(block.text for block in response.content if block.type == "text").strip()
        data = _parse_json(raw)
        last_data = data
        candidate_question = re.sub(r"\s+", " ", str(data.get("question", "")).strip()).casefold()
        if not candidate_question or candidate_question not in previous_normalized:
            break
    else:
        data = last_data or {}

    normalized_type = data.get("question_type") or question_type
    if normalized_type not in {"multiple_choice", "true_false", "open_ended"}:
        normalized_type = question_type if question_type in {"multiple_choice", "true_false", "open_ended"} else "multiple_choice"
    choices = data.get("choices", [])
    if normalized_type == "true_false":
        choices = ["True", "False"]
    if normalized_type == "open_ended":
        choices = []
    correct_answer = data.get("correct_answer", "")
    question_text = str(data.get("question", "")).strip()
    if not question_text:
        raise ValueError(f"model did not return a question: {data}")
    if normalized_type == "multiple_choice":
        if not isinstance(choices, list) or len(choices) != 4:
            raise ValueError(f"model must return exactly four multiple-choice answers: {data}")
        if any(not isinstance(choice, str) or not choice.strip() for choice in choices):
            raise ValueError(f"model returned an invalid multiple-choice answer: {data}")
        if len({choice.strip().casefold() for choice in choices}) != 4:
            raise ValueError(f"model returned duplicate multiple-choice answers: {data}")
    if choices and correct_answer not in choices:
        raise ValueError(f"model's correct_answer isn't among its own choices: {data}")
    if not correct_answer:
        raise ValueError(f"model did not return a correct_answer: {data}")

    return {
        "lecture_id": chunk["lecture_id"],
        "chunk_id": chunk["chunk_id"],
        "topic": chunk["topic"],
        "mode": "assessment",
        "question_type": normalized_type,
        "model": MODEL_ASSESSMENT,
        "question": question_text,
        "choices": choices,
        "correct_answer": correct_answer,
        "explanation": clean_flashcard_text(data.get("explanation", "")),
    }


def record_attempt(
    course_id: str, lecture_id: str, chunk_id: str, topic: str,
    question: str, correct_answer: str, user_answer: str, user=None,
) -> dict:
    """Logs one quiz attempt to quiz_history.json and immediately rebuilds
    mastery_scores.json from it, so mastery is always current with what's
    actually been answered — callers never need to remember to rebuild.

    Validates lecture_id/chunk_id resolve to a real chunk this user's course
    actually has, so a submission can't forge quiz/mastery history against a
    chunk from another course (or another user's course, since chunk lookup
    is already user-scoped)."""
    chunks = _all_chunks(course_id, user)
    if not any(c["lecture_id"] == lecture_id and c["chunk_id"] == chunk_id for c in chunks):
        raise InvalidChunkReferenceError(
            f"chunk '{chunk_id}' in lecture '{lecture_id}' does not belong to course '{course_id}'"
        )

    def normalized_answer(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    correct = normalized_answer(user_answer) == normalized_answer(correct_answer)

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
    storage.append_quiz_attempt(course_id, attempt, user=user)
    mastery.rebuild_scores(course_id, user=user)

    return {"correct": correct, "correct_answer": correct_answer}


def recent_attempts(course_id: str, limit: int = 10, user=None) -> list:
    """Most recent quiz attempts for this course, newest first."""
    history = storage.read_quiz_history(course_id, user=user)
    attempts = sorted(history.get("attempts", []), key=lambda a: a.get("timestamp") or "", reverse=True)
    return attempts[:limit]
