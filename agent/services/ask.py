"""
Grounded Q&A over a course's syllabus + notes (full-context stuffing, per
CLAUDE.md — no retrieval/chunking in v1). Uses AsyncAnthropic so the DRF
async view can await it directly without blocking the ASGI event loop; the
management command wraps the same coroutine with asyncio.run() for standalone
CLI use.
"""

import json
import re

from asgiref.sync import sync_to_async

from . import sessions, storage
from .client import MODEL_DEFAULT as MODEL, get_client
from .storage import CourseNotFoundError

ASK_SYSTEM_PROMPT = """You answer questions about ONE course using ONLY the syllabus \
and notes provided below. That material is the entire knowledge base you have — \
there is nothing else to draw on.

Rules:
- Answer ONLY from the provided material. Never use outside/general knowledge, even \
if you're confident it's correct — the user needs to know what is and isn't actually \
in their course materials.
- If the answer isn't in the provided material, say so explicitly (e.g. "This isn't \
covered in the syllabus or notes I have for this course.") — do not guess, and do not \
answer as if it were the course's content.
- This applies to every turn of a multi-turn conversation, not just the first message. \
Earlier turns establishing a topic is not license to fill gaps from general knowledge \
later on — re-check each new question against the provided material on its own merits.
- A topic being NAMED in the material is not the same as the material ANSWERING a \
question about it. If the material only mentions a topic in passing — e.g. naming it \
and saying it's out of scope, or referencing it without explaining it — and the \
question asks you to explain, teach, or apply that topic, the material does not \
contain the answer. Say what the material does say about it (that's fine and often \
useful), but this is still an ungrounded answer: not fabricating anything is not the \
same as the material actually answering what was asked.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, \
no commentary.

Schema:
{
  "answer": "string",
  "grounded": true/false,
  "sources": ["syllabus" | "<lecture_id>", ...]
}

Notes on fields:
- "grounded" is true only if the material contains an actual answer to what was asked \
— not merely that everything you said is accurate and drawn from the text. A truthful, \
non-fabricated "the material doesn't cover this" is still grounded: false, since the \
question itself remains unanswered.
- "sources" lists which part(s) of the material the answer draws from: "syllabus" \
and/or the specific lecture_ids (from the notes) it was drawn from. Empty list when \
grounded is false.
"""


async def ask_async(course_id: str, question: str, session_id: str = None) -> dict:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    notes = await sync_to_async(storage.read_notes)(course_id)

    context = f"SYLLABUS:\n{json.dumps(syllabus, indent=2)}\n\n"
    if notes:
        context += f"NOTES:\n{json.dumps(notes, indent=2)}"
    else:
        context += "NOTES: none available yet for this course."

    session = None
    if session_id is not None:
        session = await sync_to_async(sessions.get_session)(course_id, session_id)
        if session is None:
            raise sessions.SessionNotFoundError(
                f"no session '{session_id}' found for course '{course_id}'"
            )

    # Multi-turn: the context (syllabus+notes) only needs to be stated once —
    # the whole message list is resent to the API every call, so it stays in
    # scope for every later turn. Prior turns are replayed as plain role/content
    # (not the JSON envelope the model emits) since that's all a turn needs to
    # carry forward as conversational context.
    messages = []
    if session and session["messages"]:
        prior = session["messages"]
        first = prior[0]
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {first['content']}"})
        for m in prior[1:]:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": question})
    else:
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {question}"})

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=ASK_SYSTEM_PROMPT,
        messages=messages,
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    result = {
        "answer": data.get("answer", ""),
        "grounded": bool(data.get("grounded", False)),
        "sources": data.get("sources", []),
    }

    if session_id is not None:
        await sync_to_async(sessions.append_message)(course_id, session_id, "user", question)
        await sync_to_async(sessions.append_message)(
            course_id, session_id, "assistant", result["answer"],
            sources=result["sources"], grounded=result["grounded"],
        )

    return result
