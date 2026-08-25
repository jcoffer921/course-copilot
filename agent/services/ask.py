"""
Grounded Q&A over a course's syllabus + notes (full-context stuffing, per
CLAUDE.md — no retrieval/chunking in v1). Uses AsyncAnthropic so the DRF
async view can await it directly without blocking the ASGI event loop; the
management command wraps the same coroutine with asyncio.run() for standalone
CLI use.
"""

import json
import re
from datetime import date
from urllib.parse import urlparse

from asgiref.sync import sync_to_async

from . import grades, mastery, sessions, storage
from .client import MODEL_DEFAULT as MODEL, MODEL_HAIKU, get_client
from .storage import CourseNotFoundError

ASK_SYSTEM_PROMPT = """You are Cora, the AI academic assistant inside OnTrack — you help students stay on top of their \
semester. You answer questions about ONE course using ONLY the material provided below, plus — only \
when that material genuinely doesn't cover the question — real, cited results from a restricted web \
search when one is available to you. There is nothing else to draw on: never answer from \
general/training knowledge as if it were this course's material.

Identity and tone: If asked who you are or what you do, answer briefly and naturally as Cora — an \
assistant that helps organize syllabi, notes, deadlines, and answers grounded questions about a \
student's courses. Keep your "answer" text supportive and encouraging, like a well-organized study \
partner — clear and direct, never padded with filler or excessive enthusiasm. This identity and tone \
guidance never overrides the grounding rules below, and never justifies adding anything to the JSON \
output beyond the "answer" field itself.

Response style — the "answer" text is rendered as markdown, so formatting is safe to use, but use it \
with judgment:
- Match depth to the question. A broad, open-ended ask ("tell me about this course", "what's this \
class like") gets a short, natural overview — hit the highlights and offer to go deeper on grading, \
deadlines, or a specific topic if they want, rather than dumping every syllabus field at once. A \
specific question ("what's my grade breakdown", "when's the project due") gets the specific, complete \
answer, in full, without holding anything back.
- Write like a knowledgeable study partner talking to the student, not a data printout — warm and \
direct, never robotic or padded.
- Use **bold** for emphasis, blank lines between distinct ideas, "- " bullet lists for enumerable \
items, and a markdown pipe table only when the data is genuinely tabular with several rows (e.g. a \
full grading breakdown) — not for two or three facts that read fine as a sentence.
- Use markdown section headings sparingly when an answer has multiple sections, with headings like \
`## From your notes` and `## Outside course material`. Do not use emoji in headings. Avoid \
horizontal rules unless the answer is long enough to need section breaks.
- Do not include raw XML/HTML citation tags such as `<cite ...>...</cite>` in the answer text. \
Paraphrase or quote briefly in normal markdown, then put the actual full URLs in the JSON "sources" \
array.
- Keep it scannable: short paragraphs, no walls of text.

Grounding tiers, in order:
1. Answer from SYLLABUS, NOTES, REFERENCES, SAVED_SITES, RECALLED_CONVERSATIONS, and LEARNING_TOOLS \
first, always. These are this course's own real material and saved OnTrack data, including saved site \
addresses, relevant earlier chat excerpts, quiz attempts, mastery scores, flashcard progress, entered \
grades, and grade-calculator results. SAVED_SITES contain only URL metadata, not page contents; you may \
provide or identify a saved URL, but do not summarize or quote that page unless its contents are \
otherwise available in REFERENCES/NOTES or a permitted web search result. RECALLED_CONVERSATIONS are \
memory of earlier chats for this same course; use them for continuity, user preferences, prior decisions, \
and previously discussed details. Do not treat a recalled assistant message as an independent source for \
course facts unless its sources are also available or cited.
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
  "sources": ["syllabus" | "<lecture_id>" | "<reference_id>" | "saved_sites" | "recalled_conversations" | "quiz_history" | "mastery_scores" | "flashcards" | "grades" | "grade_calculator" | "<full URL>", ...]
}

Notes on fields:
- "grounded" is true when the material contains an actual answer to what was asked, OR when a \
permitted web search returned a real, cited, allowed-domain result that answers it — not merely that \
everything you said is accurate. A truthful, non-fabricated "this isn't covered" is still grounded: \
false, since the question itself remains unanswered.
- "sources" lists which part(s) of the material — and/or which cited web result(s) — the answer draws \
from: "syllabus", specific lecture_ids (from NOTES), specific reference_ids (from REFERENCES), \
"saved_sites" or full saved URLs (from SAVED_SITES), "recalled_conversations" (from earlier same-course \
chat excerpts), "quiz_history", "mastery_scores", "flashcards", "grades", "grade_calculator", and/or \
full URLs (from a permitted web search). Empty list when grounded is false.
"""


MAX_PAUSE_TURN_CONTINUATIONS = 3
WEB_SEARCH_MAX_USES = 5
DEADLINE_INTENT_RE = re.compile(r"\b(add|create|schedule|put|make)\b.*\b(deadline|homework|hw|project|quiz|test|exam|class|event)\b", re.I)
SAVE_SITE_INTENT_RE = re.compile(r"\b(save|remember|store|add)\b.*\b(site|link|url|address|book|textbook)\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.I)


def _parse_json_response(raw: str) -> dict:
    """Parses the model's JSON response, tolerating a leading preamble the
    model adds despite being told not to (verified in practice: Cora
    sometimes explains a limitation in prose before the JSON when no tool
    use follows to trigger ask_async's post-tool-use text-block trim).
    Finds the first '{' and decodes from there with a streaming JSON
    decoder, so anything before it — and any trailing text after the object
    closes — is ignored rather than breaking the parse."""
    start = raw.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found in model output", raw, 0)
    obj, _ = json.JSONDecoder().raw_decode(raw, start)
    return obj


DEADLINE_EXTRACTION_PROMPT = """Extract a calendar deadline/event request for OnTrack.

Return ONLY valid JSON:
{
  "is_deadline_request": true,
  "missing": ["title"|"date"|"course_id"],
  "deadline": {
    "title": "string",
    "course_id": "string|null",
    "date": "YYYY-MM-DD",
    "time": "HH:MM|null",
    "end_time": "HH:MM|null",
    "type": "hw|project|test_quiz|class|other"
  },
  "message": "short confirmation or follow-up question"
}

Rules:
- Use the supplied current course when the user does not name another course.
- Use null course_id only when the user clearly says it is general/all courses.
- If a required field is missing or ambiguous, put it in missing and ask for it in message.
- Do not invent dates. If the date is relative, resolve it using today's date.
- Map homework/assignment/problem set to hw, exam/test/quiz to test_quiz, lectures/classes/meetings to class.
"""


def _build_web_search_tool(approved_domains: list[str]) -> dict | None:
    if not approved_domains:
        return None
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": approved_domains,
        "max_uses": WEB_SEARCH_MAX_USES,
    }


def _domains_from_saved_sites(saved_sites: list[dict]) -> list[str]:
    domains = []
    for site in saved_sites or []:
        parsed = urlparse(site.get("url") or "")
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            domains.append(parsed.netloc.lower())
    return domains


def _merge_allowed_domains(*domain_lists: list[str]) -> list[str]:
    seen = set()
    merged = []
    for domains in domain_lists:
        for domain in domains or []:
            normalized = str(domain or "").strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                merged.append(normalized)
    return merged


def _looks_like_deadline_request(question: str) -> bool:
    return bool(DEADLINE_INTENT_RE.search(question or ""))


def _looks_like_save_site_request(question: str) -> bool:
    text = question or ""
    if "?" in text:
        # A question mark means the user is asking something, not just issuing
        # a save command — even one that also mentions a save-verb and a URL
        # (e.g. "remember the textbook site <url> and tell me if ... ?").
        # Fall through to normal grounded Q&A rather than silently swallowing it.
        return False
    return bool(URL_RE.search(text) and SAVE_SITE_INTENT_RE.search(text))


def _title_for_saved_site(question: str, url: str) -> str:
    quoted = re.findall(r"[\"']([^\"']{1,255})[\"']", question or "")
    quoted = [q.strip() for q in quoted if q.strip() and url not in q]
    if quoted:
        return quoted[-1]

    without_url = (question or "").replace(url, " ")
    as_match = re.search(r"\bas\s+(.+)$", without_url, re.I)
    if as_match:
        title = re.sub(r"[.?!]\s*$", "", as_match.group(1)).strip()
        if title:
            return title[:255]

    lower = (question or "").lower()
    if "textbook" in lower:
        return "Textbook"
    if "book" in lower:
        return "Course Book"

    parsed = urlparse(url)
    return parsed.netloc or "Saved Site"


def _extract_save_site_request(question: str) -> dict:
    match = URL_RE.search(question or "")
    if not match:
        raise ValueError("no URL found to save")
    url = match.group(0).rstrip(".,;:!?)\"]}'")
    return {
        "url": url,
        "title": _title_for_saved_site(question, url),
    }


def _recent_quiz_attempts(course_id: str, user=None, limit: int = 20) -> list:
    history = storage.read_quiz_history(course_id, user=user)
    attempts = sorted(history.get("attempts", []), key=lambda a: a.get("timestamp") or "", reverse=True)
    return attempts[:limit]


def _flashcard_summary(course_id: str, user=None, limit: int = 80) -> dict:
    progress = storage.read_flashcard_progress(course_id, user=user)
    cards = progress.get("cards", {})
    by_status = {"not_started": 0, "in_progress": 0, "mastered": 0}
    starred_count = 0
    visible_cards = []

    for key, card in cards.items():
        status = card.get("status") if card.get("status") in {"in_progress", "mastered"} else "not_started"
        by_status[status] += 1
        if card.get("starred"):
            starred_count += 1
        if len(visible_cards) < limit:
            visible_cards.append({
                "key": key,
                "term": card.get("term", ""),
                "definition": card.get("definition", ""),
                "status": status,
                "starred": bool(card.get("starred", False)),
                "updated_at": card.get("updated_at"),
            })

    return {
        "counts": by_status,
        "starred_count": starred_count,
        "cards": visible_cards,
        "truncated": len(cards) > limit,
    }


def _grade_tool_context(course_id: str, user=None) -> dict:
    current = grades.current_grade(course_id, user=user)
    items = storage.read_grades(course_id, user=user)["items"]
    target_pcts = [60, 70, 80, 90]
    overall = current.get("overall_pct")
    if overall is not None:
        target_pcts = sorted({pct for pct in target_pcts if pct > overall} | {round(overall, 2)})

    targets = []
    for target in target_pcts[:5]:
        targets.append({
            "target_pct": target,
            "grade_needed": grades.grade_needed(course_id, target, user=user),
            "missable_by_category": grades.missable_by_category(course_id, target, user=user),
        })

    return {
        "current_grade": current,
        "entered_items": items,
        "precomputed_targets": targets,
        "calculator_note": (
            "current_grade excludes categories with no entered items. "
            "grade_needed estimates the same score needed on every remaining item for a target percent."
        ),
    }


def _learning_tools_context(course_id: str, user=None) -> dict:
    context = {
        "quiz": {},
        "flashcards": {},
        "grades": {},
    }

    try:
        context["quiz"] = {
            "recent_attempts": _recent_quiz_attempts(course_id, user=user),
            "mastery_scores": mastery.weak_topics(course_id, user=user),
        }
    except storage.QuizStorageError as e:
        context["quiz"] = {"error": str(e)}

    try:
        context["flashcards"] = _flashcard_summary(course_id, user=user)
    except storage.FlashcardProgressStorageError as e:
        context["flashcards"] = {"error": str(e)}

    try:
        context["grades"] = _grade_tool_context(course_id, user=user)
    except (storage.CourseNotFoundError, storage.GradesStorageError, ValueError) as e:
        context["grades"] = {"error": str(e)}

    return context


async def _extract_deadline_request(client, question: str, course_id: str, syllabus: dict) -> dict:
    today = date.today().isoformat()
    course_context = {
        "current_course_id": course_id,
        "current_course_name": syllabus.get("course_name") or course_id,
        "today": today,
        "allowed_categories": ["hw", "project", "test_quiz", "class", "other"],
    }
    response = await client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=1000,
        system=DEADLINE_EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": f"Context:\n{json.dumps(course_context)}\n\nUser request:\n{question}"}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"deadline extraction did not return valid JSON: {e}\n\nRaw output:\n{raw}")
    deadline = data.get("deadline") or {}
    category = storage.normalize_date_type(deadline.get("type"))
    pending = {
        "title": str(deadline.get("title") or "").strip(),
        "course_id": deadline.get("course_id") if deadline.get("course_id") is not None else course_id,
        "date": str(deadline.get("date") or "").strip(),
        "time": deadline.get("time") or None,
        "end_time": deadline.get("end_time") or None,
        "type": category,
        "completed": False,
    }
    missing = [m for m in data.get("missing", []) if m in {"title", "date", "course_id"}]
    if not pending["title"] and "title" not in missing:
        missing.append("title")
    if not pending["date"] and "date" not in missing:
        missing.append("date")
    return {
        "answer": data.get("message") or ("I can add this deadline after you confirm the details." if not missing else "I need a little more detail before I can add that deadline."),
        "grounded": True,
        "sources": ["syllabus"],
        "pending_deadline": None if missing else pending,
        "deadline_missing": missing,
    }


async def ask_async(course_id: str, question: str, session_id: str = None, user=None) -> dict:
    syllabus = await sync_to_async(storage.read_syllabus)(course_id, user)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    if _looks_like_save_site_request(question):
        request = _extract_save_site_request(question)
        site = await sync_to_async(storage.save_site)(
            course_id, request["url"], title=request["title"], user=user,
        )
        answer = (
            f"Saved **{site['title']}** for this course: {site['url']}\n\n"
            "I only stored the address, not the page contents."
        )
        result = {
            "answer": answer,
            "grounded": True,
            "sources": [site["url"]],
            "saved_site": site,
        }
        if session_id is not None:
            await sync_to_async(sessions.append_message)(course_id, session_id, "user", question, user=user)
            await sync_to_async(sessions.append_message)(
                course_id, session_id, "assistant", result["answer"],
                sources=result["sources"], grounded=result["grounded"], user=user,
            )
        return result

    client = get_client()

    if _looks_like_deadline_request(question):
        result = await _extract_deadline_request(client, question, course_id, syllabus)
        if session_id is not None:
            await sync_to_async(sessions.append_message)(course_id, session_id, "user", question, user=user)
            await sync_to_async(sessions.append_message)(
                course_id, session_id, "assistant", result["answer"],
                sources=result["sources"], grounded=result["grounded"], user=user,
            )
        return result

    notes = await sync_to_async(storage.read_notes)(course_id, user)
    references = await sync_to_async(storage.read_references)(course_id, user)
    saved_sites = await sync_to_async(storage.list_saved_sites)(course_id, user=user)
    recalled_conversations = await sync_to_async(sessions.relevant_messages)(
        course_id, question, session_id=session_id, user=user,
    )
    approved_domains = await sync_to_async(storage.read_trusted_domains)(course_id, user)
    allowed_domains = _merge_allowed_domains(approved_domains, _domains_from_saved_sites(saved_sites))
    learning_tools = await sync_to_async(_learning_tools_context)(course_id, user=user)

    context = f"SYLLABUS:\n{json.dumps(syllabus, indent=2)}\n\n"
    if notes:
        context += f"NOTES:\n{json.dumps(notes, indent=2)}\n\n"
    else:
        context += "NOTES: none available yet for this course.\n\n"
    if references:
        context += f"REFERENCES:\n{json.dumps(references, indent=2)}\n\n"
    else:
        context += "REFERENCES: none available yet for this course.\n\n"
    if saved_sites:
        context += (
            "SAVED_SITES:\n"
            f"{json.dumps(saved_sites, indent=2)}\n\n"
            "Saved sites are URL metadata only. Their page contents have not been stored.\n\n"
        )
    else:
        context += "SAVED_SITES: none available yet for this course.\n\n"
    if recalled_conversations:
        context += (
            "RECALLED_CONVERSATIONS:\n"
            f"{json.dumps(recalled_conversations, indent=2)}\n\n"
        )
    else:
        context += "RECALLED_CONVERSATIONS: no relevant earlier conversations found for this course.\n\n"
    context += f"LEARNING_TOOLS:\n{json.dumps(learning_tools, indent=2, default=str)}"

    session = None
    if session_id is not None:
        session = await sync_to_async(sessions.get_session)(course_id, session_id, user=user)
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
    # The context block (syllabus+notes+references+...) is identical across
    # every question in a session and often across separate stateless calls
    # for the same course within the cache TTL — a cache_control breakpoint
    # after it (kept in its own content block, separate from the question
    # that follows) lets repeated/back-to-back questions reuse it at cache
    # read pricing instead of paying full input price every time.
    def _context_message(role_content: str) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": f"\n\nQuestion: {role_content}"},
            ],
        }

    messages = []
    if session and session["messages"]:
        prior = session["messages"]
        first = prior[0]
        messages.append(_context_message(first["content"]))
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
        messages.append(_context_message(question))

    # No domains approved for this course yet means the agent stays scoped to
    # course material only, same as it does today — the web_search tool is
    # simply never offered, rather than failing or (worse) searching
    # unrestricted.
    tools = []
    web_search_tool = _build_web_search_tool(allowed_domains)
    if web_search_tool:
        tools.append(web_search_tool)

    create_kwargs = {
        "model": MODEL,
        "max_tokens": 2048,
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

    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"response truncated at max_tokens before completing the JSON answer "
            f"(stop_reason={response.stop_reason})"
        )

    last_non_text = max((i for i, b in enumerate(response.content) if b.type != "text"), default=-1)
    raw = "".join(
        block.text for block in response.content[last_non_text + 1:] if block.type == "text"
    ).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = _parse_json_response(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    result = {
        "answer": data.get("answer", ""),
        "grounded": bool(data.get("grounded", False)),
        "sources": data.get("sources", []),
    }

    if session_id is not None:
        await sync_to_async(sessions.append_message)(course_id, session_id, "user", question, user=user)
        await sync_to_async(sessions.append_message)(
            course_id, session_id, "assistant", result["answer"],
            sources=result["sources"], grounded=result["grounded"], user=user,
        )

    return result
