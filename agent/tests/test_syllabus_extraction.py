import pytest

from agent.services.syllabus_extraction import _parse_model_json, extract_text_from_bytes


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
