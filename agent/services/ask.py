"""
Grounded Q&A over a course's syllabus + notes (full-context stuffing, per
CLAUDE.md — no retrieval/chunking in v1). Uses AsyncAnthropic so the DRF
async view can await it directly without blocking the ASGI event loop; the
management command wraps the same coroutine with asyncio.run() for standalone
CLI use.
"""

import json
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from asgiref.sync import sync_to_async

from . import calendar_events, citations, custom_events, grades, mastery, sessions, storage
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
- You are a tutor, not just a lookup tool. When a student asks to understand, study, practice, or \
compare a concept, teach from the course material: break the idea into steps, call out likely \
confusions, and include one or two short examples derived from the provided syllabus, notes, \
references, saved course data, or recalled course conversation. Make the examples concrete, but do \
not introduce facts or techniques that are not supported by the course material unless a permitted, \
cited web result supplies them.
- Use diagrams when they would make the answer easier to learn, especially for processes, pipelines, \
state transitions, comparisons, dependencies, algorithms, and cause/effect chains. Diagrams must also \
be grounded in the provided course material. Put each diagram in a fenced mermaid block using simple \
flowchart syntax, for example:
```mermaid
flowchart TD
  A[Course concept] --> B[Next step]
  B --> C[Result]
```
Keep diagram labels short and readable. Explain the diagram in nearby text rather than relying on it \
alone. Do not wrap fenced diagram blocks in bold, italics, inline backticks, or extra markdown markers.
- For two-set visual examples like union, intersection, difference, complement, or DeMorgan's laws, \
prefer a fenced venn block instead of Mermaid so visual learners get a picture-style diagram. Use this \
format:
```venn
operation: union
a: A
b: B
universe: U
caption: A union B includes anything in A or B.
```
Allowed operation values are `union`, `intersection`, `a_minus_b`, `b_minus_a`, and `complement_a`. \
Only use labels and captions that are supported by the course material or by a permitted cited source. \
The opening fence must be exactly ```venn on its own line and the closing fence must be exactly ``` on \
its own line.
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
- Output ONLY valid JSON matching the schema below. Do not wrap the JSON object in a markdown fence, \
and do not add preamble or commentary outside it — this applies even if you use the web search tool \
first. Mermaid and Venn fences are allowed only inside the JSON "answer" string when you include a diagram.

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
- Use only the exact source labels present in the supplied context. OnTrack resolves these labels to \
owned material IDs and excerpts after your response; never invent a source label.
"""


MAX_PAUSE_TURN_CONTINUATIONS = 3
WEB_SEARCH_MAX_USES = 5
CLASS_SCHEDULE_WEEKS = 15
MAX_CALENDAR_ACTIONS = 150
CALENDAR_WRITE_TOOL_NAME = "propose_calendar_changes"
DEADLINE_INTENT_RE = re.compile(
    r"("
    r"\b(add|create|schedule|put|make|remember|remind)\b[\s\S]*\b(deadline|due|homework|hw|assignment|project|quiz|test|exam|class|event|meeting|presentation|lab|calendar)\b"
    r"|"
    r"\b(deadline|homework|hw|assignment|project|quiz|test|exam|event|meeting|presentation|lab)\b[\s\S]*\b(is due|due|on|at)\b"
    r"|"
    r"\b(class|lecture|lab|seminar|course)\b[\s\S]*\b(meets|meeting|schedule|scheduled|every|mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|mwf|tth|tu/th|tues/thurs)\b"
    r"|"
    r"\b(meets|meeting|schedule|scheduled|every)\b[\s\S]*\b(mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|mwf|tth|tu/th|tues/thurs)\b"
    r"|"
    r"\b(move|reschedule|push|change|update|edit|shift|postpone)\b[\s\S]*\b(deadline|due|homework|hw|assignment|project|quiz|test|exam|class|event|meeting|presentation|lab|calendar|it|that|this)\b"
    r"|"
    r"\b(delete|remove|cancel)\b[\s\S]*\b(deadline|due|homework|hw|assignment|project|quiz|test|exam|class|event|meeting|presentation|lab|calendar|it|that|this)\b"
    r"|"
    r"\b(add|put)\b[\s\S]*\b(to|on)\b[\s\S]*\bcalendar\b"
    r")",
    re.I,
)
SAVE_SITE_INTENT_RE = re.compile(r"\b(save|remember|store|add)\b.*\b(site|link|url|address|book|textbook)\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.I)


def _decode_loose_json_string(value: str) -> str:
    text = value or ""
    text = text.replace(r"\/", "/")
    text = text.replace(r"\\", "\\")
    text = text.replace(r"\"", '"')
    text = text.replace(r"\n", "\n")
    text = text.replace(r"\r", "\r")
    text = text.replace(r"\t", "\t")
    text = re.sub(r'\\(?!["\\/bfnrtu])', "", text)
    return text


def _parse_loose_answer_response(raw: str) -> dict | None:
    """Recover the common Cora final-answer shape when the model leaves
    unescaped quotes inside the answer string, e.g. `"Not (A or B)"`.
    This is intentionally narrow and only handles answer/grounded/sources."""
    match = re.search(
        r'"answer"\s*:\s*"(.*)"\s*,\s*"grounded"\s*:\s*(true|false)\s*,\s*"sources"\s*:\s*(\[[\s\S]*?\])',
        raw or "",
        re.S,
    )
    if not match:
        return None
    sources_raw = re.sub(r'\\(?!["\\/bfnrtu])', "", match.group(3))
    try:
        sources = json.loads(sources_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(sources, list):
        return None
    return {
        "answer": _decode_loose_json_string(match.group(1)),
        "grounded": match.group(2) == "true",
        "sources": sources,
    }


def _parse_json_response(raw: str) -> dict:
    """Parses the model's JSON response, tolerating a leading preamble the
    model adds despite being told not to (verified in practice: Cora
    sometimes explains a limitation in prose before the JSON when no tool
    use follows to trigger ask_async's post-tool-use text-block trim).
    Searches every object start, preferring response-shaped objects, so
    examples like `A = {1, 2, 3}` in a preamble do not break parsing."""
    decoder = json.JSONDecoder()
    last_error = None
    fallback = None

    for match in reversed(list(re.finditer(r"{", raw or ""))):
        start = match.start()
        candidate = raw[start:]
        for text in (candidate, re.sub(r'\\(?!["\\/bfnrtu])', "", candidate)):
            try:
                obj, _ = decoder.raw_decode(text)
            except json.JSONDecodeError as e:
                last_error = e
                continue
            if not isinstance(obj, dict):
                continue
            fallback = obj
            if (
                "answer" in obj
                or "is_deadline_request" in obj
                or "deadline" in obj
                or "deadlines" in obj
            ):
                return obj

    if fallback is not None:
        return fallback
    loose = _parse_loose_answer_response(raw)
    if loose is not None:
        return loose
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("no JSON object found in model output", raw or "", 0)


DEADLINE_EXTRACTION_PROMPT = """Use the propose_calendar_changes tool to prepare a calendar action request for \
OnTrack: adding a new deadline/event, editing an existing one, or removing one. The tool only prepares a \
proposal. It does not write anything. The student must review and explicitly confirm every proposed change \
before OnTrack applies it.

Rules:
- "action" is "create" for a brand-new deadline/event, "update" to change an existing one's date/time/title, \
or "delete" to remove one. Default to "create" when the user is clearly describing something new.
- For "update"/"delete", you are given EXISTING_DEADLINES (id/title/date/time/type/source) for this course. \
Match the user's reference (e.g. "my project deadline", "the midterm") to the single best existing item by \
title and context, and set "event_id" to its exact id. Still fill in "title"/"date"/"type" from that matched \
item (carrying forward whatever the user isn't changing) so the proposal is a complete, resolved record.
- If you cannot confidently match a unique existing item for an update/delete (none look right, or more than \
one plausibly matches), do NOT guess — put "event_match" in missing and ask which one they mean in message, \
listing the plausible candidates by title and date.
- For "update", only include the fields that should change plus whatever is needed to keep the record \
complete — do not silently drop a field that isn't changing.
- Use the supplied current course when the user does not name another course.
- Use null course_id only when the user clearly says it is general/all courses.
- If a required field is missing or ambiguous, put it in missing and ask for it in message.
- Do not invent dates. If the date is relative, resolve it using today's date.
- Treat "remind me", "remember", "put this on my calendar", "add this to deadlines", and "I have X due/on/at Y" as create requests, and "move"/"reschedule"/"push back"/"change" as update requests, and "delete"/"remove"/"cancel" as delete requests, whenever they contain enough event intent.
- Map homework/assignment/problem set to hw, exam/test/quiz to test_quiz, lectures/classes/meetings to class, presentations/projects to project, and meetings/labs/other events to other unless the user clearly gives a course category.
- For recurring college class schedules with multiple meeting days (for example MWF, Tuesdays/Thursdays, Mon and Wed), return one "create" item per meeting in "deadlines". Use the supplied schedule_start_date/schedule_end_date and create meetings for the full schedule_weeks window. Include only meetings on or after today.
- If the user gives exact semester start/end dates, use those dates instead of the default schedule window.
- Return every proposed item in the tool's "deadlines" array, including when there is only one item.
- If nothing is missing, message should briefly describe the action (e.g. "Move Project 1 to Oct 3?") and ask the user to confirm — never say it's already done, since nothing is written until the user confirms.
"""


def _build_calendar_write_tool() -> dict:
    """Build Cora's side-effect-free, plan-before-write calendar tool."""
    nullable_string = {"type": ["string", "null"]}
    action_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update", "delete"]},
            "event_id": nullable_string,
            "title": {"type": "string"},
            "course_id": nullable_string,
            "date": {"type": "string"},
            "time": nullable_string,
            "end_time": nullable_string,
            "type": {"type": "string", "enum": ["hw", "project", "test_quiz", "class", "other"]},
        },
        "required": ["action", "event_id", "title", "course_id", "date", "time", "end_time", "type"],
        "additionalProperties": False,
    }
    return {
        "name": CALENDAR_WRITE_TOOL_NAME,
        "description": (
            "Prepare create, update, or delete actions for the student's OnTrack calendar. "
            "This tool proposes changes only; OnTrack shows them to the student and writes "
            "nothing until the student explicitly confirms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "is_deadline_request": {"type": "boolean", "const": True},
                "missing": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["title", "date", "course_id", "event_match"]},
                    "uniqueItems": True,
                },
                "deadlines": {"type": "array", "items": action_schema, "maxItems": MAX_CALENDAR_ACTIONS},
                "message": {"type": "string"},
            },
            "required": ["is_deadline_request", "missing", "deadlines", "message"],
            "additionalProperties": False,
        },
    }


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


def _normalize_pending_deadline(raw: dict, default_course_id: str) -> dict:
    deadline = raw if isinstance(raw, dict) else {}
    action = deadline.get("action") if deadline.get("action") in {"create", "update", "delete"} else "create"
    return {
        "action": action,
        "event_id": str(deadline["event_id"]) if deadline.get("event_id") else None,
        "title": str(deadline.get("title") or "").strip(),
        "course_id": deadline.get("course_id") if deadline.get("course_id") is not None else default_course_id,
        "date": str(deadline.get("date") or "").strip(),
        "time": deadline.get("time") or None,
        "end_time": deadline.get("end_time") or None,
        "type": storage.normalize_date_type(deadline.get("type")),
        "completed": False,
    }


def _existing_deadlines_context(course_id: str, user=None, limit: int = 60) -> list:
    """Trimmed, id-bearing list of this course's real deadlines (syllabus +
    manual), so the extraction model can resolve "my project deadline" to a
    specific event_id for update/delete instead of guessing blind. Ownership
    is enforced independently server-side when the action is actually
    confirmed (calendar_events.all_events is already user-scoped) — this
    context is only ever used to help the model pick the right reference,
    never trusted as the source of authorization."""
    events = calendar_events.all_events(user, course_ids=[course_id])
    events = sorted(events, key=lambda e: e.get("date") or "")[:limit]
    return [
        {"id": e["id"], "title": e["title"], "date": e["date"], "time": e.get("time"), "type": e["type"], "source": e["source"]}
        for e in events
    ]


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


async def _structure_result_sources(
    result: dict, course_id: str, question: str, user=None, session_id: str = None,
) -> dict:
    result = dict(result)
    if not isinstance(result.get("answer"), str) or not result["answer"].strip():
        raise ValueError("Cora returned an invalid answer.")
    if not isinstance(result.get("grounded"), bool):
        raise ValueError("Cora returned an invalid grounded value.")
    source_labels = citations.validate_source_labels(result.get("sources"))
    if not result.get("grounded"):
        result["sources"] = []
        return result
    result["sources"] = await sync_to_async(citations.resolve_citations)(
        user,
        course_id,
        source_labels,
        question,
        result.get("answer", ""),
        session_id,
    )
    return result


async def _extract_deadline_request(client, question: str, course_id: str, syllabus: dict, user=None) -> dict:
    today_date = date.today()
    days_since_sunday = (today_date.weekday() + 1) % 7
    week_start = today_date - timedelta(days=days_since_sunday)
    week_end = week_start + timedelta(days=6)
    schedule_end = week_start + timedelta(days=(CLASS_SCHEDULE_WEEKS * 7) - 1)
    existing_deadlines = await sync_to_async(_existing_deadlines_context)(course_id, user=user)
    course_context = {
        "current_course_id": course_id,
        "current_course_name": syllabus.get("course_name") or course_id,
        "today": today_date.isoformat(),
        "current_week_start": week_start.isoformat(),
        "current_week_end": week_end.isoformat(),
        "schedule_weeks": CLASS_SCHEDULE_WEEKS,
        "schedule_start_date": week_start.isoformat(),
        "schedule_end_date": schedule_end.isoformat(),
        "allowed_categories": ["hw", "project", "test_quiz", "class", "other"],
        "existing_deadlines": existing_deadlines,
    }
    response = await client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=8000,
        system=DEADLINE_EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": f"Context:\n{json.dumps(course_context)}\n\nUser request:\n{question}"}],
        tools=[_build_calendar_write_tool()],
        tool_choice={"type": "tool", "name": CALENDAR_WRITE_TOOL_NAME},
    )
    tool_blocks = [
        block for block in response.content
        if getattr(block, "type", None) == "tool_use"
        and getattr(block, "name", None) == CALENDAR_WRITE_TOOL_NAME
    ]
    if len(tool_blocks) > 1:
        raise ValueError("Cora returned more than one calendar proposal.")
    if tool_blocks:
        data = getattr(tool_blocks[0], "input", None)
        if not isinstance(data, dict):
            raise ValueError("Cora returned an invalid calendar proposal.")
    else:
        # Compatibility with recorded responses created before the calendar
        # tool contract. New production calls force tool use above.
        raw = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            data = _parse_json_response(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"calendar tool did not return valid input: {e}\n\nRaw output:\n{raw}")

    if not isinstance(data.get("missing", []), list):
        raise ValueError("Cora returned invalid missing calendar fields.")
    raw_deadlines = data.get("deadlines")
    if not isinstance(raw_deadlines, list):
        # Compatibility with the former single-item extraction response.
        raw_deadline = data.get("deadline")
        raw_deadlines = [raw_deadline] if isinstance(raw_deadline, dict) else []
    if len(raw_deadlines) > MAX_CALENDAR_ACTIONS or any(not isinstance(raw, dict) for raw in raw_deadlines):
        raise ValueError("Cora returned an invalid number or shape of calendar actions.")
    pending_deadlines = [_normalize_pending_deadline(raw, course_id) for raw in raw_deadlines]
    for pending in pending_deadlines:
        conflicts = []
        if pending["action"] in ("create", "update") and pending["date"] and pending["time"]:
            # Cross-course by design (course_ids=None inside detect_conflicts'
            # all_events() call) — a double-booking with a different course's
            # event is exactly the kind of thing that must be surfaced, not
            # missed because we only looked at the current course. Wrapped in
            # sync_to_async: detect_conflicts hits the ORM and this function
            # runs inside the ASGI event loop.
            conflicts = await sync_to_async(calendar_events.detect_conflicts)(
                user, pending["date"], pending["time"], pending["end_time"],
                exclude_event_id=pending["event_id"],
            )
        pending["conflicts"] = [
            {
                "id": c["id"], "title": c["title"], "date": c["date"],
                "time": c.get("time"), "end_time": c.get("end_time"), "course_id": c.get("course_id"),
            }
            for c in conflicts
        ]
    missing = [m for m in data.get("missing", []) if m in {"title", "date", "course_id", "event_match"}]
    if not pending_deadlines and "title" not in missing:
        missing.append("title")
    if any(not pending["title"] for pending in pending_deadlines) and "title" not in missing:
        missing.append("title")
    if any(not pending["date"] for pending in pending_deadlines) and "date" not in missing:
        missing.append("date")
    if any(pending["action"] in ("update", "delete") and not pending["event_id"] for pending in pending_deadlines) and "event_match" not in missing:
        missing.append("event_match")
    first_pending = pending_deadlines[0] if len(pending_deadlines) == 1 else None
    has_conflicts = not missing and any(pending["conflicts"] for pending in pending_deadlines)
    default_message = (
        "I need a little more detail before I can do that."
        if missing
        else "I can update this after you confirm the details."
        if any(p["action"] == "update" for p in pending_deadlines)
        else "I can remove this after you confirm."
        if any(p["action"] == "delete" for p in pending_deadlines)
        else "I can add this to your calendar after you confirm the details."
    )
    answer = data.get("message") or default_message
    if has_conflicts:
        # Surface the overlap so the student decides — never silently
        # double-book or auto-reschedule around a detected conflict.
        answer += (
            " Heads up: this overlaps with something already on your calendar — let me know if "
            "you'd like to proceed anyway or pick a different time."
        )
    return {
        "answer": answer,
        "grounded": True,
        "sources": ["syllabus"],
        "pending_deadline": None if missing else first_pending,
        "pending_deadlines": [] if missing else pending_deadlines,
        "deadline_missing": missing,
        "deadline_conflicts": has_conflicts,
    }


async def ask_async(
    course_id: str,
    question: str,
    session_id: str = None,
    user=None,
    client_request_id: str = None,
    allow_web: bool = False,
) -> dict:
    grounding_mode = "course_materials_and_web" if allow_web else "course_materials"
    syllabus = await sync_to_async(storage.read_syllabus)(course_id, user)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    if session_id is not None and client_request_id:
        existing = await sync_to_async(sessions.exchange_for_request)(
            course_id, session_id, client_request_id, user=user
        )
        if existing is not None:
            return existing

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
        result = await _structure_result_sources(
            result, course_id, question, user=user, session_id=session_id,
        )
        result["grounding_mode"] = grounding_mode
        if session_id is not None:
            result = await sync_to_async(sessions.append_exchange)(
                course_id, session_id, question, result,
                client_request_id=client_request_id, user=user,
            )
        return result

    client = get_client()

    if _looks_like_deadline_request(question):
        result = await _extract_deadline_request(client, question, course_id, syllabus, user=user)
        result = await _structure_result_sources(
            result, course_id, question, user=user, session_id=session_id,
        )
        result["grounding_mode"] = grounding_mode
        if session_id is not None:
            result = await sync_to_async(sessions.append_exchange)(
                course_id, session_id, question, result,
                client_request_id=client_request_id, user=user,
            )
        return result

    notes = await sync_to_async(storage.read_notes)(course_id, user)
    references = await sync_to_async(storage.read_references)(course_id, user)
    saved_sites = await sync_to_async(storage.list_saved_sites)(course_id, user=user)
    recalled_conversations = await sync_to_async(sessions.relevant_messages)(
        course_id, question, session_id=session_id, user=user,
    )
    approved_domains = await sync_to_async(storage.read_trusted_domains)(course_id, user)
    allowed_domains = _merge_allowed_domains(approved_domains, _domains_from_saved_sites(saved_sites)) if allow_web else []
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
                    "sources": [
                        label for label in (citations.legacy_source_label(source) for source in m.get("sources", []))
                        if label
                    ],
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
        "max_tokens": 8000,
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
        "grounded": data.get("grounded", False),
        "sources": data.get("sources", []),
    }
    result = await _structure_result_sources(
        result, course_id, question, user=user, session_id=session_id,
    )
    result["grounding_mode"] = grounding_mode

    if session_id is not None:
        result = await sync_to_async(sessions.append_exchange)(
            course_id, session_id, question, result,
            client_request_id=client_request_id, user=user,
        )

    return result


def _format_when(date_str: str, time_str: str | None) -> str:
    # Avoids the platform-specific "%-d"/"%-I" strftime flags (Unix-only —
    # Windows raises ValueError on them) by formatting day/hour manually.
    try:
        parsed = date.fromisoformat(date_str)
        label = f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
    except (TypeError, ValueError):
        label = date_str or "an unspecified date"
    if time_str:
        try:
            hour, minute = (int(part) for part in time_str.split(":")[:2])
            period = "AM" if hour < 12 else "PM"
            hour12 = hour % 12 or 12
            label += f" at {hour12}:{minute:02d} {period}"
        except (TypeError, ValueError):
            pass
    return label


def _resolve_existing_event(course_id: str, event_id: str, user=None) -> dict | None:
    """Re-resolves event_id against this user's OWN events, regardless of
    what the extraction model claimed about it — the only real
    authorization check for update/delete, since model output is untrusted."""
    events = calendar_events.all_events(user, course_ids=[course_id])
    return next((e for e in events if e["id"] == event_id), None)


def confirm_deadline_actions(course_id: str, session_id: str, actions: list, user=None) -> dict:
    """Executes one or more calendar actions Cora proposed in this session
    and the user just explicitly confirmed, then appends one summary turn to
    the session. This is the only code path allowed to write to the calendar
    on Cora's behalf — ask_async itself only ever proposes, never writes,
    per this project's plan-then-pause rule for destructive/bulk writes."""
    session = sessions.get_session(course_id, session_id, user=user)
    if session is None:
        raise sessions.SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")

    summaries = []
    for raw in actions:
        action = raw.get("action") or "create"

        if action == "create":
            title = str(raw.get("title") or "").strip()
            event_date = raw.get("date")
            if not title or not event_date:
                raise ValueError("title and date are required to add a deadline")
            event = custom_events.create_event(
                raw.get("course_id") or course_id,
                event_date.isoformat() if hasattr(event_date, "isoformat") else str(event_date),
                raw["time"].strftime("%H:%M") if raw.get("time") else None,
                title, raw.get("type") or "other", user=user,
                end_time=raw["end_time"].strftime("%H:%M") if raw.get("end_time") else None,
            )
            summaries.append(f"Added **{event['title']}** — {_format_when(event['date'], event['time'])}.")
            continue

        event_id = raw.get("event_id")
        if not event_id:
            raise ValueError(f"event_id is required to {action} a deadline")
        existing = _resolve_existing_event(course_id, str(event_id), user=user)
        if existing is None:
            raise custom_events.EventNotFoundError(f"no deadline '{event_id}' found for '{course_id}'")

        if action == "delete":
            if existing["source"] == "syllabus":
                raise ValueError(
                    f"'{existing['title']}' comes from the syllabus and can't be deleted — "
                    "I can mark it complete or move its date/time instead."
                )
            custom_events.delete_event(str(event_id), user=user)
            summaries.append(f"Removed **{existing['title']}** from your calendar.")
            continue

        if action == "update":
            fields = {}
            if raw.get("title"):
                fields["title"] = str(raw["title"]).strip()
            if raw.get("date"):
                fields["date"] = raw["date"].isoformat() if hasattr(raw["date"], "isoformat") else str(raw["date"])
            if raw.get("time"):
                fields["time"] = raw["time"].strftime("%H:%M")
            if raw.get("end_time"):
                fields["end_time"] = raw["end_time"].strftime("%H:%M")
            if raw.get("type"):
                fields["type"] = raw["type"]

            if existing["source"] == "syllabus":
                merged = {
                    "date": fields.get("date", existing["date"]),
                    "time": fields.get("time", existing.get("time")),
                    "end_time": fields.get("end_time", existing.get("end_time")),
                    "title": fields.get("title", existing["title"]),
                    "type": fields.get("type", existing["type"]),
                }
                event = custom_events.create_event(
                    course_id, merged["date"], merged["time"], merged["title"], merged["type"],
                    user=user, end_time=merged["end_time"], replaces_syllabus_key=existing["key"],
                )
            else:
                event = custom_events.update_event(str(event_id), user=user, **fields)
            summaries.append(f"Updated **{event['title']}** — now {_format_when(event['date'], event['time'])}.")
            continue

        raise ValueError(f"unknown action '{action}'")

    confirmation_text = " ".join(summaries) if summaries else "Nothing to confirm."
    return sessions.append_message(course_id, session_id, "assistant", confirmation_text, grounded=True, user=user)
