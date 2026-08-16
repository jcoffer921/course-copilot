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

ASK_SYSTEM_PROMPT = """You answer questions about ONE course using ONLY the material provided below, \
plus — only when that material genuinely doesn't cover the question — real, cited results from a \
restricted web search when one is available to you. There is nothing else to draw on: never answer \
from general/training knowledge as if it were this course's material.

Grounding tiers, in order:
1. Answer from SYLLABUS, NOTES, and REFERENCES first, always. These are this course's own real \
material and take priority over everything else.
2. Only if that material genuinely doesn't cover the question, and only if a web_search tool is \
available to you, you may search the web — restricted to the domains you've been given access to. \
If no web_search tool is available, you have no other source: say the material doesn't cover it.
3. Every claim sourced from the web must be cited with its real URL, and your answer must make clear \
which parts (if any) came from outside the course's own material — never blend a web result into an \
answer as if it were the course's own syllabus, notes, or reference material.

Rules:
- Answer ONLY from the provided material and, when used, real cited web search results — never use \
outside/general knowledge, even if you're confident it's correct — the user needs to know what is and \
isn't actually grounded in real material.
- If the answer isn't covered by the provided material or an available, permitted web search, say so \
explicitly (e.g. "This isn't covered in the syllabus, notes, or references I have for this course.") \
— do not guess, and do not answer as if it were the course's content.
- This applies to every turn of a multi-turn conversation, not just the first message. Earlier turns \
establishing a topic is not license to fill gaps from general knowledge later on — re-check each new \
question against the provided material (and, if used, real search results) on its own merits.
- A topic being NAMED in the material is not the same as the material ANSWERING a question about it. \
If the material only mentions a topic in passing — e.g. naming it and saying it's out of scope, or \
referencing it without explaining it — and the question asks you to explain, teach, or apply that \
topic, the material does not contain the answer. Say what the material does say about it (that's fine \
and often useful), but this is still an ungrounded answer unless a permitted web search fills the gap: \
not fabricating anything is not the same as the material actually answering what was asked.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary — \
this applies even if you use the web search tool first: your final visible response must be nothing \
but this JSON object.

Schema:
{
  "answer": "string",
  "grounded": true/false,
  "sources": ["syllabus" | "<lecture_id>" | "<reference_id>" | "<full URL>", ...]
}

Notes on fields:
- "grounded" is true when the material contains an actual answer to what was asked, OR when a \
permitted web search returned a real, cited, allowed-domain result that answers it — not merely that \
everything you said is accurate. A truthful, non-fabricated "this isn't covered" is still grounded: \
false, since the question itself remains unanswered.
- "sources" lists which part(s) of the material — and/or which cited web result(s) — the answer draws \
from: "syllabus", specific lecture_ids (from NOTES), specific reference_ids (from REFERENCES), and/or \
full URLs (from a permitted web search). Empty list when grounded is false.
"""


MAX_PAUSE_TURN_CONTINUATIONS = 3


async def ask_async(course_id: str, question: str, session_id: str = None) -> dict:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    notes = await sync_to_async(storage.read_notes)(course_id)
    references = await sync_to_async(storage.read_references)(course_id)
    approved_domains = await sync_to_async(storage.read_trusted_domains)(course_id)

    context = f"SYLLABUS:\n{json.dumps(syllabus, indent=2)}\n\n"
    if notes:
        context += f"NOTES:\n{json.dumps(notes, indent=2)}\n\n"
    else:
        context += "NOTES: none available yet for this course.\n\n"
    if references:
        context += f"REFERENCES:\n{json.dumps(references, indent=2)}"
    else:
        context += "REFERENCES: none available yet for this course."

    session = None
    if session_id is not None:
        session = await sync_to_async(sessions.get_session)(course_id, session_id)
        if session is None:
            raise sessions.SessionNotFoundError(
                f"no session '{session_id}' found for course '{course_id}'"
            )

    # Multi-turn: the context (syllabus+notes+references) only needs to be
    # stated once — the whole message list is resent to the API every call,
    # so it stays in scope for every later turn. Prior assistant turns are
    # replayed in the same JSON envelope the system prompt demands (not the
    # plain answer text) — otherwise the model's own conversation history
    # shows it answering in plain prose on earlier turns, and it drifts away
    # from the required JSON format on later ones despite the system prompt
    # repeating the instruction every call (confirmed in practice: turn 2 of
    # a session failed JSON parsing once this replayed as plain text).
    messages = []
    if session and session["messages"]:
        prior = session["messages"]
        first = prior[0]
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {first['content']}"})
        for m in prior[1:]:
            if m["role"] == "assistant":
                envelope = json.dumps({
                    "answer": m["content"],
                    "grounded": m.get("grounded", False),
                    "sources": m.get("sources", []),
                })
                messages.append({"role": "assistant", "content": envelope})
            else:
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": question})
    else:
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {question}"})

    # No domains approved for this course yet means the agent stays scoped to
    # course material only, same as it does today — the web_search tool is
    # simply never offered, rather than failing or (worse) searching
    # unrestricted.
    tools = []
    if approved_domains:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "allowed_domains": approved_domains,
        })

    create_kwargs = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": ASK_SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools

    response = await client.messages.create(**create_kwargs)

    # web_search is a server-side tool — the API runs its own internal search
    # loop and returns results in this same response, so no client-side
    # tool_use/tool_result loop is needed here. If that internal loop hits
    # its default iteration cap mid-search, the API returns stop_reason
    # "pause_turn" instead of finishing; resending the conversation (not a
    # "Continue" message — the API detects the trailing search state itself)
    # lets it pick back up. Capped so a stuck search can't loop forever.
    continuations = 0
    while response.stop_reason == "pause_turn" and continuations < MAX_PAUSE_TURN_CONTINUATIONS:
        messages = messages + [{"role": "assistant", "content": response.content}]
        create_kwargs["messages"] = messages
        response = await client.messages.create(**create_kwargs)
        continuations += 1

    text_blocks = [block.text for block in response.content if block.type == "text"]
    raw = text_blocks[-1].strip() if text_blocks else ""
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
