"""Render the current session-only academic plan as a DOCX download."""

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from django.utils.text import slugify


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

EXPORT_LAYOUTS = ("term_table", "year_grid", "plan_notes")
DEFAULT_LAYOUT = "term_table"
GRID_TERMS_PER_TABLE = 3


def plan_filename(draft_plan: dict) -> str:
    major = slugify(str(draft_plan.get("student_major") or "draft"))[:80] or "draft"
    return f"academic-plan-{major}.docx"


def _add_title(document, draft_plan):
    title = document.add_heading("Academic Plan", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    major = str(draft_plan.get("student_major") or "Undeclared")
    subtitle = document.add_paragraph(major)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.runs[0].font.size = Pt(13)


def _add_term_tables(document, semesters):
    for semester in semesters:
        document.add_heading(str(semester.get("label") or "Semester"), level=1)
        courses = semester.get("courses") or []
        if not courses:
            document.add_paragraph("No courses listed.")
            continue
        table = document.add_table(rows=1, cols=3)
        table.style = "Light Shading Accent 1"
        for cell, label in zip(table.rows[0].cells, ("Course", "Title", "Credits")):
            cell.text = label
        for course in courses:
            cells = table.add_row().cells
            cells[0].text = str(course.get("code") or "")
            cells[1].text = str(course.get("title") or "")
            cells[2].text = str(course.get("credits") or 0)


def _add_year_grid(document, semesters):
    """One column per term, GRID_TERMS_PER_TABLE terms per table, so a year fits on a page."""
    for start in range(0, len(semesters), GRID_TERMS_PER_TABLE):
        chunk = semesters[start:start + GRID_TERMS_PER_TABLE]
        table = document.add_table(rows=2, cols=len(chunk))
        table.style = "Light Shading Accent 1"
        for column, semester in enumerate(chunk):
            table.rows[0].cells[column].text = str(semester.get("label") or "Semester")
            lines = [
                f"{course.get('code') or ''} {course.get('title') or ''} ({course.get('credits') or 0})".strip()
                for course in semester.get("courses") or []
            ]
            table.rows[1].cells[column].text = "\n".join(lines) or "No courses listed."
        document.add_paragraph()


def _add_total(document, draft_plan):
    document.add_paragraph()
    total = document.add_paragraph()
    total.add_run("Total planned credits: ").bold = True
    total.add_run(str(draft_plan.get("total_credits") or 0))


def _add_notes(document, draft_plan):
    notes = str(draft_plan.get("notes") or "").strip()
    if notes:
        document.add_heading("Notes", level=1)
        document.add_paragraph(notes)


def _add_followups(document, draft_plan):
    document.add_heading("Flagged issues and follow-ups", level=1)
    notes = str(draft_plan.get("notes") or "").strip()
    document.add_paragraph(notes or "None noted.")
    document.add_heading("Action items", level=1)
    for _ in range(3):
        document.add_paragraph("", style="List Bullet")


def render_plan_docx(draft_plan: dict, layout: str = DEFAULT_LAYOUT) -> BytesIO:
    if layout not in EXPORT_LAYOUTS:
        layout = DEFAULT_LAYOUT

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)

    _add_title(document, draft_plan)
    semesters = draft_plan.get("semesters") or []
    if layout == "year_grid":
        _add_year_grid(document, semesters)
    else:
        _add_term_tables(document, semesters)
    _add_total(document, draft_plan)
    if layout == "plan_notes":
        _add_followups(document, draft_plan)
    else:
        _add_notes(document, draft_plan)

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output
