from io import BytesIO

import pytest
from docx import Document

from agent.services import plan_export

LAYOUTS = ("term_table", "year_grid", "plan_notes")


def _draft(semesters=None, notes="Confirm elective availability."):
    if semesters is None:
        semesters = [
            {"label": "Fall 2026", "courses": [
                {"code": "CS 101", "title": "Intro to Programming", "credits": 3},
                {"code": "MATH 230", "title": "Discrete Mathematics", "credits": 3},
            ]},
            {"label": "Spring 2027", "courses": [{"code": "CS 201", "title": "Data Structures", "credits": 4}]},
        ]
    return {
        "student_major": "Computer Science",
        "semesters": semesters,
        "total_credits": 10,
        "notes": notes,
    }


def _open(buffer):
    return Document(BytesIO(buffer.getvalue()))


def _text(document):
    paragraphs = [p.text for p in document.paragraphs]
    tables = [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables]
    return paragraphs, tables


def test_term_table_matches_existing_output():
    default = _text(_open(plan_export.render_plan_docx(_draft())))
    explicit = _text(_open(plan_export.render_plan_docx(_draft(), "term_table")))

    assert default == explicit
    paragraphs, tables = default
    assert len(tables) == 2
    assert tables[0][0] == ["Course", "Title", "Credits"]
    assert tables[0][1] == ["CS 101", "Intro to Programming", "3"]
    assert "Total planned credits: 10" in paragraphs
    assert "Notes" in paragraphs


def test_year_grid_places_semesters_in_one_table():
    _, tables = _text(_open(plan_export.render_plan_docx(_draft(), "year_grid")))

    assert len(tables) == 1
    assert tables[0][0] == ["Fall 2026", "Spring 2027"]
    assert "CS 101" in tables[0][1][0] and "MATH 230" in tables[0][1][0]
    assert "CS 201" in tables[0][1][1]


def test_year_grid_starts_a_new_table_after_three_semesters():
    semesters = [{"label": f"Term {i}", "courses": []} for i in range(1, 5)]

    _, tables = _text(_open(plan_export.render_plan_docx(_draft(semesters), "year_grid")))

    assert [len(table[0]) for table in tables] == [3, 1]


def test_plan_notes_includes_followup_section():
    paragraphs, _ = _text(_open(plan_export.render_plan_docx(_draft(), "plan_notes")))

    assert "Flagged issues and follow-ups" in paragraphs
    assert "Action items" in paragraphs
    assert "Confirm elective availability." in paragraphs


def test_unknown_layout_falls_back_to_term_table():
    assert _text(_open(plan_export.render_plan_docx(_draft(), "no-such-layout"))) == _text(
        _open(plan_export.render_plan_docx(_draft(), "term_table"))
    )


@pytest.mark.parametrize("layout", LAYOUTS)
def test_empty_semesters_still_produces_valid_docx(layout):
    document = _open(plan_export.render_plan_docx(_draft([], notes=""), layout))

    assert "Academic Plan" in [p.text for p in document.paragraphs]


def test_layout_constants():
    assert plan_export.EXPORT_LAYOUTS == LAYOUTS
    assert plan_export.DEFAULT_LAYOUT == "term_table"
