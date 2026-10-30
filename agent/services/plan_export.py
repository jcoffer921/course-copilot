"""Render the current session-only academic plan as a DOCX or PDF download.

Both formats share one layout step: `build_blocks` turns the draft plan into a short list of simple
blocks for the chosen layout, and each renderer only knows how to draw those blocks. That keeps the
three layouts identical whichever file type is chosen.
"""

import html
from io import BytesIO

import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from django.utils.text import slugify


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_CONTENT_TYPE = "application/pdf"

EXPORT_LAYOUTS = ("term_table", "year_grid", "plan_notes")
DEFAULT_LAYOUT = "term_table"
FILE_TYPES = ("docx", "pdf")
DEFAULT_FILE_TYPE = "docx"
GRID_TERMS_PER_TABLE = 3
GRID_COLUMN_PERCENT = 33  # every grid column is the same width, even in a table with fewer terms

# Letter page, 0.75in side margins, room below the text for the footer.
PDF_PAGE = pymupdf.paper_rect("letter")
PDF_TEXT_AREA = PDF_PAGE + (54, 54, -54, -66)
PDF_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; color: #10192b; }
p.inst { font-size: 9.5pt; text-align: center; margin: 0 0 10pt 0; color: #1E407C; }
h1 { font-size: 22pt; text-align: center; margin: 0 0 4pt 0; color: #001E44; }
p.sub { font-size: 13pt; text-align: center; margin: 0 0 14pt 0; color: #5a6578; }
h2 { font-size: 13pt; margin: 14pt 0 4pt 0; color: #001E44; }
p { margin: 0 0 6pt 0; }
table { width: 100%; border-spacing: 0; margin: 0 0 6pt 0; }  /* not border-collapse: it makes PyMuPDF paint stray bars on later pages */
th { background-color: #1E407C; color: #ffffff; text-align: left; padding: 4pt; font-size: 9.5pt; }
td { padding: 4pt; border-bottom: 0.5pt solid #d9e0ea; vertical-align: top; }
li { margin: 0 0 10pt 0; }
"""


def plan_filename(draft_plan: dict, file_type: str = DEFAULT_FILE_TYPE) -> str:
    major = slugify(str(draft_plan.get("student_major") or "draft"))[:80] or "draft"
    extension = file_type if file_type in FILE_TYPES else DEFAULT_FILE_TYPE
    return f"academic-plan-{major}.{extension}"


def ground_to_program(draft_plan: dict, requirements: dict) -> dict:
    """Overwrite each course's title and credits (and the total) with the program's own values.

    The model is only trusted for which courses go in which term; the document must agree with
    the grounded requirements the faculty member reviewed on screen."""
    known = {
        course["code"]: course
        for category in (requirements or {}).get("categories") or []
        for course in category.get("courses") or []
        if course.get("code")
    }
    semesters = []
    total = 0
    for semester in draft_plan.get("semesters") or []:
        courses = []
        for course in semester.get("courses") or []:
            match = known.get(course.get("code"))
            merged = {**course, "title": match.get("title") or course.get("title"), "credits": match.get("credits")} if match else dict(course)
            total += int(merged.get("credits") or 0)
            courses.append(merged)
        semesters.append({**semester, "courses": courses})
    return {**draft_plan, "semesters": semesters, "total_credits": total}


# ---------------------------------------------------------------------------
# Layout: draft plan -> blocks
# ---------------------------------------------------------------------------
#   {"type": "institution" | "title" | "subtitle" | "heading" | "paragraph" | "spacer", "text": str}
#   {"type": "labeled", "label": str, "text": str}
#   {"type": "table", "header": [str], "rows": [[str]], "align": [str], "widths": [percent]}  (align and widths optional)
#   {"type": "blank_bullets", "count": int}


def _term_blocks(semesters):
    blocks = []
    for semester in semesters:
        blocks.append({"type": "heading", "text": str(semester.get("label") or "Semester")})
        courses = semester.get("courses") or []
        if not courses:
            blocks.append({"type": "paragraph", "text": "No courses listed."})
            continue
        blocks.append({
            "type": "table",
            "header": ["Course", "Title", "Credits"],
            "align": ["left", "left", "right"],
            "widths": [18, 70, 12],
            "rows": [[str(c.get("code") or ""), str(c.get("title") or ""), str(c.get("credits") or 0)] for c in courses],
        })
    return blocks


def _grid_blocks(semesters):
    """One column per term, GRID_TERMS_PER_TABLE terms per table, so a year fits on a page."""
    blocks = []
    for start in range(0, len(semesters), GRID_TERMS_PER_TABLE):
        chunk = semesters[start:start + GRID_TERMS_PER_TABLE]
        cells = []
        for semester in chunk:
            lines = [
                f"{course.get('code') or ''} {course.get('title') or ''} ({course.get('credits') or 0})".strip()
                for course in semester.get("courses") or []
            ]
            cells.append("\n".join(lines) or "No courses listed.")
        blocks.append({
            "type": "table",
            "header": [str(s.get("label") or "Semester") for s in chunk],
            "widths": [GRID_COLUMN_PERCENT] * len(chunk),
            "rows": [cells],
        })
        blocks.append({"type": "spacer"})
    return blocks


def build_blocks(draft_plan: dict, layout: str = DEFAULT_LAYOUT, institution_line: str = "") -> list:
    if layout not in EXPORT_LAYOUTS:
        layout = DEFAULT_LAYOUT
    semesters = draft_plan.get("semesters") or []
    notes = str(draft_plan.get("notes") or "").strip()

    blocks = []
    if institution_line:
        blocks.append({"type": "institution", "text": institution_line})
    blocks += [
        {"type": "title", "text": "Academic Plan"},
        {"type": "subtitle", "text": str(draft_plan.get("student_major") or "Undeclared")},
    ]
    blocks += _grid_blocks(semesters) if layout == "year_grid" else _term_blocks(semesters)
    blocks += [
        {"type": "spacer"},
        {"type": "labeled", "label": "Total planned credits: ", "text": str(draft_plan.get("total_credits") or 0)},
    ]
    if layout == "plan_notes":
        blocks += [
            {"type": "heading", "text": "Flagged issues and follow-ups"},
            {"type": "paragraph", "text": notes or "None noted."},
            {"type": "heading", "text": "Action items"},
            {"type": "blank_bullets", "count": 3},
        ]
    elif notes:
        blocks += [{"type": "heading", "text": "Notes"}, {"type": "paragraph", "text": notes}]
    return blocks


# ---------------------------------------------------------------------------
# DOCX renderer
# ---------------------------------------------------------------------------


def _docx_from_blocks(blocks) -> BytesIO:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)

    for block in blocks:
        kind = block["type"]
        if kind == "institution":
            paragraph = document.add_paragraph(block["text"])
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.runs[0].font.size = Pt(10)
        elif kind == "title":
            document.add_heading(block["text"], level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif kind == "subtitle":
            paragraph = document.add_paragraph(block["text"])
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.runs[0].font.size = Pt(13)
        elif kind == "heading":
            document.add_heading(block["text"], level=1)
        elif kind == "paragraph":
            document.add_paragraph(block["text"])
        elif kind == "spacer":
            document.add_paragraph()
        elif kind == "labeled":
            paragraph = document.add_paragraph()
            paragraph.add_run(block["label"]).bold = True
            paragraph.add_run(block["text"])
        elif kind == "table":
            table = document.add_table(rows=1, cols=len(block["header"]))
            table.style = "Light Shading Accent 1"
            for cell, label in zip(table.rows[0].cells, block["header"]):
                cell.text = label
            for row in block["rows"]:
                for cell, value in zip(table.add_row().cells, row):
                    cell.text = value
        elif kind == "blank_bullets":
            for _ in range(block["count"]):
                document.add_paragraph("", style="List Bullet")

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------


def _text(value) -> str:
    return html.escape(str(value), quote=True)


def _multiline(value) -> str:
    return "<br>".join(_text(line) for line in str(value).split("\n"))


def _html_from_blocks(blocks) -> str:
    parts = []
    for block in blocks:
        kind = block["type"]
        if kind == "institution":
            parts.append(f"<p class='inst'>{_text(block['text'])}</p>")
        elif kind == "title":
            parts.append(f"<h1>{_text(block['text'])}</h1>")
        elif kind == "subtitle":
            parts.append(f"<p class='sub'>{_text(block['text'])}</p>")
        elif kind == "heading":
            parts.append(f"<h2>{_text(block['text'])}</h2>")
        elif kind == "paragraph":
            parts.append(f"<p>{_multiline(block['text'])}</p>")
        elif kind == "spacer":
            parts.append("<p>&nbsp;</p>")
        elif kind == "labeled":
            parts.append(f"<p><b>{_text(block['label'])}</b>{_text(block['text'])}</p>")
        elif kind == "table":
            columns = len(block["header"])
            aligns = block.get("align") or ["left"] * columns
            widths = block.get("widths") or [100 // columns] * columns
            head = "".join(
                f"<th style='width:{w}%;text-align:{a}'>{_text(label)}</th>" for label, a, w in zip(block["header"], aligns, widths)
            )
            body = "".join(
                "<tr>" + "".join(f"<td style='text-align:{a}'>{_multiline(value)}</td>" for value, a in zip(row, aligns)) + "</tr>"
                for row in block["rows"]
            )
            # No <thead>/<tbody>: PyMuPDF's repeated-header handling draws stray header bars on later pages.
            parts.append(f"<table style='width:{sum(widths)}%'><tr>{head}</tr>{body}</table>")
        elif kind == "blank_bullets":
            parts.append("<ul>" + "<li style='border-bottom: 0.5pt solid #9aa7b8'>&nbsp;</li>" * block["count"] + "</ul>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def _pdf_from_blocks(blocks) -> BytesIO:
    laid_out = BytesIO()
    writer = pymupdf.DocumentWriter(laid_out)
    story = pymupdf.Story(html=_html_from_blocks(blocks), user_css=PDF_CSS)
    more = 1
    while more:
        device = writer.begin_page(PDF_PAGE)
        more, _ = story.place(PDF_TEXT_AREA)
        story.draw(device)
        writer.end_page()
    writer.close()

    document = pymupdf.open(stream=laid_out.getvalue(), filetype="pdf")
    total = document.page_count
    for number, page in enumerate(document, start=1):
        page.insert_text(
            pymupdf.Point(54, PDF_PAGE.height - 36),
            f"Academic plan · page {number} of {total}",
            fontsize=8, fontname="helv", color=(0.35, 0.4, 0.47),
        )
    document.set_metadata({"title": "Academic Plan", "author": "OnTrack"})
    output = BytesIO(document.tobytes(garbage=3, deflate=True))
    document.close()
    return output


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def render_plan_docx(draft_plan: dict, layout: str = DEFAULT_LAYOUT, institution_line: str = "") -> BytesIO:
    return _docx_from_blocks(build_blocks(draft_plan, layout, institution_line))


def render_plan_pdf(draft_plan: dict, layout: str = DEFAULT_LAYOUT, institution_line: str = "") -> BytesIO:
    return _pdf_from_blocks(build_blocks(draft_plan, layout, institution_line))


def render_plan(draft_plan: dict, layout: str = DEFAULT_LAYOUT, file_type: str = DEFAULT_FILE_TYPE, institution_line: str = "") -> BytesIO:
    """Unknown layouts and file types fall back to the defaults. `institution_line` is printed above the title when set."""
    if file_type == "pdf":
        return render_plan_pdf(draft_plan, layout, institution_line)
    return render_plan_docx(draft_plan, layout, institution_line)


def content_type_for(file_type: str) -> str:
    return PDF_CONTENT_TYPE if file_type == "pdf" else DOCX_CONTENT_TYPE
