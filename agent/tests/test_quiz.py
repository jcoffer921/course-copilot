import pytest
from asgiref.sync import sync_to_async

from agent.services import mastery, quiz, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_recent_attempts_newest_first(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="recent-owner")
    storage.append_quiz_attempt("cs101", {"topic": "A", "timestamp": "2026-01-01T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "B", "timestamp": "2026-01-03T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "C", "timestamp": "2026-01-02T00:00:00"}, user=user)

    attempts = quiz.recent_attempts("cs101", user=user)

    assert [a["topic"] for a in attempts] == ["B", "C", "A"]


def test_recent_attempts_respects_limit(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="limit-owner")
    for i in range(5):
        storage.append_quiz_attempt("cs101", {"topic": str(i), "timestamp": f"2026-01-0{i + 1}T00:00:00"}, user=user)

    attempts = quiz.recent_attempts("cs101", limit=2, user=user)

    assert len(attempts) == 2
    assert [a["topic"] for a in attempts] == ["4", "3"]


def test_recent_attempts_empty_for_new_course(isolated_courses_dir):
    assert quiz.recent_attempts("brandnew") == []


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResponse:
    stop_reason = "end_turn"

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


def _seed_quizzable_course(user, course_id="cs101"):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": "Test Course",
        "dates": [],
        "grading": [],
        "topics": ["A"],
    }, user)
    storage.write_notes(course_id, "lecture01", {
        "lecture_id": "lecture01",
        "source": "notes",
        "topics": ["A"],
        "chunks": [{"id": "chunk1", "topic": "A", "text": "A closure captures variables from an outer scope."}],
    }, user)


def _seed_multi_topic_course(user, course_id="cs101"):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": "Test Course",
        "dates": [],
        "grading": [],
        "topics": ["Weak", "Developing", "Strong", "Fresh"],
    }, user)
    storage.write_notes(course_id, "lecture01", {
        "lecture_id": "lecture01",
        "source": "notes",
        "topics": ["Weak", "Developing", "Strong", "Fresh"],
        "chunks": [
            {"id": "weak-chunk", "topic": "Weak", "text": "Weak topic notes."},
            {"id": "developing-chunk", "topic": "Developing", "text": "Developing topic notes."},
            {"id": "strong-chunk", "topic": "Strong", "text": "Strong topic notes."},
            {"id": "fresh-chunk", "topic": "Fresh", "text": "Unassessed topic notes."},
        ],
    }, user)


def test_topic_quiz_weight_drops_as_mastery_improves():
    assert quiz._topic_quiz_weight(0.2) > quiz._topic_quiz_weight(0.5)
    assert quiz._topic_quiz_weight(0.5) > quiz._topic_quiz_weight(0.8)
    assert quiz._topic_quiz_weight(1.0) > 0


def test_pick_chunk_weights_weak_topics_above_strong_topics(isolated_courses_dir, monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="pick-chunk-weights", email="pick-chunk-weights@example.com")
    _seed_multi_topic_course(user)
    for index in range(2):
        storage.append_quiz_attempt("cs101", {
            "topic": "Weak",
            "correct": False,
            "timestamp": f"2026-01-0{index + 1}T00:00:00",
        }, user=user)
        storage.append_quiz_attempt("cs101", {
            "topic": "Developing",
            "correct": True,
            "timestamp": f"2026-01-1{index + 1}T00:00:00",
        }, user=user)
        storage.append_quiz_attempt("cs101", {
            "topic": "Strong",
            "correct": True,
            "timestamp": f"2026-01-2{index + 1}T00:00:00",
        }, user=user)
    storage.append_quiz_attempt("cs101", {
        "topic": "Developing",
        "correct": False,
        "timestamp": "2026-01-13T00:00:00",
    }, user=user)
    mastery.rebuild_scores("cs101", user=user)

    captured = {}

    def fake_choices(population, weights, k):
        captured["weights"] = dict(zip(population, weights))
        return ["Weak"]

    monkeypatch.setattr(quiz.random, "choices", fake_choices)
    chunk = quiz.pick_chunk("cs101", user=user)

    assert chunk["topic"] == "Weak"
    assert captured["weights"]["Weak"] > captured["weights"]["Developing"]
    assert captured["weights"]["Developing"] > captured["weights"]["Strong"]
    assert captured["weights"]["Fresh"] > captured["weights"]["Strong"]


async def test_generate_flashcards_uses_haiku_and_scoped_web_search(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="flashcards-haiku-web-search", email="flashcards-haiku-web-search@example.com",
    )
    await sync_to_async(_seed_quizzable_course)(user)
    await sync_to_async(storage.write_trusted_domains)("cs101", ["docs.python.org"], user)
    response = _FakeResponse(
        '{"flashcards":[{"term":"Closure","definition":"A function value with captured state.","source":"course","url":null}]}'
    )
    fake_client = _FakeClient(response)
    monkeypatch.setattr(quiz, "get_client", lambda: fake_client)

    deck = await quiz.generate_flashcards_async("cs101", chunk_id="chunk1", user=user)

    assert deck["model"] == quiz.MODEL_HAIKU
    assert deck["flashcards"][0]["term"] == "Closure"
    assert fake_client.messages.calls[0]["model"] == quiz.MODEL_HAIKU
    assert fake_client.messages.calls[0]["tools"] == [{
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": quiz.WEB_SEARCH_MAX_USES,
    }]


async def test_generate_flashcards_strips_citation_markup(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="flashcards-strip-citations", email="flashcards-strip-citations@example.com",
    )
    await sync_to_async(_seed_quizzable_course)(user)
    response = _FakeResponse(
        '{"flashcards":[{"term":"&lt;cite index=\\"1-1\\"&gt;WebGL&lt;/cite&gt;",'
        '"definition":"<cite index=\\"1-1\\">JavaScript API for 3D graphics.</cite>",'
        '"source":"web","url":"https://developer.mozilla.org/"}]}'
    )
    monkeypatch.setattr(quiz, "get_client", lambda: _FakeClient(response))

    deck = await quiz.generate_flashcards_async("cs101", chunk_id="chunk1", user=user)

    assert deck["flashcards"][0]["term"] == "WebGL"
    assert deck["flashcards"][0]["definition"] == "JavaScript API for 3D graphics."


async def test_generate_flashcards_extracts_json_from_preamble_and_markdown_url(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="flashcards-preamble-markdown", email="flashcards-preamble-markdown@example.com",
    )
    await sync_to_async(_seed_quizzable_course)(user)
    response = _FakeResponse(
        'Based on the course material, here are cards:\n'
        '```json\n'
        '{"flashcards":[{"term":"WebGL","definition":"A 3D graphics API.",'
        '"source":"course+web","url":"[https://www.khronos.org/webgl/](https://www.khronos.org/webgl/)"}]}\n'
        '```'
    )
    monkeypatch.setattr(quiz, "get_client", lambda: _FakeClient(response))

    deck = await quiz.generate_flashcards_async("cs101", chunk_id="chunk1", user=user)

    assert deck["flashcards"][0]["term"] == "WebGL"
    assert deck["flashcards"][0]["url"] == "https://www.khronos.org/webgl/"


async def test_generate_assessment_question_uses_sonnet_with_flashcard_context(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="assessment-sonnet-flashcards", email="assessment-sonnet-flashcards@example.com",
    )
    await sync_to_async(_seed_quizzable_course)(user)
    response = _FakeResponse(
        '{"question":"Which statement best describes a closure?","choices":["Captured state","A loop","A class","A file"],"correct_answer":"Captured state"}'
    )
    fake_client = _FakeClient(response)
    monkeypatch.setattr(quiz, "get_client", lambda: fake_client)
    flashcards = [{"term": "Closure", "definition": "A function value with captured state."}]

    question = await quiz.generate_assessment_question_async(
        "cs101", chunk_id="chunk1", flashcards=flashcards, user=user,
    )

    call = fake_client.messages.calls[0]
    assert question["model"] == quiz.MODEL_ASSESSMENT
    assert call["model"] == quiz.MODEL_ASSESSMENT
    assert "Closure" in call["messages"][0]["content"]
    assert question["explanation"] == ""


async def test_generate_assessment_question_returns_model_explanation(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="assessment-explanation", email="assessment-explanation@example.com",
    )
    await sync_to_async(_seed_quizzable_course)(user)
    response = _FakeResponse(
        '{"question":"Which statement best describes a closure?","choices":["Captured state","A loop","A class","A file"],'
        '"correct_answer":"Captured state","explanation":"A closure captures variables from its outer scope."}'
    )
    monkeypatch.setattr(quiz, "get_client", lambda: _FakeClient(response))

    question = await quiz.generate_assessment_question_async("cs101", chunk_id="chunk1", flashcards=[], user=user)

    assert question["explanation"] == "A closure captures variables from its outer scope."


@pytest.mark.parametrize("payload", [
    '{"question":"Q?","choices":["A","B","C"],"correct_answer":"A"}',
    '{"question":"Q?","choices":["A","A","C","D"],"correct_answer":"A"}',
    '{"question":"Q?","choices":["A","B","C","D"],"correct_answer":"E"}',
])
async def test_generate_assessment_question_rejects_malformed_multiple_choice_output(
    isolated_courses_dir, monkeypatch, django_user_model, payload,
):
    user, _ = await sync_to_async(django_user_model.objects.get_or_create)(username="malformed-question-owner")
    await sync_to_async(_seed_quizzable_course)(user)
    monkeypatch.setattr(quiz, "get_client", lambda: _FakeClient(_FakeResponse(payload)))

    with pytest.raises(ValueError):
        await quiz.generate_assessment_question_async("cs101", chunk_id="chunk1", flashcards=[], user=user)


def test_record_attempt_rejects_chunk_that_does_not_belong_to_this_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="record-owner")
    _seed_quizzable_course(user, course_id="cs101")

    with pytest.raises(quiz.InvalidChunkReferenceError):
        quiz.record_attempt(
            "cs101", "other-lecture", "other-chunk", "A",
            "Q?", "correct", "correct", user=user,
        )


def test_record_attempt_rejects_chunk_belonging_to_a_different_users_course(isolated_courses_dir, django_user_model):
    owner = django_user_model.objects.create_user(username="chunk-owner")
    attacker = django_user_model.objects.create_user(username="chunk-attacker")
    _seed_quizzable_course(owner, course_id="cs101")
    # Attacker owns a course with the same course_id but genuinely different
    # chunks, so owner's real "lecture01"/"chunk1" combo is never part of
    # anything the attacker actually has.
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Attacker Course", "dates": [], "grading": [], "topics": ["B"],
    }, attacker)
    storage.write_notes("cs101", "attacker-lecture", {
        "lecture_id": "attacker-lecture", "source": "notes", "topics": ["B"],
        "chunks": [{"id": "attacker-chunk", "topic": "B", "text": "Unrelated attacker content."}],
    }, attacker)

    with pytest.raises(quiz.InvalidChunkReferenceError):
        quiz.record_attempt(
            "cs101", "lecture01", "chunk1", "A",
            "Q?", "correct", "correct", user=attacker,
        )
    assert quiz.recent_attempts("cs101", user=owner) == []


def test_record_attempt_accepts_a_real_owned_chunk(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="record-valid-owner")
    _seed_quizzable_course(user, course_id="cs101")

    result = quiz.record_attempt(
        "cs101", "lecture01", "chunk1", "A",
        "Q?", "correct", "correct", user=user,
    )

    assert result["correct"] is True
