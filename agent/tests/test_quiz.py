import pytest

from agent.services import mastery, quiz, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_recent_attempts_newest_first(isolated_courses_dir):
    storage.append_quiz_attempt("cs101", {"topic": "A", "timestamp": "2026-01-01T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "B", "timestamp": "2026-01-03T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "C", "timestamp": "2026-01-02T00:00:00"})

    attempts = quiz.recent_attempts("cs101")

    assert [a["topic"] for a in attempts] == ["B", "C", "A"]


def test_recent_attempts_respects_limit(isolated_courses_dir):
    for i in range(5):
        storage.append_quiz_attempt("cs101", {"topic": str(i), "timestamp": f"2026-01-0{i + 1}T00:00:00"})

    attempts = quiz.recent_attempts("cs101", limit=2)

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


def _seed_quizzable_course(course_id="cs101"):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": "Test Course",
        "dates": [],
        "grading": [],
        "topics": ["A"],
    })
    storage.write_notes(course_id, "lecture01", {
        "lecture_id": "lecture01",
        "source": "notes",
        "topics": ["A"],
        "chunks": [{"id": "chunk1", "topic": "A", "text": "A closure captures variables from an outer scope."}],
    })


def _seed_multi_topic_course(course_id="cs101"):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": "Test Course",
        "dates": [],
        "grading": [],
        "topics": ["Weak", "Developing", "Strong", "Fresh"],
    })
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
    })


def test_topic_quiz_weight_drops_as_mastery_improves():
    assert quiz._topic_quiz_weight(0.2) > quiz._topic_quiz_weight(0.5)
    assert quiz._topic_quiz_weight(0.5) > quiz._topic_quiz_weight(0.8)
    assert quiz._topic_quiz_weight(1.0) > 0


def test_pick_chunk_weights_weak_topics_above_strong_topics(isolated_courses_dir, monkeypatch):
    _seed_multi_topic_course()
    for index in range(2):
        storage.append_quiz_attempt("cs101", {
            "topic": "Weak",
            "correct": False,
            "timestamp": f"2026-01-0{index + 1}T00:00:00",
        })
        storage.append_quiz_attempt("cs101", {
            "topic": "Developing",
            "correct": True,
            "timestamp": f"2026-01-1{index + 1}T00:00:00",
        })
        storage.append_quiz_attempt("cs101", {
            "topic": "Strong",
            "correct": True,
            "timestamp": f"2026-01-2{index + 1}T00:00:00",
        })
    storage.append_quiz_attempt("cs101", {
        "topic": "Developing",
        "correct": False,
        "timestamp": "2026-01-13T00:00:00",
    })
    mastery.rebuild_scores("cs101")

    captured = {}

    def fake_choices(population, weights, k):
        captured["weights"] = dict(zip(population, weights))
        return ["Weak"]

    monkeypatch.setattr(quiz.random, "choices", fake_choices)
    chunk = quiz.pick_chunk("cs101")

    assert chunk["topic"] == "Weak"
    assert captured["weights"]["Weak"] > captured["weights"]["Developing"]
    assert captured["weights"]["Developing"] > captured["weights"]["Strong"]
    assert captured["weights"]["Fresh"] > captured["weights"]["Strong"]


async def test_generate_flashcards_uses_haiku_and_scoped_web_search(isolated_courses_dir, monkeypatch):
    _seed_quizzable_course()
    storage.write_trusted_domains("cs101", ["docs.python.org"])
    response = _FakeResponse(
        '{"flashcards":[{"term":"Closure","definition":"A function value with captured state.","source":"course","url":null}]}'
    )
    fake_client = _FakeClient(response)
    monkeypatch.setattr(quiz, "get_client", lambda: fake_client)

    deck = await quiz.generate_flashcards_async("cs101", chunk_id="chunk1")

    assert deck["model"] == quiz.MODEL_HAIKU
    assert deck["flashcards"][0]["term"] == "Closure"
    assert fake_client.messages.calls[0]["model"] == quiz.MODEL_HAIKU
    assert fake_client.messages.calls[0]["tools"] == [{
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": quiz.WEB_SEARCH_MAX_USES,
    }]


async def test_generate_flashcards_strips_citation_markup(isolated_courses_dir, monkeypatch):
    _seed_quizzable_course()
    response = _FakeResponse(
        '{"flashcards":[{"term":"&lt;cite index=\\"1-1\\"&gt;WebGL&lt;/cite&gt;",'
        '"definition":"<cite index=\\"1-1\\">JavaScript API for 3D graphics.</cite>",'
        '"source":"web","url":"https://developer.mozilla.org/"}]}'
    )
    monkeypatch.setattr(quiz, "get_client", lambda: _FakeClient(response))

    deck = await quiz.generate_flashcards_async("cs101", chunk_id="chunk1")

    assert deck["flashcards"][0]["term"] == "WebGL"
    assert deck["flashcards"][0]["definition"] == "JavaScript API for 3D graphics."


async def test_generate_flashcards_extracts_json_from_preamble_and_markdown_url(isolated_courses_dir, monkeypatch):
    _seed_quizzable_course()
    response = _FakeResponse(
        'Based on the course material, here are cards:\n'
        '```json\n'
        '{"flashcards":[{"term":"WebGL","definition":"A 3D graphics API.",'
        '"source":"course+web","url":"[https://www.khronos.org/webgl/](https://www.khronos.org/webgl/)"}]}\n'
        '```'
    )
    monkeypatch.setattr(quiz, "get_client", lambda: _FakeClient(response))

    deck = await quiz.generate_flashcards_async("cs101", chunk_id="chunk1")

    assert deck["flashcards"][0]["term"] == "WebGL"
    assert deck["flashcards"][0]["url"] == "https://www.khronos.org/webgl/"


async def test_generate_assessment_question_uses_sonnet_with_flashcard_context(isolated_courses_dir, monkeypatch):
    _seed_quizzable_course()
    response = _FakeResponse(
        '{"question":"Which statement best describes a closure?","choices":["Captured state","A loop","A class","A file"],"correct_answer":"Captured state"}'
    )
    fake_client = _FakeClient(response)
    monkeypatch.setattr(quiz, "get_client", lambda: fake_client)
    flashcards = [{"term": "Closure", "definition": "A function value with captured state."}]

    question = await quiz.generate_assessment_question_async("cs101", chunk_id="chunk1", flashcards=flashcards)

    call = fake_client.messages.calls[0]
    assert question["model"] == quiz.MODEL_ASSESSMENT
    assert call["model"] == quiz.MODEL_ASSESSMENT
    assert "Closure" in call["messages"][0]["content"]
