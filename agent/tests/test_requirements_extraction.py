import json

import pytest

from agent.services import requirements_extraction
from agent.services.requirements_extraction import (
    MalformedRequirementsSourceError,
    _normalize_extracted_requirements,
    _parse_model_json,
    extract_requirements_async,
    extract_text_from_workbook_bytes,
)


def _xlsx_bytes(rows):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    import io

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------

def test_extract_text_reads_nonempty_rows():
    data = _xlsx_bytes([["Program:", "B.S. Test"], ["CS 101", "Intro", 3]])

    text = extract_text_from_workbook_bytes(data, "program.xlsx")

    assert "Program:" in text
    assert "CS 101" in text


def test_extract_text_raises_on_empty_workbook():
    data = _xlsx_bytes([])

    with pytest.raises(MalformedRequirementsSourceError, match="no readable rows"):
        extract_text_from_workbook_bytes(data, "empty.xlsx")


def test_extract_text_raises_on_unsupported_extension():
    with pytest.raises(MalformedRequirementsSourceError, match="unsupported file type"):
        extract_text_from_workbook_bytes(b"not excel", "program.pdf")


def test_extract_text_raises_on_corrupt_file():
    with pytest.raises(MalformedRequirementsSourceError, match="couldn't read Excel file"):
        extract_text_from_workbook_bytes(b"this is not a real workbook", "program.xlsx")


# --------------------------------------------------------------------------
# JSON parsing
# --------------------------------------------------------------------------

def test_parse_model_json_uses_last_valid_object_after_self_correction():
    raw = """
{
  "program_name": "B.S. Test",
  "catalog_year": "2026",
  "total_credits_required": 120,
  "categories": []
}
Wait, let me reconsider.
{
  "program_name": "B.S. Test",
  "catalog_year": "2026",
  "total_credits_required": 121,
  "categories": []
}
"""
    data = _parse_model_json(raw)
    assert data["total_credits_required"] == 121


def test_parse_model_json_raises_when_no_complete_json_object_exists():
    with pytest.raises(ValueError, match="model did not return valid JSON"):
        _parse_model_json("Here's the extraction: {not valid")


# --------------------------------------------------------------------------
# Normalization — never fabricate a category or course the model omitted
# --------------------------------------------------------------------------

def test_normalize_defaults_missing_fields_without_fabricating():
    data = _normalize_extracted_requirements({
        "program_name": "B.S. Test",
        "categories": [
            {
                "name": "Core",
                "courses": [
                    {"code": "CS 101", "title": "Intro"},
                    {"code": "", "title": "No code — dropped"},
                ],
            }
        ],
    })

    assert data["catalog_year"] == ""
    assert data["total_credits_required"] == 0
    assert len(data["categories"]) == 1
    assert len(data["categories"][0]["courses"]) == 1
    assert data["categories"][0]["courses"][0] == {
        "code": "CS 101", "title": "Intro", "credits": 0, "prerequisites": [], "notes": "",
    }


def test_normalize_drops_non_dict_categories_and_courses():
    data = _normalize_extracted_requirements({
        "categories": ["not a dict", {"name": "Core", "courses": ["also not a dict"]}],
    })

    assert len(data["categories"]) == 1
    assert data["categories"][0]["courses"] == []


def test_normalize_raises_on_non_dict_result():
    with pytest.raises(MalformedRequirementsSourceError):
        _normalize_extracted_requirements(["not", "a", "dict"])


# --------------------------------------------------------------------------
# extract_requirements_async — mocked model call
# --------------------------------------------------------------------------

class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


@pytest.mark.asyncio
async def test_extract_requirements_async_returns_normalized_model_output(monkeypatch):
    payload = json.dumps({
        "program_name": "B.S. Computer Science",
        "catalog_year": "2026-2027",
        "total_credits_required": 120,
        "categories": [
            {"name": "Core", "credits_required": 30, "courses": [
                {"code": "CS 101", "title": "Intro to Programming", "credits": 3, "prerequisites": [], "notes": ""},
            ]},
        ],
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(requirements_extraction, "get_client", lambda: fake)

    data = _xlsx_bytes([["CS 101", "Intro to Programming", 3]])
    result = await extract_requirements_async(data, "program.xlsx")

    assert result["program_name"] == "B.S. Computer Science"
    assert result["categories"][0]["courses"][0]["code"] == "CS 101"
    assert len(fake.messages.calls) == 1


@pytest.mark.asyncio
async def test_extract_requirements_async_raises_on_malformed_source(monkeypatch):
    with pytest.raises(MalformedRequirementsSourceError):
        await extract_requirements_async(_xlsx_bytes([]), "empty.xlsx")
