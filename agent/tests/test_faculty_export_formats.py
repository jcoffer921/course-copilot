from io import BytesIO

import pytest
from docx import Document

from agent.services import plan_export, plan_state

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


# ---- Task 10: export endpoint `format` option ----

from rest_framework.test import APIClient

from agent.models import UserSettings

EXPORT_URL = "/api/faculty/plan/export/"


def _faculty_client(django_user_model, with_draft=True):
    user = django_user_model.objects.create_user(username="export-format-faculty")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=UserSettings.ROLE_FACULTY)
    client = APIClient()
    client.force_authenticate(user=user)
    if with_draft:
        plan_state.write(user, {
            "program_requirement_id": "00000000-0000-0000-0000-000000000000",
            "student_details": {"name": "Hidden Student"},
            "conversation": [{"role": "user", "content": "private conversation text"}],
            "draft_plan": _draft(),
        })
    return client


def _exported_document(response):
    return Document(BytesIO(b"".join(response.streaming_content)))


@pytest.mark.django_db
def test_export_defaults_to_term_table_without_body(django_user_model):
    response = _faculty_client(django_user_model).post(EXPORT_URL)

    assert response.status_code == 200
    assert len(_exported_document(response).tables) == 2


@pytest.mark.django_db
def test_export_honors_year_grid(django_user_model):
    response = _faculty_client(django_user_model).post(EXPORT_URL, {"format": "year_grid"}, format="json")

    assert response.status_code == 200
    assert len(_exported_document(response).tables) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["bogus", "", None, 7])
def test_export_unknown_format_falls_back_and_returns_200(django_user_model, value):
    response = _faculty_client(django_user_model).post(EXPORT_URL, {"format": value}, format="json")

    assert response.status_code == 200
    assert len(_exported_document(response).tables) == 2


@pytest.mark.django_db
def test_export_without_draft_still_400(django_user_model):
    response = _faculty_client(django_user_model, with_draft=False).post(EXPORT_URL, {"format": "year_grid"}, format="json")

    assert response.status_code == 400
    assert response.data["detail"] == "Create a draft plan before downloading it."


@pytest.mark.django_db
@pytest.mark.parametrize("layout", LAYOUTS)
def test_export_contains_no_session_metadata(django_user_model, layout):
    response = _faculty_client(django_user_model).post(EXPORT_URL, {"format": layout}, format="json")

    document = _exported_document(response)
    everything = "\n".join(p.text for p in document.paragraphs) + "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )
    assert "private conversation text" not in everything
    assert "Hidden Student" not in everything


# ---- Final review fixes: grounded export values and session-mismatch guard ----

import uuid

from agent.models import ProgramRequirement


def _client_with_program_session(django_user_model, username="export-grounding-faculty"):
    user = django_user_model.objects.create_user(username=username)
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=UserSettings.ROLE_FACULTY)
    program = ProgramRequirement.objects.create(
        user=user, program_name="B.S. Test", catalog_year="2026",
        requirements={"program_name": "B.S. Test", "catalog_year": "2026", "total_credits_required": 120, "categories": [
            {"name": "Core", "credits_required": 7, "courses": [
                {"code": "CS 201", "title": "Data Structures", "credits": 3, "prerequisites": [], "notes": ""},
            ]},
        ]},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    plan_state.write(user, {
        "program_requirement_id": str(program.requirement_id),
        "student_details": {}, "conversation": [],
        "draft_plan": {
            "student_major": "Computer Science",
            "semesters": [{"label": "Fall", "courses": [{"code": "CS 201", "title": "Wrong Model Title", "credits": 4}]}],
            "total_credits": 99, "notes": "",
        },
    })
    return client, program


def _doc_text(response):
    document = _exported_document(response)
    return "\n".join(p.text for p in document.paragraphs) + "\n" + "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )


@pytest.mark.django_db
@pytest.mark.parametrize("layout", LAYOUTS)
def test_export_uses_program_credits_titles_and_total(django_user_model, layout):
    client, _ = _client_with_program_session(django_user_model)

    response = client.post(EXPORT_URL, {"format": layout}, format="json")

    text = _doc_text(response)
    assert response.status_code == 200
    assert "Data Structures" in text
    assert "Wrong Model Title" not in text
    assert "Total planned credits: 3" in text
    assert "99" not in text


@pytest.mark.django_db
def test_export_rejects_a_plan_from_a_different_program(django_user_model):
    client, program = _client_with_program_session(django_user_model, "export-mismatch-faculty")

    mismatch = client.post(EXPORT_URL, {"program_requirement_id": str(uuid.uuid4())}, format="json")
    match = client.post(EXPORT_URL, {"program_requirement_id": str(program.requirement_id)}, format="json")
    absent = client.post(EXPORT_URL)

    assert mismatch.status_code == 409
    assert "different" in mismatch.data["detail"]
    assert match.status_code == 200
    assert absent.status_code == 200


# ---- PDF export ----

import pymupdf


def _pdf(draft, layout="term_table"):
    buffer = plan_export.render_plan_pdf(draft, layout)
    return pymupdf.open(stream=buffer.getvalue(), filetype="pdf")


def _pdf_text(document):
    # NFKC folds typographic ligatures (such as the "fi" ligature) and no-break spaces, as PDF viewers do when searching.
    import unicodedata

    return unicodedata.normalize("NFKC", "\n".join(page.get_text() for page in document))


def test_pdf_constants():
    assert plan_export.FILE_TYPES == ("docx", "pdf")
    assert plan_export.DEFAULT_FILE_TYPE == "docx"
    assert plan_export.PDF_CONTENT_TYPE == "application/pdf"


def test_pdf_term_table_lists_courses_credits_and_total():
    text = _pdf_text(_pdf(_draft()))

    for expected in ("Academic Plan", "Computer Science", "Fall 2026", "CS 101", "Intro to Programming",
                     "MATH 230", "Spring 2027", "CS 201", "Total planned credits: 10", "Confirm elective availability."):
        assert expected in text, expected


def test_pdf_year_grid_shows_every_term_label_and_course():
    text = _pdf_text(_pdf(_draft(), "year_grid"))

    for expected in ("Fall 2026", "Spring 2027", "CS 101", "MATH 230", "CS 201"):
        assert expected in text, expected


def test_pdf_plan_notes_has_followup_sections():
    text = _pdf_text(_pdf(_draft(), "plan_notes"))

    assert "Flagged issues and follow-ups" in text
    assert "Action items" in text


@pytest.mark.parametrize("layout", LAYOUTS)
def test_pdf_empty_semesters_still_valid(layout):
    document = _pdf(_draft([], notes=""), layout)

    assert document.page_count >= 1
    assert "Academic Plan" in _pdf_text(document)


def test_pdf_long_plan_spans_pages_with_page_numbers():
    semesters = [
        {"label": f"Term {i}", "courses": [{"code": f"CS {i}0{j}", "title": f"Course number {i}-{j}", "credits": 3} for j in range(1, 7)]}
        for i in range(1, 13)
    ]

    document = _pdf(_draft(semesters))

    assert document.page_count > 1
    last = document[document.page_count - 1].get_text()
    assert f"page {document.page_count} of {document.page_count}" in last
    assert "Term 12" in _pdf_text(document)


def test_pdf_keeps_accented_and_cyrillic_text():
    draft = _draft([{"label": "Осень 2026", "courses": [{"code": "CS 101", "title": "Introducción à la programmation, Müller", "credits": 3}]}])

    text = _pdf_text(_pdf(draft))

    assert "Осень 2026" in text
    assert "Introducción à la programmation, Müller" in text


def test_pdf_shows_markup_literally_instead_of_interpreting_it():
    draft = _draft([{"label": "Fall <b>2026</b>", "courses": [{"code": "CS 101", "title": "Tom & Jerry <script>alert(1)</script>", "credits": 3}]}])

    text = _pdf_text(_pdf(draft))

    assert "Fall <b>2026</b>" in text
    assert "Tom & Jerry <script>alert(1)</script>" in text


def test_pdf_wraps_a_very_long_title_without_losing_it():
    long_title = "Advanced Topics in " + "Interdisciplinary Computational Methods and Applications " * 4
    draft = _draft([{"label": "Fall", "courses": [{"code": "CS 999", "title": long_title.strip(), "credits": 3}]}])

    text = " ".join(_pdf_text(_pdf(draft)).split())

    assert long_title.strip() in text


# ---- PDF through the API ----


def _post(client, body=None):
    return client.post(EXPORT_URL, body, format="json")


@pytest.mark.django_db
def test_export_pdf_returns_a_pdf_with_a_pdf_filename(django_user_model):
    response = _post(_faculty_client(django_user_model), {"file_type": "pdf"})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith('attachment; filename="academic-plan-')
    assert response["Content-Disposition"].endswith('.pdf"')
    body = b"".join(response.streaming_content)
    assert body.startswith(b"%PDF")


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["exe", "", None, 7, "PDF "])
def test_export_unknown_file_type_falls_back_to_docx(django_user_model, value):
    response = _post(_faculty_client(django_user_model), {"file_type": value})

    assert response.status_code == 200
    assert response["Content-Type"] == plan_export.DOCX_CONTENT_TYPE
    assert response["Content-Disposition"].endswith('.docx"')


@pytest.mark.django_db
@pytest.mark.parametrize("layout", LAYOUTS)
def test_pdf_export_uses_program_values_and_no_session_metadata(django_user_model, layout):
    client, _ = _client_with_program_session(django_user_model, f"pdf-grounding-{layout}")

    response = _post(client, {"file_type": "pdf", "format": layout})

    text = _pdf_text(pymupdf.open(stream=b"".join(response.streaming_content), filetype="pdf"))
    assert response.status_code == 200
    assert "Data Structures" in text
    assert "Wrong Model Title" not in text
    assert "Total planned credits: 3" in text


@pytest.mark.django_db
def test_pdf_export_hides_conversation_and_student_details(django_user_model):
    response = _post(_faculty_client(django_user_model), {"file_type": "pdf"})

    text = _pdf_text(pymupdf.open(stream=b"".join(response.streaming_content), filetype="pdf"))
    assert "private conversation text" not in text
    assert "Hidden Student" not in text


@pytest.mark.django_db
def test_pdf_export_applies_the_same_session_mismatch_guard(django_user_model):
    client, _ = _client_with_program_session(django_user_model, "pdf-mismatch-faculty")

    response = _post(client, {"file_type": "pdf", "program_requirement_id": str(uuid.uuid4())})

    assert response.status_code == 409


@pytest.mark.django_db
def test_pdf_export_without_a_draft_is_still_400(django_user_model):
    response = _post(_faculty_client(django_user_model, with_draft=False), {"file_type": "pdf"})

    assert response.status_code == 400


def _header_bands(page):
    """Count the dark-blue horizontal bands on a page (the table header rows) by sampling one pixel column."""
    pixmap = page.get_pixmap(dpi=50)
    x = pixmap.width // 2  # the middle of the page, which every table's header row spans
    bands, inside = 0, False
    for y in range(pixmap.height):
        r, g, b = pixmap.pixel(x, y)[:3]
        blue = abs(r - 0x1E) < 24 and abs(g - 0x40) < 24 and abs(b - 0x7C) < 24
        if blue and not inside:
            bands += 1
        inside = blue
    return bands


def test_pdf_has_no_stray_header_bars_on_later_pages():
    semesters = [
        {"label": f"Term {i}", "courses": [{"code": f"CS {i}0{j}", "title": f"Course number {i}-{j}", "credits": 3} for j in range(1, 8)]}
        for i in range(1, 9)
    ]

    document = _pdf(_draft(semesters))

    assert document.page_count > 1
    for page in document:
        headers = len([word for word in page.get_text("words") if word[4] == "Credits"])
        assert _header_bands(page) == headers, f"page {page.number + 1}"


def test_pdf_table_columns_keep_course_codes_on_one_line():
    draft = _draft([{"label": "Spring", "courses": [
        {"code": "CS 320", "title": "Operating Systems", "credits": 4},
        {"code": "CS 350", "title": "Software Engineering and Professional Practice with a Deliberately Long Title That Must Wrap", "credits": 3},
    ]}])

    text = _pdf_text(_pdf(draft))

    assert "CS 320 " in text.replace("\n", " ") and "CS\n320" not in text
    assert "CS\n350" not in text


def test_pdf_grid_headers_do_not_wrap_for_three_terms():
    semesters = [
        {"label": "Fall 2026", "courses": [{"code": "CS 101", "title": "Introduction to Programming", "credits": 3},
                                           {"code": "MATH 230", "title": "Discrete Mathematics", "credits": 3}]},
        {"label": "Spring 2027", "courses": [{"code": "CS 350", "title": "Software Engineering and Professional Practice", "credits": 3}]},
        {"label": "Summer 2027", "courses": []},
    ]

    text = _pdf_text(_pdf(_draft(semesters), "year_grid"))

    assert "Summer 2027" in text
    assert "Summer\n2027" not in text

    # equal-width columns: the header labels sit at equal distances from one another
    page = _pdf(_draft(semesters), "year_grid")[0]
    starts = [page.search_for(label)[0].x0 for label in ("Fall 2026", "Spring 2027", "Summer 2027")]
    assert abs((starts[1] - starts[0]) - (starts[2] - starts[1])) < 12, starts
