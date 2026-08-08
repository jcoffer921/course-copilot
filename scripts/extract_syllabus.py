#!/usr/bin/env python3
"""
extract_syllabus.py — Extract structured syllabus data from a PDF or text file
using the Anthropic API, validate it against the course-copilot schema, and
write it to courses/<course_id>/syllabus.json.

Usage:
    python extract_syllabus.py <path_to_syllabus_file> <course_id> [--course-name "Name"] [--force]

Requires:
    ANTHROPIC_API_KEY environment variable set.
    pip install anthropic pypdf
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("Missing dependency: pip install anthropic")

MODEL = "claude-sonnet-4-6"  # per project instructions: Sonnet for extraction
VALID_DATE_TYPES = {"exam", "assignment", "reading", "other"}

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
COURSES_DIR = PROJECT_ROOT / "courses"


# --------------------------------------------------------------------------
# File reading
# --------------------------------------------------------------------------

def read_source_text(path: Path) -> str:
    """Read a syllabus source file (.pdf, .txt, or .md) into plain text."""
    if not path.exists():
        sys.exit(f"ERROR: source file not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("Missing dependency: pip install pypdf")
        reader = PdfReader(str(path))
        text_parts = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(text_parts).strip()
        if not text:
            sys.exit(
                "ERROR: no extractable text found in PDF. "
                "It may be a scanned image — OCR is not supported yet."
            )
        return text

    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            sys.exit(f"ERROR: source file is empty: {path}")
        return text

    else:
        sys.exit(f"ERROR: unsupported file type '{suffix}'. Use .pdf, .txt, or .md.")


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You extract structured data from a course syllabus.

Rules:
- Use ONLY information present in the provided syllabus text. Do not add dates, \
topics, or grading components that are not explicitly stated or clearly implied \
by the document (e.g. "Midterm — Oct 14" clearly implies an exam on that date).
- If a field cannot be determined from the text, omit that item rather than \
guessing. Do not invent plausible-sounding data.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown \
fences, no commentary.

Schema:
{
  "course_id": "string",
  "course_name": "string",
  "dates": [{"date": "YYYY-MM-DD", "title": "string", "type": "exam|assignment|reading|other"}],
  "grading": [{"component": "string", "weight_pct": 0}],
  "topics": ["string"]
}

Notes on fields:
- "date" must be YYYY-MM-DD. If the syllabus gives no year, infer it only if \
unambiguous from context (e.g. a semester label like "Fall 2026" stated elsewhere \
in the document); otherwise omit that date entry rather than guessing a year.
- "type" must be exactly one of: exam, assignment, reading, other.
- "weight_pct" is a number (e.g. 20 for 20%). If weights aren't given, omit that \
grading entry rather than guessing a number.
- "topics" is a flat list of topic/unit names as they appear in the syllabus.
"""


def call_extraction(source_text: str, course_id: str, course_name_hint):
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    user_prompt = f"course_id to use: {course_id}\n"
    if course_name_hint:
        user_prompt += f"course_name hint (use if it matches the document): {course_name_hint}\n"
    user_prompt += f"\nSyllabus text:\n---\n{source_text}\n---"

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: model did not return valid JSON.\n{e}\n\nRaw output:\n{raw}")

    return data


# --------------------------------------------------------------------------
# Validation — fail loudly, no silent empty results
# --------------------------------------------------------------------------

def validate_syllabus(data: dict) -> list:
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("course_id", str)
    require("course_name", str)
    require("dates", list)
    require("grading", list)
    require("topics", list)

    if errors:
        return errors  # top-level shape is broken, don't bother checking nested items

    for i, d in enumerate(data["dates"]):
        if not isinstance(d, dict):
            errors.append(f"dates[{i}] is not an object")
            continue
        if "date" not in d or "title" not in d or "type" not in d:
            errors.append(f"dates[{i}] missing one of date/title/type: {d}")
            continue
        try:
            datetime.strptime(d["date"], "%Y-%m-%d")
        except ValueError:
            errors.append(f"dates[{i}].date is not YYYY-MM-DD: {d['date']!r}")
        if d["type"] not in VALID_DATE_TYPES:
            errors.append(
                f"dates[{i}].type invalid: {d['type']!r} (must be one of {VALID_DATE_TYPES})"
            )

    for i, g in enumerate(data["grading"]):
        if not isinstance(g, dict) or "component" not in g or "weight_pct" not in g:
            errors.append(f"grading[{i}] malformed: {g}")
            continue
        if not isinstance(g["weight_pct"], (int, float)):
            errors.append(f"grading[{i}].weight_pct must be numeric: {g['weight_pct']!r}")

    for i, t in enumerate(data["topics"]):
        if not isinstance(t, str):
            errors.append(f"topics[{i}] is not a string: {t!r}")

    total_weight = sum(
        g.get("weight_pct", 0) for g in data["grading"]
        if isinstance(g.get("weight_pct"), (int, float))
    )
    if data["grading"] and abs(total_weight - 100) > 0.5:
        errors.append(
            f"WARNING: grading weights sum to {total_weight}, not 100 "
            f"(not blocking, but check the source)"
        )

    return errors


# --------------------------------------------------------------------------
# Write with plan-then-pause on overwrite
# --------------------------------------------------------------------------

def write_syllabus(course_id: str, data: dict, force: bool):
    out_dir = COURSES_DIR / course_id
    out_path = out_dir / "syllabus.json"

    if out_path.exists() and not force:
        print(f"\n'{out_path}' already exists.")
        print("This extraction would overwrite it. Preview of new data:")
        print(json.dumps(data, indent=2)[:1000])
        confirm = input("\nOverwrite? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted. No file was written.")
            sys.exit(0)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n✓ Wrote {out_path}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract syllabus.json from a syllabus file.")
    parser.add_argument("source", help="Path to syllabus PDF, TXT, or MD file")
    parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
    parser.add_argument("--course-name", help="Hint for the course's full name", default=None)
    parser.add_argument("--force", action="store_true", help="Overwrite existing syllabus.json without confirmation")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: ANTHROPIC_API_KEY environment variable is not set.")

    source_path = Path(args.source)
    print(f"Reading {source_path}...")
    text = read_source_text(source_path)
    print(f"Extracted {len(text)} characters of source text.")

    print(f"Calling {MODEL} for extraction...")
    data = call_extraction(text, args.course_id, args.course_name)

    print("Validating against schema...")
    errors = validate_syllabus(data)
    blocking_errors = [e for e in errors if not e.startswith("WARNING")]
    warnings = [e for e in errors if e.startswith("WARNING")]

    for w in warnings:
        print(f"  {w}")

    if blocking_errors:
        print("\nERROR: extracted data failed schema validation:")
        for e in blocking_errors:
            print(f"  - {e}")
        print("\nNothing was written. Raw extracted data:")
        print(json.dumps(data, indent=2))
        sys.exit(1)

    print(
        f"  ✓ {len(data['dates'])} dates, "
        f"{len(data['grading'])} grading components, "
        f"{len(data['topics'])} topics"
    )

    write_syllabus(args.course_id, data, args.force)


if __name__ == "__main__":
    main()
