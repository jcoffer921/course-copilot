"""
Suggests candidate trusted domains for a course's restricted web search,
based on that course's own syllabus (course_name + topics). Read-only — this
never writes trusted_domains.json itself; a human reviews and approves (or
hand-edits) the list via storage.write_trusted_domains() afterward.

Uses AsyncAnthropic so the DRF async view can await it directly without
blocking the ASGI event loop; the management command wraps the same
coroutine with asyncio.run() for standalone CLI use — same pattern as
ask.py and chunk_notes.py.
"""

import json
import re

from asgiref.sync import sync_to_async

from . import storage
from .client import MODEL_DEFAULT as MODEL, get_client
from .storage import CourseNotFoundError

DOMAIN_SUGGESTION_SYSTEM_PROMPT = """You propose a short list of real, authoritative web domains \
that would be trustworthy sources for questions about ONE college course, based on its name and \
topics.

Rules:
- Only propose real domains you're confident actually exist and are authoritative for this subject \
— official documentation sites, .gov agencies, .edu institutions, and reputable .org organizations \
relevant to the course's subject matter. Prefer institutional/official domains over general \
commercial ones.
- Never propose wikipedia.org or any other openly-editable wiki — it is not treated as an \
authoritative source here, regardless of how commonly it's used for the subject.
- Tailor the list to THIS course's actual subject, not a generic default list — a Chemistry course \
and a Psychology course should get different domains.
- This is a suggestion only. A human will review and approve (or reject) each domain before it's \
ever used for search — you may be wrong about a domain, or it may not resolve. Propose your best \
real candidates; do not hedge by proposing fewer than you're confident in.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "domains": ["string", ...]
}

Notes on fields:
- "domains" is a flat list of bare domain strings (e.g. "docs.python.org", "nist.gov") — no \
wildcards, no protocol prefix, no path.
"""


async def suggest_domains(course_id: str) -> list[str]:
    syllabus = await sync_to_async(storage.read_syllabus)(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    client = get_client()

    user_prompt = (
        f"course_name: {syllabus.get('course_name', '')}\n"
        f"topics: {json.dumps(syllabus.get('topics', []), indent=2)}"
    )

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=DOMAIN_SUGGESTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    seen = set()
    domains = []
    for d in data.get("domains", []):
        if not isinstance(d, str):
            continue
        domain = d.strip().lower()
        if not domain or "wikipedia.org" in domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)

    return domains
