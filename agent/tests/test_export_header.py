import unicodedata
from io import BytesIO

import pymupdf
import pytest
from docx import Document
from rest_framework.test import APIClient

from agent.models import UserSettings
from agent.services import export_header, plan_export, plan_state

URL = "/api/faculty/export-header/"
EXPORT_URL = "/api/faculty/plan/export/"
LINE = "The Pennsylvania State University · College of Information Sciences and Technology"


def make_client(django_user_model, username, role=UserSettings.ROLE_FACULTY):
    user = django_user_model.objects.create_user(username=username)
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def faculty_client(django_user_model):
    return make_client(django_user_model, "header-faculty")


@pytest.fixture
def other_client(django_user_model):
    return make_client(django_user_model, "header-other")


@pytest.fixture
def student_client(django_user_model):
    return make_client(django_user_model, "header-student", UserSettings.ROLE_STUDENT)


# ---- normalize ----


def test_normalize_trims_and_collapses_whitespace_and_line_breaks():
    assert export_header.normalize("  The   Pennsylvania\nState \t University  ·  IST \r\n") == "The Pennsylvania State University · IST"


def test_normalize_drops_control_characters():
    assert export_header.normalize("Penn\x00 State\x07") == "Penn State"


def test_normalize_caps_the_length_without_a_trailing_space():
    result = export_header.normalize("word " * 100)

    assert len(result) <= export_header.MAX_LENGTH == 160
    assert result == result.rstrip()


def test_normalize_keeps_markup_as_literal_text_and_non_latin_letters():
    assert export_header.normalize("<b>Penn</b> & Müller Осень") == "<b>Penn</b> & Müller Осень"


@pytest.mark.parametrize("value", [None, "", "   \n\t "])
def test_normalize_turns_nothing_into_an_empty_line(value):
    assert export_header.normalize(value) == ""


# ---- store ----


@pytest.mark.django_db
def test_default_is_empty_and_set_round_trips(faculty_client):
    assert export_header.get_for_user(faculty_client.user) == ""

    saved = export_header.set_for_user(faculty_client.user, f"  {LINE}  ")

    assert saved == LINE
    assert export_header.get_for_user(faculty_client.user) == LINE


@pytest.mark.django_db
def test_get_for_a_user_without_a_settings_row_is_empty(django_user_model):
    user = django_user_model.objects.create_user(username="no-settings-row")

    assert export_header.get_for_user(user) == ""


# ---- API ----


@pytest.mark.django_db
def test_get_returns_empty_by_default(faculty_client):
    response = faculty_client.get(URL)

    assert response.status_code == 200
    assert response.data == {"export_header_line": ""}


@pytest.mark.django_db
def test_put_saves_the_normalized_line_and_returns_it(faculty_client):
    response = faculty_client.put(URL, {"export_header_line": f"  {LINE}\n"}, format="json")

    assert response.status_code == 200
    assert response.data == {"export_header_line": LINE}
    assert faculty_client.get(URL).data == {"export_header_line": LINE}


@pytest.mark.django_db
def test_put_an_empty_string_clears_the_line(faculty_client):
    faculty_client.put(URL, {"export_header_line": LINE}, format="json")

    response = faculty_client.put(URL, {"export_header_line": ""}, format="json")

    assert response.status_code == 200
    assert response.data == {"export_header_line": ""}


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"export_header_line": 5}, {"export_header_line": ["a"]}, {"export_header_line": None}])
def test_put_rejects_a_missing_or_non_string_value(faculty_client, body):
    assert faculty_client.put(URL, body, format="json").status_code == 400


@pytest.mark.django_db
def test_each_faculty_member_has_their_own_line(faculty_client, other_client):
    faculty_client.put(URL, {"export_header_line": "Mine"}, format="json")

    assert other_client.get(URL).data == {"export_header_line": ""}
    other_client.put(URL, {"export_header_line": "Theirs"}, format="json")
    assert faculty_client.get(URL).data == {"export_header_line": "Mine"}


@pytest.mark.django_db
def test_students_get_404_and_cannot_write(student_client):
    assert student_client.get(URL).status_code == 404
    assert student_client.put(URL, {"export_header_line": "x"}, format="json").status_code == 404
    assert export_header.get_for_user(student_client.user) == ""


@pytest.mark.django_db
def test_anonymous_requests_are_refused():
    assert APIClient().get(URL).status_code in (401, 403)


@pytest.mark.django_db
def test_account_data_export_includes_the_line(faculty_client):
    from agent.services import accounts

    export_header.set_for_user(faculty_client.user, LINE)

    assert accounts.export_account_data(faculty_client.user)["profile"]["export_header_line"] == LINE


# ---- layout + both file types ----

DRAFT = {
    "student_major": "Computer Science",
    "semesters": [{"label": "Fall 2026", "courses": [{"code": "CS 101", "title": "Intro", "credits": 3}]}],
    "total_credits": 3,
    "notes": "",
}
LAYOUTS = ("term_table", "year_grid", "plan_notes")


def _pdf_text(buffer):
    document = pymupdf.open(stream=buffer.getvalue(), filetype="pdf")
    return unicodedata.normalize("NFKC", "\n".join(page.get_text() for page in document))


def _docx_paragraphs(buffer):
    return [p.text for p in Document(BytesIO(buffer.getvalue())).paragraphs]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_blocks_start_with_the_institution_line_only_when_set(layout):
    with_line = plan_export.build_blocks(DRAFT, layout, institution_line=LINE)
    without = plan_export.build_blocks(DRAFT, layout)

    assert with_line[0] == {"type": "institution", "text": LINE}
    assert with_line[1]["type"] == "title"
    assert without[0]["type"] == "title"
    assert all(block["type"] != "institution" for block in without)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_pdf_shows_the_line_above_the_title(layout):
    text = _pdf_text(plan_export.render_plan_pdf(DRAFT, layout, institution_line=LINE))

    assert " ".join(text.split()).index(LINE) < text.index("Academic Plan")


@pytest.mark.parametrize("layout", LAYOUTS)
def test_docx_shows_the_line_above_the_title(layout):
    paragraphs = _docx_paragraphs(plan_export.render_plan_docx(DRAFT, layout, institution_line=LINE))

    assert paragraphs[0] == LINE
    assert "Academic Plan" in paragraphs


@pytest.mark.parametrize("renderer", [plan_export.render_plan_pdf, plan_export.render_plan_docx])
def test_nothing_extra_appears_when_the_line_is_empty(renderer):
    buffer = renderer(DRAFT, "term_table")
    if renderer is plan_export.render_plan_pdf:
        assert "Pennsylvania" not in _pdf_text(buffer)
    else:
        assert _docx_paragraphs(buffer)[0] != LINE


def test_pdf_wraps_a_long_line_and_shows_markup_literally():
    long_line = "Department of " + "Interdisciplinary Computational Sciences and Applications " * 2 + "<b>& Co</b>"

    text = " ".join(_pdf_text(plan_export.render_plan_pdf(DRAFT, institution_line=long_line)).split())

    assert long_line.strip() in text


def test_pdf_keeps_accented_and_cyrillic_letters_in_the_line():
    line = "Университет · Universität Zürich"

    assert line in _pdf_text(plan_export.render_plan_pdf(DRAFT, institution_line=line))


# ---- export endpoint uses the saved line, never one sent by the client ----


def _seed(client):
    plan_state.write(client.user, {
        "program_requirement_id": "00000000-0000-0000-0000-000000000000",
        "student_details": {}, "conversation": [], "draft_plan": DRAFT,
    })


def _body(response):
    return BytesIO(b"".join(response.streaming_content))


@pytest.mark.django_db
def test_pdf_export_uses_the_saved_line(faculty_client):
    export_header.set_for_user(faculty_client.user, LINE)
    _seed(faculty_client)

    response = faculty_client.post(EXPORT_URL, {"file_type": "pdf"}, format="json")

    assert response.status_code == 200
    assert LINE in " ".join(_pdf_text(_body(response)).split())


@pytest.mark.django_db
def test_docx_export_uses_the_saved_line(faculty_client):
    export_header.set_for_user(faculty_client.user, LINE)
    _seed(faculty_client)

    response = faculty_client.post(EXPORT_URL, {"file_type": "docx"}, format="json")

    assert _docx_paragraphs(_body(response))[0] == LINE


@pytest.mark.django_db
def test_export_without_a_saved_line_has_no_header(faculty_client):
    _seed(faculty_client)

    response = faculty_client.post(EXPORT_URL, {"file_type": "pdf"}, format="json")

    assert "Pennsylvania" not in _pdf_text(_body(response))


@pytest.mark.django_db
def test_a_line_sent_in_the_export_request_is_ignored(faculty_client):
    _seed(faculty_client)

    response = faculty_client.post(
        EXPORT_URL, {"file_type": "pdf", "institution_line": "Forged University", "export_header_line": "Forged University"}, format="json",
    )

    assert "Forged University" not in _pdf_text(_body(response))
