# Ask Grounding Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `ask.py` two new real grounding sources — user-uploaded reference docs and a per-course, human-approved, domain-restricted web search — without weakening CLAUDE.md's "never fabricate" invariant.

**Architecture:** Two independent additions that both plug into `ask_async`'s existing context-stuffing + JSON-envelope pattern. (1) `references.py` is a no-LLM ingestion service (raw text extraction only) with its own storage functions, CLI command, and DRF view, mirroring `chunk_notes.py`'s file-upload shape but skipping the LLM call entirely. (2) `domain_suggestions.py` is an LLM-assisted *suggestion* service (never writes) paired with a plain storage read/write for the human-approved list; `ask_async` reads that list and conditionally adds Anthropic's `web_search_20250305` server-side tool with `allowed_domains` set to it. Both sources join `SYLLABUS`/`NOTES` in `ask_async`'s context, and the system prompt is rewritten to state the two-tier grounding rule (course material first, approved-domain web search only as a fallback) and the redefined `grounded` semantics.

**Tech Stack:** Django 6 + DRF + adrf (async views), Anthropic Python SDK (`AsyncAnthropic`), `pypdf` for PDF text extraction (reused from `syllabus_extraction.py`), pytest + pytest-django + pytest-asyncio (`asyncio_mode = auto`).

## Global Constraints

- Every new storage function follows the existing mirror pattern in `agent/services/storage.py:203-321` — `_course_dir`-relative paths, path-traversal guards via a compiled `_ID_RE` pattern, `FileExistsError` for overwrite-guarded writes, `[]`/`None` returns for "not created yet" states (never raise for a missing-but-expected-empty state).
- Every new service function that calls the Anthropic API is `async def`, imports `MODEL_DEFAULT as MODEL, get_client` from `agent/services/client.py`, and is wrapped in a plain `asyncio.run(...)` call in its CLI command — same as `ask.py`, `chunk_notes.py`, `syllabus_extraction.py`.
- Every new DRF view is an `adrf.views.APIView` subclass with `async def get/post/put`, wraps sync storage calls in `sync_to_async(...)`, and returns `rest_framework.response.Response` with the same status-code conventions already used in `agent/views.py` (400 invalid id / validation, 404 not found, 409 conflict, 422 schema validation failure, 500 corrupt storage, 502 LLM call failed).
- `course_id` and the new `reference_id` are filesystem path segments — always validate through the existing `COURSE_ID_RE` / `LECTURE_ID_RE`-derived regexes, never interpolate raw user input into a path.
- No new dependency: PDF/TXT/MD text extraction reuses `agent/services/syllabus_extraction.py:extract_text_from_bytes` (already handles `.pdf`/`.txt`/`.md`, already in `requirements.txt` via `pypdf`).
- Web search uses tool type `web_search_20250305` (Anthropic's basic, ZDR-eligible server-side web search tool) with `allowed_domains` — not the newer `_20260209` dynamic-filtering variant — per the design doc's explicit choice (no code-execution dependency this single-user project doesn't need).
- Tests that touch disk use the existing `isolated_courses_dir` fixture pattern (`monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)`), duplicated per test file exactly as `test_quiz.py`/`test_mastery.py`/`test_dashboard.py` already do — no shared conftest fixture exists for it, so don't introduce one speculatively.
- Live-API tests follow `test_ask.py`'s existing pattern: `pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a live ANTHROPIC_API_KEY")`, and skip individually when a needed fixture (uploaded reference, approved domains) isn't present rather than failing.

---

### Task 1: `storage.py` — reference doc schema

**Files:**
- Modify: `agent/services/storage.py`
- Test: `agent/tests/test_references.py` (new)

**Interfaces:**
- Produces: `storage.InvalidReferenceIdError`, `storage.ReferencesStorageError`, `storage.REFERENCE_ID_RE`, `storage.validate_reference(data: dict) -> list`, `storage.read_references(course_id: str) -> list`, `storage.read_reference(course_id: str, reference_id: str) -> dict | None`, `storage.write_reference(course_id: str, reference_id: str, data: dict, overwrite: bool = False) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_references.py`:

```python
import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_references_empty_for_new_course(isolated_courses_dir):
    assert storage.read_references("cs101") == []


def test_read_reference_none_when_missing(isolated_courses_dir):
    assert storage.read_reference("cs101", "ch1") is None


def test_write_then_read_reference_roundtrip(isolated_courses_dir):
    data = {"reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello"}
    storage.write_reference("cs101", "ch1", data)

    assert storage.read_reference("cs101", "ch1") == data
    assert storage.read_references("cs101") == [data]


def test_write_reference_raises_on_existing_without_overwrite(isolated_courses_dir):
    data = {"reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello"}
    storage.write_reference("cs101", "ch1", data)

    with pytest.raises(FileExistsError):
        storage.write_reference("cs101", "ch1", data)


def test_validate_reference_rejects_empty_text():
    errors = storage.validate_reference({
        "reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "   ",
    })

    assert any("text" in e for e in errors)


def test_validate_reference_rejects_missing_field():
    errors = storage.validate_reference({"reference_id": "ch1", "title": "Chapter 1"})

    assert any("source_filename" in e for e in errors)
    assert any("text" in e for e in errors)


def test_validate_reference_accepts_valid_data():
    errors = storage.validate_reference({
        "reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello",
    })

    assert errors == []


def test_invalid_reference_id_rejected(isolated_courses_dir):
    with pytest.raises(storage.InvalidReferenceIdError):
        storage.write_reference("cs101", "../escape", {
            "reference_id": "ch1", "title": "x", "source_filename": "x.pdf", "text": "x",
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_references.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.storage' has no attribute 'read_references'` (and similar for the other new names)

- [ ] **Step 3: Add the exception classes and `REFERENCE_ID_RE`**

In `agent/services/storage.py`, after the existing `class NotesStorageError(Exception):` block (around line 43-44), add:

```python
class InvalidReferenceIdError(ValueError):
    """Raised when reference_id isn't a safe filesystem path segment."""


class ReferencesStorageError(Exception):
    """Raised when an existing references/<reference_id>.json on disk is corrupt/unreadable."""
```

Immediately after the existing `LECTURE_ID_RE` definition (around line 26-28), add:

```python
# reference_id becomes a filename under courses/<course_id>/references/ — same
# defense as LECTURE_ID_RE, and reuses it directly rather than duplicating the
# same safe charset under a new name.
REFERENCE_ID_RE = LECTURE_ID_RE
```

- [ ] **Step 4: Add `_reference_path` helper**

Immediately after the existing `_lecture_path` function (ends around line 80), add:

```python
def _reference_path(course_id: str, reference_id: str) -> Path:
    """Resolves courses/<course_id>/references/<reference_id>.json, guarding
    against path traversal via reference_id the same way _lecture_path does
    for lecture_id."""
    if not REFERENCE_ID_RE.fullmatch(reference_id):
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    references_dir = _course_dir(course_id) / "references"
    path = (references_dir / f"{reference_id}.json").resolve()
    if path.parent != references_dir.resolve():
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    return path
```

- [ ] **Step 5: Add `validate_reference`**

Immediately after `validate_notes` (ends around line 196), add:

```python
def validate_reference(data: dict) -> list:
    """Returns a list of error strings. An empty list means the data is
    valid. Unlike notes/syllabus, there are no non-blocking WARNING entries
    here — a reference doc either has usable text or it doesn't."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("reference_id", str)
    require("title", str)
    require("source_filename", str)
    require("text", str)

    if errors:
        return errors  # top-level shape is broken, don't bother checking nested items

    if not data["text"].strip():
        errors.append("'text' is empty — a reference with no extractable content shouldn't be written")

    return errors
```

- [ ] **Step 6: Add `read_references`, `read_reference`, `write_reference`**

Immediately after `write_notes` (ends around line 254), add:

```python
def read_references(course_id: str) -> list:
    """Returns a list of parsed reference dicts for every file under
    courses/<course_id>/references/*.json, sorted by filename. Returns [] if
    references/ doesn't exist yet — that's a normal state, not an error."""
    references_dir = _course_dir(course_id) / "references"
    if not references_dir.exists():
        return []

    references = []
    for path in sorted(references_dir.glob("*.json")):
        try:
            references.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise ReferencesStorageError(f"reference file '{path.name}' for '{course_id}' is corrupt: {e}")
    return references


def read_reference(course_id: str, reference_id: str):
    """Returns the parsed references/<reference_id>.json dict, or None if it
    doesn't exist."""
    path = _reference_path(course_id, reference_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ReferencesStorageError(f"reference file '{reference_id}' for '{course_id}' is corrupt: {e}")


def write_reference(course_id: str, reference_id: str, data: dict, overwrite: bool = False) -> Path:
    """Writes references/<reference_id>.json. Raises FileExistsError if it
    already exists and overwrite=False — same plan-then-pause contract as
    write_notes, even though in practice references.ingest_reference()
    generates reference_id fresh on every call and this path is rarely hit."""
    references_dir = _course_dir(course_id) / "references"
    out_path = _reference_path(course_id, reference_id)

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    references_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest agent/tests/test_references.py -v`
Expected: PASS (9 tests)

- [ ] **Step 8: Commit**

```bash
git add agent/services/storage.py agent/tests/test_references.py
git commit -m "feat: add reference doc storage functions"
```

---

### Task 2: `agent/services/references.py` — no-LLM ingestion

**Files:**
- Create: `agent/services/references.py`
- Modify: `agent/tests/test_references.py`

**Interfaces:**
- Consumes: `storage.write_reference`, `storage.read_reference`, `syllabus_extraction.extract_text_from_bytes(data: bytes, filename: str) -> str`
- Produces: `references.ingest_reference(course_id: str, file_bytes: bytes, filename: str, title: str = None) -> dict` (async) — returns `{"reference_id", "title", "source_filename", "text"}`, not yet written to disk

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_references.py`:

```python
from agent.services import references


async def test_ingest_reference_extracts_txt_and_generates_id(isolated_courses_dir):
    data = await references.ingest_reference(
        "cs101", b"Some textbook content about recursion.", "chapter1.txt", title="Chapter 1: Recursion",
    )

    assert data["reference_id"] == "chapter-1-recursion"
    assert data["title"] == "Chapter 1: Recursion"
    assert data["source_filename"] == "chapter1.txt"
    assert data["text"] == "Some textbook content about recursion."


async def test_ingest_reference_defaults_title_to_filename_stem(isolated_courses_dir):
    data = await references.ingest_reference("cs101", b"content", "notes.md")

    assert data["title"] == "notes"
    assert data["reference_id"] == "notes"


async def test_ingest_reference_dedupes_id_on_collision(isolated_courses_dir):
    storage.write_reference("cs101", "notes", {
        "reference_id": "notes", "title": "notes", "source_filename": "notes.md", "text": "existing",
    })

    data = await references.ingest_reference("cs101", b"content", "notes.md")

    assert data["reference_id"] == "notes-2"


async def test_ingest_reference_rejects_unsupported_file_type(isolated_courses_dir):
    with pytest.raises(ValueError):
        await references.ingest_reference("cs101", b"content", "slides.pptx")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_references.py -v -k ingest_reference`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.services.references'`

- [ ] **Step 3: Write `agent/services/references.py`**

```python
"""
Ingests a reference document (e.g. a textbook chapter) for a course. Unlike
chunk_notes.py (semantic chunking) or syllabus_extraction.py (structured
field extraction), a reference doc just needs its raw text extracted and
stored whole — no LLM call in this file at all. The whole extracted text
gets stuffed into ask.py's context every time, same as syllabus and notes.
"""

import re
from pathlib import Path

from asgiref.sync import sync_to_async

from . import storage
from .syllabus_extraction import extract_text_from_bytes


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "reference"


def _unique_reference_id(course_id: str, base_id: str) -> str:
    """Appends -2, -3, ... on collision so two references with the same
    title/filename don't clobber each other — reference_id is generated
    here, not supplied by the caller, so there's no user-facing overwrite
    decision to make."""
    candidate = base_id
    n = 1
    while storage.read_reference(course_id, candidate) is not None:
        n += 1
        candidate = f"{base_id}-{n}"
    return candidate


async def ingest_reference(course_id: str, file_bytes: bytes, filename: str, title: str = None) -> dict:
    text = extract_text_from_bytes(file_bytes, filename)

    resolved_title = (title or "").strip() or Path(filename).stem
    base_id = _slugify(resolved_title)
    reference_id = await sync_to_async(_unique_reference_id)(course_id, base_id)

    return {
        "reference_id": reference_id,
        "title": resolved_title,
        "source_filename": filename,
        "text": text,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_references.py -v`
Expected: PASS (13 tests total)

- [ ] **Step 5: Commit**

```bash
git add agent/services/references.py agent/tests/test_references.py
git commit -m "feat: add reference doc ingestion service"
```

---

### Task 3: References CLI + API view

**Files:**
- Create: `agent/management/commands/references.py`
- Modify: `agent/serializers.py`
- Modify: `agent/views.py`
- Modify: `agent/urls.py`
- Create: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `references.ingest_reference`, `storage.validate_reference`, `storage.write_reference`, `storage.read_references`
- Produces: `IngestReferenceRequestSerializer`, `views.ReferencesView` (`POST`/`GET` at `courses/<course_id>/references/`)

- [ ] **Step 1: Write the failing view tests**

Create `agent/tests/test_views.py`:

```python
import io

import pytest
from rest_framework.test import APIClient

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def api_client():
    return APIClient()


def _seed_syllabus(course_id):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    })


def test_references_post_then_get(isolated_courses_dir, api_client):
    upload = io.BytesIO(b"Some reference content.")
    upload.name = "chapter1.txt"

    response = api_client.post(
        "/api/courses/cs101/references/", {"file": upload, "title": "Chapter 1"}, format="multipart",
    )

    assert response.status_code == 201
    assert response.data["reference"]["reference_id"] == "chapter-1"
    assert response.data["reference"]["text"] == "Some reference content."

    list_response = api_client.get("/api/courses/cs101/references/")
    assert list_response.status_code == 200
    assert len(list_response.data["references"]) == 1
    assert list_response.data["references"][0]["reference_id"] == "chapter-1"


def test_references_get_empty_for_new_course(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/references/")

    assert response.status_code == 200
    assert response.data["references"] == []


def test_references_post_rejects_unsupported_file_type(isolated_courses_dir, api_client):
    upload = io.BytesIO(b"binary junk")
    upload.name = "slides.pptx"

    response = api_client.post("/api/courses/cs101/references/", {"file": upload}, format="multipart")

    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_views.py -v`
Expected: FAIL with 404s (route doesn't exist yet)

- [ ] **Step 3: Add the serializer**

In `agent/serializers.py`, after `ChunkNotesRequestSerializer` (ends around line 19), add:

```python
class IngestReferenceRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(required=False, allow_blank=True, default=None)
```

- [ ] **Step 4: Add `ReferencesView`**

In `agent/views.py`:

1. Update the services import line (currently `from .services import chunk_notes, dashboard, mastery, quiz, reminders, sessions, storage`) to also import `references`:

```python
from .services import chunk_notes, dashboard, mastery, quiz, references, reminders, sessions, storage
```

2. Update the serializers import to add `IngestReferenceRequestSerializer`:

```python
from .serializers import (
    AskRequestSerializer,
    ChunkNotesRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
)
```

3. After the `ChunkNotesView` class (ends around line 148), add:

```python
class ReferencesView(APIView):
    """
    POST /api/courses/<course_id>/references/
    multipart/form-data: file=<reference pdf/txt/md>, title=<optional>

    No plan-then-pause here — reference_id is generated fresh from the title
    (or filename), with a numeric suffix on collision, so there's no
    existing file for this upload to overwrite the way syllabus/notes
    uploads can collide.

    GET /api/courses/<course_id>/references/ — list all references, [] if none.
    """

    async def post(self, request, course_id):
        serializer = IngestReferenceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload = serializer.validated_data["file"]
        title = serializer.validated_data.get("title") or None

        try:
            data = await references.ingest_reference(course_id, upload.read(), upload.name, title=title)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        errors = storage.validate_reference(data)
        if errors:
            return Response(
                {"detail": "extracted data failed schema validation", "errors": errors, "raw": data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            await sync_to_async(storage.write_reference)(course_id, data["reference_id"], data)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"course_id": course_id, "reference": data},
            status=status.HTTP_201_CREATED,
        )

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(storage.read_references)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.ReferencesStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"references": data}, status=status.HTTP_200_OK)
```

- [ ] **Step 5: Wire the route**

In `agent/urls.py`, after the `chunk-notes` path (around line 10), add:

```python
    path("courses/<slug:course_id>/references/", views.ReferencesView.as_view(), name="references"),
```

- [ ] **Step 6: Run `manage.py check`**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest agent/tests/test_views.py agent/tests/test_references.py -v`
Expected: PASS (16 tests total)

- [ ] **Step 8: Write the CLI command (no dedicated test, matching the existing no-CLI-test convention for `extract_syllabus.py`/`chunk_notes.py`)**

Create `agent/management/commands/references.py`:

```python
import asyncio
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agent.services import references, storage


class Command(BaseCommand):
    help = "Ingest a reference document (PDF/TXT/MD) for a course (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to reference file (PDF/TXT/MD)")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("--title", dest="title", default=None, help="Reference title (defaults to the filename)")

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        try:
            data = asyncio.run(
                references.ingest_reference(
                    options["course_id"], source_path.read_bytes(), source_path.name, title=options["title"],
                )
            )
        except ValueError as e:
            raise CommandError(str(e))

        errors = storage.validate_reference(data)
        if errors:
            self.stdout.write(self.style.ERROR("Schema validation failed:"))
            for e in errors:
                self.stdout.write(f"  - {e}")
            raise CommandError("reference ingestion failed schema validation")

        out_path = storage.write_reference(options["course_id"], data["reference_id"], data)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} (reference_id: {data['reference_id']})"))
```

- [ ] **Step 9: Commit**

```bash
git add agent/management/commands/references.py agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add references CLI command and API view"
```

---

### Task 4: `storage.py` — trusted domains schema

**Files:**
- Modify: `agent/services/storage.py`
- Test: `agent/tests/test_domains.py` (new)

**Interfaces:**
- Produces: `storage.TrustedDomainsStorageError`, `storage.validate_trusted_domains(data: dict) -> list`, `storage.read_trusted_domains(course_id: str) -> list`, `storage.write_trusted_domains(course_id: str, domains: list) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_domains.py`:

```python
import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_trusted_domains_empty_before_approval(isolated_courses_dir):
    assert storage.read_trusted_domains("cs101") == []


def test_write_then_read_trusted_domains_roundtrip(isolated_courses_dir):
    storage.write_trusted_domains("cs101", ["docs.python.org", "nist.gov"])

    assert storage.read_trusted_domains("cs101") == ["docs.python.org", "nist.gov"]


def test_write_trusted_domains_always_overwrites(isolated_courses_dir):
    storage.write_trusted_domains("cs101", ["a.com"])
    storage.write_trusted_domains("cs101", ["b.com"])

    assert storage.read_trusted_domains("cs101") == ["b.com"]


def test_validate_trusted_domains_rejects_empty_domain_string():
    errors = storage.validate_trusted_domains({"course_id": "cs101", "domains": ["good.com", ""]})

    assert any("domains[1]" in e for e in errors)


def test_validate_trusted_domains_rejects_missing_field():
    errors = storage.validate_trusted_domains({"course_id": "cs101"})

    assert any("domains" in e for e in errors)


def test_validate_trusted_domains_accepts_valid_data():
    errors = storage.validate_trusted_domains({"course_id": "cs101", "domains": ["good.com"]})

    assert errors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_domains.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.storage' has no attribute 'read_trusted_domains'`

- [ ] **Step 3: Add the exception class**

In `agent/services/storage.py`, after the `ReferencesStorageError` class added in Task 1, add:

```python
class TrustedDomainsStorageError(Exception):
    """Raised when an existing trusted_domains.json on disk is corrupt/unreadable."""
```

- [ ] **Step 4: Add `validate_trusted_domains`**

Immediately after `validate_reference` (added in Task 1), add:

```python
def validate_trusted_domains(data: dict) -> list:
    """Returns a list of error strings. An empty list means the data is valid."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("course_id", str)
    require("domains", list)

    if errors:
        return errors

    for i, d in enumerate(data["domains"]):
        if not isinstance(d, str) or not d.strip():
            errors.append(f"domains[{i}] is not a non-empty string: {d!r}")

    return errors
```

- [ ] **Step 5: Add `read_trusted_domains` and `write_trusted_domains`**

Immediately after `write_reference` (added in Task 1), add:

```python
def read_trusted_domains(course_id: str) -> list:
    """Returns the approved domains list, or [] if trusted_domains.json
    doesn't exist yet — no domains approved is the normal starting state,
    same "doesn't exist yet = normal state" convention as
    mastery_scores.json before any quiz attempt."""
    path = _course_dir(course_id) / "trusted_domains.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TrustedDomainsStorageError(f"trusted_domains.json for '{course_id}' is corrupt: {e}")
    return data.get("domains", [])


def write_trusted_domains(course_id: str, domains: list) -> Path:
    """Writes trusted_domains.json. Always overwrites — this is a
    user-controlled config list (the human approval step), not append-only
    data, so there's no destructive-conflict case to guard against the way
    write_syllabus/write_notes do."""
    out_dir = _course_dir(course_id)
    out_path = out_dir / "trusted_domains.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"course_id": course_id, "domains": domains}, indent=2), encoding="utf-8"
    )
    return out_path
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest agent/tests/test_domains.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add agent/services/storage.py agent/tests/test_domains.py
git commit -m "feat: add trusted domains storage functions"
```

---

### Task 5: `agent/services/domain_suggestions.py` — LLM domain suggestions

**Files:**
- Create: `agent/services/domain_suggestions.py`
- Create: `agent/tests/test_domain_suggestions.py`

**Interfaces:**
- Consumes: `storage.read_syllabus`, `storage.CourseNotFoundError`, `client.MODEL_DEFAULT`, `client.get_client`
- Produces: `domain_suggestions.suggest_domains(course_id: str) -> list[str]` (async) — read-only, never writes

- [ ] **Step 1: Write `agent/services/domain_suggestions.py`**

No unit test precedes this step — the function's only real logic (an LLM call) can only be meaningfully exercised live; Step 2 below adds the live-API test immediately after, matching `ask.py`'s own testing shape (no unit test file, only `test_ask.py`'s live tests).

```python
"""
Suggests candidate trusted domains for a course's restricted web search,
based on that course's own syllabus (course_name + topics). Read-only — this
never writes trusted_domains.json itself; a human reviews and approves (or
hand-edits) the list via storage.write_trusted_domains() afterward.

Uses AsyncAnthropic so the DRF async view can await it directly without
blocking the ASGI event loop; the management command wraps the same
coroutine with asyncio.run() for standalone CLI use — same pattern as
ask.py and chunk_notes.py.
"""

import json
import re

from asgiref.sync import sync_to_async

from . import storage
from .client import MODEL_DEFAULT as MODEL, get_client
from .storage import CourseNotFoundError

DOMAIN_SUGGESTION_SYSTEM_PROMPT = """You propose a short list of real, authoritative web domains \
that would be trustworthy sources for questions about ONE college course, based on its name and \
topics.

Rules:
- Only propose real domains you're confident actually exist and are authoritative for this subject \
— official documentation sites, .gov agencies, .edu institutions, and reputable .org organizations \
relevant to the course's subject matter. Prefer institutional/official domains over general \
commercial ones.
- Never propose wikipedia.org or any other openly-editable wiki — it is not treated as an \
authoritative source here, regardless of how commonly it's used for the subject.
- Tailor the list to THIS course's actual subject, not a generic default list — a Chemistry course \
and a Psychology course should get different domains.
- This is a suggestion only. A human will review and approve (or reject) each domain before it's \
ever used for search — you may be wrong about a domain, or it may not resolve. Propose your best \
real candidates; do not hedge by proposing fewer than you're confident in.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "domains": ["string", ...]
}

Notes on fields:
- "domains" is a flat list of bare domain strings (e.g. "docs.python.org", "nist.gov") — no \
wildcards, no protocol prefix, no path.
"""


async def suggest_domains(course_id: str) -> list[str]:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    user_prompt = (
        f"course_name: {syllabus.get('course_name', '')}\n"
        f"topics: {json.dumps(syllabus.get('topics', []), indent=2)}"
    )

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=DOMAIN_SUGGESTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    seen = set()
    domains = []
    for d in data.get("domains", []):
        if not isinstance(d, str):
            continue
        domain = d.strip().lower()
        if not domain or "wikipedia.org" in domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)

    return domains
```

- [ ] **Step 2: Write the live-API test**

Create `agent/tests/test_domain_suggestions.py`:

```python
"""
Live tests against the real Anthropic API for domain_suggestions.py.

Requires ANTHROPIC_API_KEY and courses/cs101 to already have syllabus.json —
skipped automatically if either precondition is missing.
"""

import os

import pytest

from agent.services import storage
from agent.services.domain_suggestions import suggest_domains

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires a live ANTHROPIC_API_KEY",
)

COURSE_ID = "cs101"


@pytest.fixture(autouse=True, scope="module")
def _require_fixture_data():
    if storage.read_syllabus(COURSE_ID) is None:
        pytest.skip(f"courses/{COURSE_ID}/syllabus.json not found — run extract_syllabus first")


async def test_suggest_domains_returns_plausible_real_domains():
    domains = await suggest_domains(COURSE_ID)

    assert domains
    assert all(isinstance(d, str) and d for d in domains)
    assert all("wikipedia.org" not in d for d in domains)


async def test_suggest_domains_never_writes_anything():
    before = storage.read_trusted_domains(COURSE_ID)

    await suggest_domains(COURSE_ID)

    after = storage.read_trusted_domains(COURSE_ID)
    assert before == after
```

- [ ] **Step 3: Run the test (only if `ANTHROPIC_API_KEY` and `courses/cs101/syllabus.json` are present; otherwise it skips cleanly)**

Run: `pytest agent/tests/test_domain_suggestions.py -v`
Expected: PASS or SKIPPED — never FAIL

- [ ] **Step 4: Commit**

```bash
git add agent/services/domain_suggestions.py agent/tests/test_domain_suggestions.py
git commit -m "feat: add domain suggestion service"
```

---

### Task 6: Domains CLI + API views

**Files:**
- Create: `agent/management/commands/domains.py`
- Modify: `agent/serializers.py`
- Modify: `agent/views.py`
- Modify: `agent/urls.py`
- Modify: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `domain_suggestions.suggest_domains`, `storage.read_trusted_domains`, `storage.write_trusted_domains`, `storage.validate_trusted_domains`
- Produces: `ApproveDomainsRequestSerializer`, `views.DomainSuggestionsView` (`POST courses/<course_id>/domains/suggest/`), `views.DomainsView` (`GET`/`PUT courses/<course_id>/domains/`)

- [ ] **Step 1: Write the failing view tests**

Append to `agent/tests/test_views.py`:

```python
from agent import views


def test_domains_get_empty_before_approval(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/domains/")

    assert response.status_code == 200
    assert response.data == {"domains": []}


def test_domains_put_replaces_approved_list(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/domains/", {"domains": ["docs.python.org"]}, format="json",
    )

    assert response.status_code == 200
    assert storage.read_trusted_domains("cs101") == ["docs.python.org"]


def test_domains_put_rejects_empty_domain_string(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/domains/", {"domains": ["good.com", ""]}, format="json",
    )

    assert response.status_code == 422


def test_domain_suggestions_view_never_writes(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101")

    async def fake_suggest_domains(course_id):
        return ["docs.python.org", "nist.gov"]

    monkeypatch.setattr(views.domain_suggestions, "suggest_domains", fake_suggest_domains)

    response = api_client.post("/api/courses/cs101/domains/suggest/")

    assert response.status_code == 200
    assert response.data == {"suggested": ["docs.python.org", "nist.gov"]}
    assert storage.read_trusted_domains("cs101") == []


def test_domain_suggestions_view_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/nocourse/domains/suggest/")

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_views.py -v -k domain`
Expected: FAIL with 404s (routes don't exist yet)

- [ ] **Step 3: Add the serializer**

In `agent/serializers.py`, after `IngestReferenceRequestSerializer` (added in Task 3), add:

```python
class ApproveDomainsRequestSerializer(serializers.Serializer):
    domains = serializers.ListField(child=serializers.CharField(allow_blank=False), allow_empty=True)
```

- [ ] **Step 4: Add `DomainSuggestionsView` and `DomainsView`**

In `agent/views.py`:

1. Update the services import to add `domain_suggestions` (kept as a module import, not a function import, so tests can `monkeypatch.setattr(views.domain_suggestions, "suggest_domains", ...)`):

```python
from .services import chunk_notes, dashboard, domain_suggestions, mastery, quiz, references, reminders, sessions, storage
```

2. Update the serializers import to add `ApproveDomainsRequestSerializer`:

```python
from .serializers import (
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    ChunkNotesRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
)
```

3. After `ReferencesView` (added in Task 3), add:

```python
class DomainSuggestionsView(APIView):
    """
    POST /api/courses/<course_id>/domains/suggest/ — read-only. Asks Claude
    to propose candidate trusted domains from this course's syllabus. Never
    writes anything; the human approves (or hand-edits) the list via
    PUT /domains/ separately.
    """

    async def post(self, request, course_id):
        try:
            domains = await domain_suggestions.suggest_domains(course_id)
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"detail": f"suggestion failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"suggested": domains}, status=status.HTTP_200_OK)


class DomainsView(APIView):
    """
    GET /api/courses/<course_id>/domains/ — the current approved list, []
    if none approved yet.

    PUT /api/courses/<course_id>/domains/ — replace the approved list with
    the user's (possibly hand-edited) selection. body: {"domains": [...]}
    """

    async def get(self, request, course_id):
        try:
            domains = await sync_to_async(storage.read_trusted_domains)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.TrustedDomainsStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"domains": domains}, status=status.HTTP_200_OK)

    async def put(self, request, course_id):
        serializer = ApproveDomainsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        domains = serializer.validated_data["domains"]
        errors = storage.validate_trusted_domains({"course_id": course_id, "domains": domains})
        if errors:
            return Response(
                {"detail": "invalid domain list", "errors": errors},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            await sync_to_async(storage.write_trusted_domains)(course_id, domains)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"course_id": course_id, "domains": domains}, status=status.HTTP_200_OK)
```

`CourseNotFoundError` is already imported in `views.py` via `from .services.ask import CourseNotFoundError, ask_async` — no new import needed for it.

- [ ] **Step 5: Wire the routes**

In `agent/urls.py`, after the `references` path (added in Task 3), add:

```python
    path("courses/<slug:course_id>/domains/suggest/", views.DomainSuggestionsView.as_view(), name="domains-suggest"),
    path("courses/<slug:course_id>/domains/", views.DomainsView.as_view(), name="domains"),
```

- [ ] **Step 6: Run `manage.py check`**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest agent/tests/test_views.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 8: Write the CLI command (no dedicated test, matching the existing no-CLI-test convention)**

Create `agent/management/commands/domains.py`:

```python
import asyncio

from django.core.management.base import BaseCommand, CommandError

from agent.services import domain_suggestions, storage
from agent.services.storage import CourseNotFoundError


class Command(BaseCommand):
    help = "Suggest or approve trusted web-search domains for a course (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--suggest", action="store_true",
            help="Ask Claude to propose candidate domains (read-only, nothing written)",
        )
        group.add_argument(
            "--approve", dest="approve", default=None,
            help="Comma-separated domains to write as this course's approved list",
        )

    def handle(self, *args, **options):
        course_id = options["course_id"]

        if options["suggest"]:
            self._suggest(course_id)
        else:
            self._approve(course_id, options["approve"])

    def _suggest(self, course_id):
        try:
            domains = asyncio.run(domain_suggestions.suggest_domains(course_id))
        except CourseNotFoundError as e:
            raise CommandError(str(e))
        except ValueError as e:
            raise CommandError(str(e))

        if not domains:
            self.stdout.write("No domains suggested.")
            return

        self.stdout.write("Suggested domains (not yet approved):")
        for d in domains:
            self.stdout.write(f"  - {d}")
        self.stdout.write(
            f"\nApprove with: python manage.py domains {course_id} --approve " + ",".join(domains)
        )

    def _approve(self, course_id, raw_domains):
        domains = [d.strip() for d in raw_domains.split(",") if d.strip()]
        errors = storage.validate_trusted_domains({"course_id": course_id, "domains": domains})

        if errors:
            self.stdout.write(self.style.ERROR("Validation failed:"))
            for e in errors:
                self.stdout.write(f"  - {e}")
            raise CommandError("invalid domain list")

        try:
            out_path = storage.write_trusted_domains(course_id, domains)
        except storage.InvalidCourseIdError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} with {len(domains)} approved domain(s)."))
```

- [ ] **Step 9: Commit**

```bash
git add agent/management/commands/domains.py agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add domains CLI command and API views"
```

---

### Task 7: `ask.py` — wire references + restricted web search into grounding

**Files:**
- Modify: `agent/services/ask.py`
- Create: `agent/tests/test_ask_grounding.py`
- Modify: `agent/tests/test_ask.py`

**Interfaces:**
- Consumes: `storage.read_references`, `storage.read_trusted_domains`
- Produces: `ask.MAX_PAUSE_TURN_CONTINUATIONS`, updated `ask.ASK_SYSTEM_PROMPT`, updated `ask.ask_async` (unchanged signature/return shape)

- [ ] **Step 1: Write the failing structural tests (no live API needed)**

These verify the tool-list-building logic — the single most safety-critical piece of this task ("zero approved domains ⇒ web_search is never even offered to the model") — deterministically, via a fake `AsyncAnthropic`-shaped client, rather than relying on live model behavior.

Create `agent/tests/test_ask_grounding.py`:

```python
"""
Structural (non-live) tests for ask.py's new grounding-source wiring: that
the web_search tool is added only when a course has approved domains, and
that it's built with the right allowed_domains. These don't call the real
API — a fake client records what ask_async would have sent it.
"""

import json

import pytest

from agent.services import ask, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason


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


def _seed_course(course_id):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    })


async def test_no_web_search_tool_when_no_domains_approved(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    canned = json.dumps({"answer": "not covered", "grounded": False, "sources": []})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question")

    assert result["grounded"] is False
    assert "tools" not in fake_client.messages.calls[0]


async def test_web_search_tool_added_with_approved_domains(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    canned = json.dumps({
        "answer": "from the web", "grounded": True, "sources": ["https://docs.python.org/3/"],
    })
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question")

    assert result["grounded"] is True
    call = fake_client.messages.calls[0]
    assert call["tools"] == [{
        "type": "web_search_20250305", "name": "web_search", "allowed_domains": ["docs.python.org"],
    }]


async def test_pause_turn_resubmits_conversation_up_to_limit(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    final = json.dumps({"answer": "done", "grounded": True, "sources": ["https://docs.python.org/3/"]})
    fake_client = _FakeClient(_FakeResponse("mid-search", stop_reason="pause_turn"))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    # First call pauses; make the second call (the resubmission) return the final answer.
    original_create = fake_client.messages.create

    call_count = 0

    async def create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return await original_create(**kwargs)
        return _FakeResponse(final)

    fake_client.messages.create = create

    result = await ask.ask_async("testcourse", "some question")

    assert result["answer"] == "done"
    assert call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_ask_grounding.py -v`
Expected: The first two tests currently pass trivially only by accident (no `tools`/`REFERENCES` context change yet) — but `test_pause_turn_resubmits_conversation_up_to_limit` FAILs because `ask_async` doesn't yet loop on `pause_turn`, and `test_web_search_tool_added_with_approved_domains` FAILs because no `tools` kwarg is ever sent

- [ ] **Step 3: Update `ASK_SYSTEM_PROMPT`**

In `agent/services/ask.py`, replace the entire `ASK_SYSTEM_PROMPT` (lines 18-57):

```python
ASK_SYSTEM_PROMPT = """You answer questions about ONE course using ONLY the material provided below, \
plus — only when that material genuinely doesn't cover the question — real, cited results from a \
restricted web search when one is available to you. There is nothing else to draw on: never answer \
from general/training knowledge as if it were this course's material.

Grounding tiers, in order:
1. Answer from SYLLABUS, NOTES, and REFERENCES first, always. These are this course's own real \
material and take priority over everything else.
2. Only if that material genuinely doesn't cover the question, and only if a web_search tool is \
available to you, you may search the web — restricted to the domains you've been given access to. \
If no web_search tool is available, you have no other source: say the material doesn't cover it.
3. Every claim sourced from the web must be cited with its real URL, and your answer must make clear \
which parts (if any) came from outside the course's own material — never blend a web result into an \
answer as if it were the course's own syllabus, notes, or reference material.

Rules:
- Answer ONLY from the provided material and, when used, real cited web search results — never use \
outside/general knowledge, even if you're confident it's correct — the user needs to know what is and \
isn't actually grounded in real material.
- If the answer isn't covered by the provided material or an available, permitted web search, say so \
explicitly (e.g. "This isn't covered in the syllabus, notes, or references I have for this course.") \
— do not guess, and do not answer as if it were the course's content.
- This applies to every turn of a multi-turn conversation, not just the first message. Earlier turns \
establishing a topic is not license to fill gaps from general knowledge later on — re-check each new \
question against the provided material (and, if used, real search results) on its own merits.
- A topic being NAMED in the material is not the same as the material ANSWERING a question about it. \
If the material only mentions a topic in passing — e.g. naming it and saying it's out of scope, or \
referencing it without explaining it — and the question asks you to explain, teach, or apply that \
topic, the material does not contain the answer. Say what the material does say about it (that's fine \
and often useful), but this is still an ungrounded answer unless a permitted web search fills the gap: \
not fabricating anything is not the same as the material actually answering what was asked.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary — \
this applies even if you use the web search tool first: your final visible response must be nothing \
but this JSON object.

Schema:
{
  "answer": "string",
  "grounded": true/false,
  "sources": ["syllabus" | "<lecture_id>" | "<reference_id>" | "<full URL>", ...]
}

Notes on fields:
- "grounded" is true when the material contains an actual answer to what was asked, OR when a \
permitted web search returned a real, cited, allowed-domain result that answers it — not merely that \
everything you said is accurate. A truthful, non-fabricated "this isn't covered" is still grounded: \
false, since the question itself remains unanswered.
- "sources" lists which part(s) of the material — and/or which cited web result(s) — the answer draws \
from: "syllabus", specific lecture_ids (from NOTES), specific reference_ids (from REFERENCES), and/or \
full URLs (from a permitted web search). Empty list when grounded is false.
"""
```

- [ ] **Step 4: Update `ask_async`**

In `agent/services/ask.py`, replace the entire `ask_async` function (lines 60-139) with:

```python
MAX_PAUSE_TURN_CONTINUATIONS = 3


async def ask_async(course_id: str, question: str, session_id: str = None) -> dict:
    client = get_client()

    syllabus = await sync_to_async(storage.read_syllabus)(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    notes = await sync_to_async(storage.read_notes)(course_id)
    references = await sync_to_async(storage.read_references)(course_id)
    approved_domains = await sync_to_async(storage.read_trusted_domains)(course_id)

    context = f"SYLLABUS:\n{json.dumps(syllabus, indent=2)}\n\n"
    if notes:
        context += f"NOTES:\n{json.dumps(notes, indent=2)}\n\n"
    else:
        context += "NOTES: none available yet for this course.\n\n"
    if references:
        context += f"REFERENCES:\n{json.dumps(references, indent=2)}"
    else:
        context += "REFERENCES: none available yet for this course."

    session = None
    if session_id is not None:
        session = await sync_to_async(sessions.get_session)(course_id, session_id)
        if session is None:
            raise sessions.SessionNotFoundError(
                f"no session '{session_id}' found for course '{course_id}'"
            )

    # Multi-turn: the context (syllabus+notes+references) only needs to be
    # stated once — the whole message list is resent to the API every call,
    # so it stays in scope for every later turn. Prior assistant turns are
    # replayed in the same JSON envelope the system prompt demands (not the
    # plain answer text) — otherwise the model's own conversation history
    # shows it answering in plain prose on earlier turns, and it drifts away
    # from the required JSON format on later ones despite the system prompt
    # repeating the instruction every call (confirmed in practice: turn 2 of
    # a session failed JSON parsing once this replayed as plain text).
    messages = []
    if session and session["messages"]:
        prior = session["messages"]
        first = prior[0]
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {first['content']}"})
        for m in prior[1:]:
            if m["role"] == "assistant":
                envelope = json.dumps({
                    "answer": m["content"],
                    "grounded": m.get("grounded", False),
                    "sources": m.get("sources", []),
                })
                messages.append({"role": "assistant", "content": envelope})
            else:
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": question})
    else:
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {question}"})

    # No domains approved for this course yet means the agent stays scoped to
    # course material only, same as it does today — the web_search tool is
    # simply never offered, rather than failing or (worse) searching
    # unrestricted.
    tools = []
    if approved_domains:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "allowed_domains": approved_domains,
        })

    create_kwargs = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": ASK_SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools

    response = await client.messages.create(**create_kwargs)

    # web_search is a server-side tool — the API runs its own internal search
    # loop and returns results in this same response, so no client-side
    # tool_use/tool_result loop is needed here. If that internal loop hits
    # its default iteration cap mid-search, the API returns stop_reason
    # "pause_turn" instead of finishing; resending the conversation (not a
    # "Continue" message — the API detects the trailing search state itself)
    # lets it pick back up. Capped so a stuck search can't loop forever.
    continuations = 0
    while response.stop_reason == "pause_turn" and continuations < MAX_PAUSE_TURN_CONTINUATIONS:
        messages = messages + [{"role": "assistant", "content": response.content}]
        create_kwargs["messages"] = messages
        response = await client.messages.create(**create_kwargs)
        continuations += 1

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    result = {
        "answer": data.get("answer", ""),
        "grounded": bool(data.get("grounded", False)),
        "sources": data.get("sources", []),
    }

    if session_id is not None:
        await sync_to_async(sessions.append_message)(course_id, session_id, "user", question)
        await sync_to_async(sessions.append_message)(
            course_id, session_id, "assistant", result["answer"],
            sources=result["sources"], grounded=result["grounded"],
        )

    return result
```

- [ ] **Step 5: Run the structural tests**

Run: `pytest agent/tests/test_ask_grounding.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the existing live-API tests (unchanged behavior check)**

Run: `pytest agent/tests/test_ask.py -v`
Expected: PASS or SKIPPED (unchanged — these three tests don't touch references/domains, so they must still pass exactly as before)

- [ ] **Step 7: Add new live-API tests for the two new grounding sources**

Append to `agent/tests/test_ask.py`:

```python
async def test_reference_grounds_when_syllabus_and_notes_dont_cover_it():
    """A question only a course's uploaded reference doc answers (not
    covered by syllabus/notes) should come back grounded, citing the
    reference_id — not 'syllabus' or a lecture_id."""
    references = storage.read_references(COURSE_ID)
    if not references:
        pytest.skip(f"courses/{COURSE_ID}/references/ is empty — upload a reference doc first")

    result = await ask_async(COURSE_ID, "What does the uploaded reference document cover?")

    assert result["grounded"] is True
    assert any(r["reference_id"] in result["sources"] for r in references)


async def test_web_search_grounds_when_domain_approved_and_course_material_silent():
    """A question genuinely outside cs101's notes/syllabus, but inside an
    approved domain's real coverage, should come back grounded with a real
    cited URL from the approved list."""
    approved = storage.read_trusted_domains(COURSE_ID)
    if not approved:
        pytest.skip(
            f"no trusted_domains.json approved for {COURSE_ID} — run "
            f"`manage.py domains {COURSE_ID} --approve ...` first"
        )

    result = await ask_async(
        COURSE_ID,
        "According to the official Python documentation, what does the walrus operator (:=) do?",
    )

    assert result["grounded"] is True
    web_sources = [s for s in result["sources"] if s.startswith("http")]
    assert web_sources
    assert any(domain in src for domain in approved for src in web_sources)
```

- [ ] **Step 8: Run the new live tests (only if fixture data is present; otherwise they skip cleanly)**

Run: `pytest agent/tests/test_ask.py -v`
Expected: PASS or SKIPPED — never FAIL

- [ ] **Step 9: Commit**

```bash
git add agent/services/ask.py agent/tests/test_ask_grounding.py agent/tests/test_ask.py
git commit -m "feat: ground ask.py in references and restricted web search"
```

---

### Task 8: `CLAUDE.md` updates

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Rewrite the first non-negotiable constraint**

In `CLAUDE.md`, under `## Non-negotiable constraints`, replace:

```
- Never fabricate course content. If the knowledge base doesn't contain something, say so — don't answer from training data or general knowledge as if it's the course's material.
```

with:

```
- Never fabricate course content. Ground every answer in real material only: this course's syllabus/notes, a user-uploaded reference document, or — only when that material genuinely doesn't cover the question, and only from a domain the user has explicitly approved for this course — real, cited web content. Never invent facts, never blend web content into an answer as if it were the course's own material, and never search the web outside an approved domain list.
```

- [ ] **Step 2: Add the new services and CLI commands to the file structure listing**

Under `## File structure`, in the `services/` block, after the `chunk_notes.py` line:

```
      chunk_notes.py         # notes (pdf/txt/md) or slides (.pptx) -> notes/<lecture_id>.json
```

add:

```
      references.py          # reference doc (pdf/txt/md) -> references/<reference_id>.json, no LLM call
```

and after the `ask.py` line:

```
      ask.py                    # grounded Q&A, stateless or multi-turn via session_id
```

add:

```
      domain_suggestions.py     # LLM-suggested trusted domains for a course's restricted web search, read-only
```

In the `management/commands/` block, after the `chunk_notes.py` line:

```
      chunk_notes.py         # CLI wrapper, handles both notes files and .pptx decks
```

add:

```
      references.py           # CLI wrapper around references.py
```

and after the `ask.py` line:

```
      ask.py                 # CLI wrapper around ask.py, optional --session
```

add:

```
      domains.py               # CLI wrapper around domain_suggestions.py (--suggest / --approve)
```

- [ ] **Step 3: Add the new per-course directory entries**

In the `courses/<course_id>/` block, after:

```
      notes/
        <lecture_id>.json # chunked notes/slides, one file per lecture — see schema below
```

add:

```
      references/
        <reference_id>.json # uploaded reference material, one file per doc — see schema below
```

and after:

```
      mastery_scores.json # derived from quiz_history.json — never hand-edited, always rebuildable
```

add:

```
      trusted_domains.json # human-approved web-search domains — absent until at least one is approved
```

- [ ] **Step 4: Add the new schema entries**

Under `## Schemas (v1)`, immediately after the `**notes/<lecture_id>.json**` schema block and its explanatory paragraphs (before `**sessions/<session_id>.json**`), add:

```

**references/<reference_id>.json**
```json
{
  "reference_id": "string",
  "title": "string",
  "source_filename": "string",
  "text": "string"
}
```

No `chunks`/`topics` — unlike notes, references aren't quizzed or mastery-tracked, so there's no need
to chunk by topic. The whole `text` gets stuffed into ask.py's context every time, same as syllabus
and notes.

**trusted_domains.json**
```json
{
  "course_id": "string",
  "domains": ["string", ...]
}
```

Absent entirely (not an empty file) until the user approves at least one domain via
`manage.py domains <course_id> --approve ...` or `PUT /api/courses/<id>/domains/` — same
"doesn't exist yet = normal state" convention as mastery_scores.json before any quiz attempt.
`domain_suggestions.suggest_domains()` proposes candidates from the course's own syllabus, but never
writes this file itself.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for references and restricted web search"
```

---

### Task 9: Frontend — clickable external source links

**Files:**
- Modify: `agent/templates/agent/course_copilot.html`

**Interfaces:**
- None — template/JS only, no new backend interface. Consumes the existing `sources: list[str]` field already returned by `/api/courses/<id>/ask/`.

- [ ] **Step 1: Update the chat message view-model JS**

In `agent/templates/agent/course_copilot.html`, replace the `chatMessages` mapping (around line 985-991):

```js
    const chatMessages = s.chatMessages.map(m => ({
      text: m.text, rowStyle: msgStyle(m.from), wrapStyle: wrapStyle(m.from), bubbleStyle: bubbleStyle(m.from),
      isAssistant: m.from === 'assistant',
      sourcesText: m.from === 'assistant'
        ? (m.grounded && m.sources && m.sources.length ? 'Sources: ' + m.sources.join(', ') : 'Not grounded in your course material')
        : ''
    }));
```

with:

```js
    const hasSources = (m) => m.from === 'assistant' && !!(m.grounded && m.sources && m.sources.length);
    const chatMessages = s.chatMessages.map(m => ({
      text: m.text, rowStyle: msgStyle(m.from), wrapStyle: wrapStyle(m.from), bubbleStyle: bubbleStyle(m.from),
      isAssistant: m.from === 'assistant',
      hasSources: hasSources(m),
      notGroundedText: !hasSources(m) && m.from === 'assistant' ? 'Not grounded in your course material' : '',
      sourceItems: hasSources(m)
        ? m.sources.map(src => ({
            text: src,
            isLink: src.indexOf('http') === 0,
            isPlain: src.indexOf('http') !== 0,
            href: src
          }))
        : []
    }));
```

- [ ] **Step 2: Update the message template to render linked vs. plain sources**

Replace the sources `<div>` (around line 464-466):

```html
                  <sc-if value="{{ m.isAssistant }}" hint-placeholder-val="{{ false }}">
                    <div style="font-size:11px;opacity:.5;margin-top:4px">{{ m.sourcesText }}</div>
                  </sc-if>
```

with:

```html
                  <sc-if value="{{ m.isAssistant }}" hint-placeholder-val="{{ false }}">
                    <div style="font-size:11px;opacity:.5;margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;align-items:center">
                      <sc-if value="{{ m.hasSources }}" hint-placeholder-val="{{ false }}">
                        <span>Sources:</span>
                        <sc-for list="{{ m.sourceItems }}" as="src" hint-placeholder-count="1">
                          <sc-if value="{{ src.isLink }}" hint-placeholder-val="{{ false }}">
                            <a href="{{ src.href }}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:underline">{{ src.text }}</a>
                          </sc-if>
                          <sc-if value="{{ src.isPlain }}" hint-placeholder-val="{{ true }}">
                            <span>{{ src.text }}</span>
                          </sc-if>
                        </sc-for>
                      </sc-if>
                      <sc-if value="{{ m.notGroundedText }}" hint-placeholder-val="{{ false }}">
                        <span>{{ m.notGroundedText }}</span>
                      </sc-if>
                    </div>
                  </sc-if>
```

- [ ] **Step 3: Manual verification**

Run: `python manage.py runserver` (or the project's usual dev-server command), open the Course Copilot UI, ask a question in a course that has at least one approved web-search domain and a question genuinely outside its syllabus/notes/references.

Expected: The assistant's "Sources:" line renders any `http`-prefixed source as an underlined, clickable link that opens in a new tab; internal sources (`"syllabus"`, lecture/reference IDs) still render as plain text next to it.

- [ ] **Step 4: Commit**

```bash
git add agent/templates/agent/course_copilot.html
git commit -m "feat: render external ask sources as clickable links"
```

---

## Self-Review Notes

- **Spec coverage:** reference doc schema/ingestion/CLI/view (Tasks 1-3); trusted domains schema/suggestion/CLI/views (Tasks 4-6); `ask_async` two-tier grounding + `grounded` redefinition + `pause_turn` handling (Task 7); CLAUDE.md updates (Task 8); frontend clickable links (Task 9); verification bullets from the design doc's "Verification" section are each covered by a specific test (storage/service unit tests in Tasks 1/2/4, view happy-path/error tests in Tasks 3/6 including the never-writes check for `DomainSuggestionsView`, live-API tests in Tasks 5/7, manual checks folded into Task 7's live tests + Task 9's manual step).
- **Explicitly out of scope items respected:** no dashboard/chat UI for domain approval was added (CLI + API only, per spec); `suggest_domains()` is not wired to fire automatically on syllabus re-extraction; no session replay changes for `web_search_tool_result` blocks were made (sessions.py continues replaying only the JSON-envelope answer text, unchanged).
- **Type consistency check:** `ingest_reference` returns the same dict shape `storage.validate_reference`/`write_reference` expect (`reference_id`/`title`/`source_filename`/`text`) across Tasks 1-3; `suggest_domains` returns `list[str]` consumed identically by the CLI (Task 6), `DomainSuggestionsView` (Task 6), and the live test (Task 5); `ask_async`'s public signature and return shape (`{"answer", "grounded", "sources"}`) are unchanged from the pre-existing contract that `views.AskView` and `sessions.append_message` already depend on.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-16-ask-grounding-expansion-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
