"""Shared JSON-recovery parser for Cora's newer capabilities
(intent_router, study_planner, mastery_analyzer, document_summarizer).

The three pre-existing parsers (ask.py::_parse_json_response,
quiz.py::_parse_json, syllabus_extraction.py::_parse_model_json) are each
independently hardened against real production quirks specific to their own
prompts — they are deliberately left alone rather than migrated here, since
touching them is pure regression risk for no behavior change. New
capabilities get this one shared helper instead of writing a fourth bespoke
variant.
"""

import json
import re


def parse_model_json(raw: str, required_keys: set[str] | None = None) -> dict:
    """Strips a markdown fence if present, then recovers a JSON object from
    the model's output even if it added preamble/commentary the prompt told
    it not to. When required_keys is given, prefers the last candidate
    object containing every one of those keys over an earlier, incomplete
    match (e.g. an example object mentioned in the model's own preamble).
    Raises ValueError with the raw output attached if nothing usable is
    found, so callers can log/report the actual model output on failure."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    decoder = json.JSONDecoder()
    fallback = None

    for match in reversed(list(re.finditer(r"{", text))):
        candidate = text[match.start():]
        try:
            obj, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if fallback is None:
            fallback = obj
        if not required_keys or required_keys.issubset(obj.keys()):
            return obj

    if fallback is not None:
        return fallback
    raise ValueError(f"no JSON object found in model output:\n{raw}")
