"""
Syllabus extraction logic. Uses AsyncAnthropic so the DRF async view can
await it directly without blocking the ASGI event loop; the management
command wraps the same coroutine with asyncio.run() for standalone CLI use.
"""

import io
import json
import re
from pathlib import Path

from .client import MODEL_DEFAULT as MODEL, get_client

EXTRACTION_SYSTEM_PROMPT = """You extract structured data from a course syllabus.

Rules:
- Use ONLY information present in the provided syllabus text. Do not add dates, \
topics, or grading components that are not explicitly stated or clearly implied \
by the document (e.g. "Midterm — Oct 14" clearly implies an exam on that date).
- If any required field of a dates[] or grading[] entry can't be determined, drop \
the ENTIRE entry rather than guessing or emitting it with that field missing — \
every dates[] item needs date AND title AND type together, every grading[] item \
needs component AND weight_pct together. A partial object (e.g. title/type with \
no date) is invalid output; omitting the whole entry is the correct move instead. \
Do not invent plausible-sounding data.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown \
fences, no commentary.

Schema:
{
  "course_id": "string",
  "course_name": "string",
  "dates": [{"date": "YYYY-MM-DD", "title": "string", "type": "exam|assignment|reading|other"}],
  "grading": [{"component": "Homework|Tests|Quizzes|Midterm|Final|Projects|Other", "weight_pct": 0}],
  "topics": ["string"]
}

Notes on fields:
- "date" must be YYYY-MM-DD, and the year is NOT optional. Before extracting any \
dates[] entries, check whether an explicit calendar year (e.g. "2026") appears \
ANYWHERE in the document — in a header, term label ("Fall 2026"), or elsewhere. \
If no explicit year appears anywhere in the document, you cannot determine the \
year for ANY date in it: the dates[] array must be empty, even though the \
document clearly has months/days/weeks in it. A vague term reference like "this \
semester", "this term", or "the current semester" is NOT a year and is NOT a \
license to guess one — guessing a plausible-looking year (e.g. defaulting to the \
current year) is fabrication and is exactly what this rule exists to prevent. \
Only extract a date when the year is either stated directly on it or unambiguous \
from an explicit year stated elsewhere in the same document.
- "type" must be exactly one of: exam, assignment, reading, other.
- "weight_pct" is a number (e.g. 20 for 20%). If weights aren't given, drop that \
whole grading[] entry — never emit {"component": ...} with no "weight_pct".
- "component" MUST be exactly one of: Homework, Tests, Quizzes, Midterm, Final, \
Projects, Other. Map the syllabus's own wording onto these:
    - Homework: homework, assignments, problem sets, exercises
    - Tests: recurring or unlabeled tests/exams not specifically called out as \
"the midterm" or "the final"
    - Quizzes: quizzes
    - Midterm: an exam explicitly labeled as the midterm
    - Final: an exam explicitly labeled as the final
    - Projects: projects, presentations, capstone work
    - Other: anything real that doesn't fit the six above (participation, \
attendance, lab reports, etc.) — use Other rather than dropping the entry or \
forcing it into the wrong bucket.
  If two or more syllabus lines map to the same bucket (e.g. "Problem Sets" 15% \
and "Lab Assignments" 10%, both Homework), merge them into ONE grading[] entry \
with the summed weight_pct — never emit two entries with the same component.
- "topics" is a flat list of topic/unit names as they appear in the syllabus.
"""


# --------------------------------------------------------------------------
# Text extraction from source bytes (sync — file I/O, not worth async)
# --------------------------------------------------------------------------

def extract_text_from_bytes(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if not text:
            raise ValueError(
                "no extractable text found in PDF (it may be a scanned image — "
                "OCR is not supported yet)"
            )
        return text

    elif suffix in (".txt", ".md"):
        text = data.decode("utf-8", errors="ignore").strip()
        if not text:
            raise ValueError("source file is empty")
        return text

    else:
        raise ValueError(f"unsupported file type '{suffix}'. Use .pdf, .txt, or .md.")


def read_source_text_from_path(path: Path) -> str:
    """For the CLI management command — reads a local file."""
    return extract_text_from_bytes(path.read_bytes(), path.name)


def read_source_text_from_upload(upload) -> str:
    """For the DRF view — reads a Django UploadedFile."""
    return extract_text_from_bytes(upload.read(), upload.name)


# --------------------------------------------------------------------------
# Extraction call
# --------------------------------------------------------------------------

async def extract_syllabus_async(source_text: str, course_id: str, course_name_hint: str = None) -> dict:
    client = get_client()

    user_prompt = f"course_id to use: {course_id}\n"
    if course_name_hint:
        user_prompt += f"course_name hint (use if it matches the document): {course_name_hint}\n"
    user_prompt += f"\nSyllabus text:\n---\n{source_text}\n---"

    response = await client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # The model sometimes prefixes the JSON with reasoning prose (or trails it
        # with commentary) despite being told not to. As a fallback, slice out
        # everything from the first "{" to the last "}" and retry once before
        # giving up — this tolerates a preamble/epilogue without trying to parse
        # or understand its shape.
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            sliced = raw[start:end + 1]
            try:
                return json.loads(sliced)
            except json.JSONDecodeError:
                pass
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")
