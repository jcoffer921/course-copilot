import pytest

from agent.services import storage
from agent.services.syllabus_extraction import (
    _extract_meeting_patterns,
    _normalize_extracted_syllabus,
    _parse_model_json,
    extract_text_from_bytes,
)


def test_parse_model_json_uses_last_valid_object_after_self_correction():
    raw = """
{
  "course_id": "computer-graphics-algorithms",
  "course_name": "Computer Graphics Algorithms",
  "dates": [],
  "grading": [
    {"component": "Other", "weight_pct": 60},
    {"component": "Projects", "weight_pct": 20},
    {"component": "Other", "weight_pct": 20}
  ],
  "topics": ["Overview of WebGL"]
}
Wait, I have two "Other" entries which violates the merge rule. Let me fix that by merging them.
json
{
  "course_id": "computer-graphics-algorithms",
  "course_name": "Computer Graphics Algorithms",
  "dates": [],
  "grading": [
    {"component": "Other", "weight_pct": 80},
    {"component": "Projects", "weight_pct": 20}
  ],
  "topics": ["Overview of WebGL"]
}
"""

    data = _parse_model_json(raw)

    assert data["course_id"] == "computer-graphics-algorithms"
    assert data["course_name"] == "Computer Graphics Algorithms"
    assert data["grading"] == [
        {"component": "Other", "weight_pct": 80},
        {"component": "Projects", "weight_pct": 20},
    ]


def test_parse_model_json_raises_when_no_complete_json_object_exists():
    with pytest.raises(ValueError, match="model did not return valid JSON"):
        _parse_model_json("Here is the extraction: {not valid")


def test_normalize_extracted_syllabus_maps_legacy_date_types():
    data = _normalize_extracted_syllabus({
        "course_id": "cmpsc460",
        "course_name": "Principles of Programming Languages",
        "dates": [
            {"date": "2026-10-01", "title": "Term-1 Exam", "type": "exam"},
            {"date": "2026-10-08", "title": "Homework", "type": "assignment"},
            {"date": "2026-10-15", "title": "Reading", "type": "reading"},
        ],
        "grading": [],
        "topics": [],
    })

    assert [item["type"] for item in data["dates"]] == ["test_quiz", "hw", "class"]
    assert data["meeting_patterns"] == []


def test_extract_meeting_patterns_reads_compact_days_times_and_explicit_term_dates():
    source = """Class Meeting Hours: MoWeFr 11:15AM - 12:05PM. Woodland Bldg 237
Aug 26, 2024-
Dec 13, 2024
"""

    assert _extract_meeting_patterns(source) == [{
        "title": "Class",
        "days": [0, 2, 4],
        "start_time": "11:15",
        "end_time": "12:05",
        "start_date": "2024-08-26",
        "end_date": "2024-12-13",
    }]


def test_validate_syllabus_accepts_valid_meeting_pattern_and_rejects_bad_time():
    syllabus = {
        "course_id": "cs101", "course_name": "CS 101", "dates": [], "grading": [], "topics": [],
        "meeting_patterns": [{
            "title": "Class", "days": [0, 2, 4], "start_time": "11:15", "end_time": "12:05",
            "start_date": "2026-08-24", "end_date": "2026-12-11",
        }],
    }
    assert storage.validate_syllabus(syllabus) == []

    syllabus["meeting_patterns"][0]["start_time"] = "25:90"
    assert any("start_time is not HH:MM" in error for error in storage.validate_syllabus(syllabus))


def test_extract_text_from_bytes_reads_plain_text_formats():
    assert extract_text_from_bytes(b"# Week 1\nIntro to shaders", "notes.md") == "# Week 1\nIntro to shaders"
    assert extract_text_from_bytes(b"Plain lecture notes", "notes.txt") == "Plain lecture notes"


def test_extract_text_from_bytes_reads_docx():
    docx = pytest.importorskip("docx")
    from io import BytesIO

    doc = docx.Document()
    doc.add_paragraph("Course overview")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Final"
    table.cell(0, 1).text = "30%"
    buf = BytesIO()
    doc.save(buf)

    text = extract_text_from_bytes(buf.getvalue(), "syllabus.docx")

    assert "Course overview" in text
    assert "Final | 30%" in text


def test_extract_text_from_bytes_reads_pptx():
    pptx = pytest.importorskip("pptx")
    from io import BytesIO

    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Week 2"
    slide.placeholders[1].text = "Fragment shaders"
    buf = BytesIO()
    prs.save(buf)

    text = extract_text_from_bytes(buf.getvalue(), "slides.pptx")

    assert "Slide 1" in text
    assert "Week 2" in text
    assert "Fragment shaders" in text


def test_extract_text_from_bytes_rejects_unsupported_file_type_with_supported_formats():
    with pytest.raises(ValueError, match=r"Use \.pdf, \.pptx, \.docx, \.txt, or \.md"):
        extract_text_from_bytes(b"legacy binary", "syllabus.doc")
