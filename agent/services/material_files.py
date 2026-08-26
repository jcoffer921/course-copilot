"""Private upload validation and object-storage interface for course materials."""

import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from . import storage


ALLOWED_SUFFIXES = {".pdf", ".pptx", ".docx", ".txt", ".md"}
STORAGE_KEY_RE = re.compile(r"^[a-f0-9]{32}\.(?:pdf|pptx|docx|txt|md)$")
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_OFFICE_MEMBERS = 5000
MAX_OFFICE_EXPANDED_BYTES = 50 * 1024 * 1024


class UploadValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedUpload:
    data: bytes
    display_filename: str
    suffix: str
    content_type: str

    @property
    def size_bytes(self):
        return len(self.data)


class MaterialObjectStorage(Protocol):
    def save(self, user, course_id: str, suffix: str, data: bytes) -> str: ...
    def read(self, user, course_id: str, storage_key: str) -> bytes: ...
    def delete(self, user, course_id: str, storage_key: str) -> None: ...


def sanitize_display_filename(filename: str) -> str:
    basename = Path(str(filename or "upload").replace("\\", "/")).name
    cleaned = "".join(ch for ch in basename if ch.isprintable() and ch not in "\r\n\t").strip(" .")
    return (cleaned or "upload")[:255]


def _read_bounded(upload, limit: int) -> bytes:
    chunks = upload.chunks() if hasattr(upload, "chunks") else [upload.read()]
    data = bytearray()
    for chunk in chunks:
        data.extend(chunk)
        if len(data) > limit:
            raise UploadValidationError("file_too_large", f"File exceeds the {limit // (1024 * 1024)} MB upload limit.")
    if not data:
        raise UploadValidationError("empty_file", "The uploaded file is empty.")
    return bytes(data)


def _validate_zip_document(data: bytes, suffix: str) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
    except (zipfile.BadZipFile, OSError) as exc:
        raise UploadValidationError("corrupt_file", f"The {suffix} file is corrupt or deceptively named.") from exc
    if len(members) > MAX_OFFICE_MEMBERS or sum(member.file_size for member in members) > MAX_OFFICE_EXPANDED_BYTES:
        raise UploadValidationError("unsafe_archive", "The Office document expands beyond the safe processing limit.")
    required = "word/document.xml" if suffix == ".docx" else "ppt/presentation.xml"
    if "[Content_Types].xml" not in names or required not in names:
        raise UploadValidationError("content_mismatch", f"The file contents do not match the {suffix} extension.")


def _validate_content(data: bytes, suffix: str, content_type: str) -> None:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    allowed_mimes = {
        ".pdf": {"application/pdf", "application/octet-stream", ""},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", "application/octet-stream", ""},
        ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/zip", "application/octet-stream", ""},
        ".txt": {"text/plain", "application/octet-stream", ""},
        ".md": {"text/markdown", "text/plain", "application/octet-stream", ""},
    }
    if normalized_type not in allowed_mimes[suffix]:
        raise UploadValidationError("content_mismatch", "The declared file type does not match its filename.")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadValidationError("content_mismatch", "The file contents do not match the .pdf extension.")
    elif suffix in {".docx", ".pptx"}:
        _validate_zip_document(data, suffix)
    else:
        if b"\x00" in data or data.startswith((b"%PDF-", b"PK\x03\x04")):
            raise UploadValidationError("content_mismatch", "The file contents do not match a text document.")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("invalid_encoding", "Text uploads must use UTF-8 encoding.") from exc
        if not text.strip():
            raise UploadValidationError("empty_file", "The uploaded file has no readable content.")


def prepare_upload(upload) -> PreparedUpload:
    filename = sanitize_display_filename(getattr(upload, "name", "upload"))
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadValidationError("unsupported_type", "Unsupported file type. Use PDF, PPTX, DOCX, TXT, or MD.")
    try:
        limit = int(os.environ.get("ONTRACK_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))
    except ValueError:
        limit = DEFAULT_MAX_UPLOAD_BYTES
    limit = max(1, limit)
    data = _read_bounded(upload, limit)
    content_type = str(getattr(upload, "content_type", "") or "")[:128]
    _validate_content(data, suffix, content_type)
    return PreparedUpload(data, filename, suffix, content_type)


class LocalMaterialObjectStorage:
    """Local/private-beta adapter; callers store only its randomized key."""

    def _path(self, user, course_id: str, storage_key: str) -> Path:
        if not STORAGE_KEY_RE.fullmatch(storage_key):
            raise ValueError("invalid material storage key")
        course_dir = storage._course_dir(course_id, user)
        upload_dir = (course_dir / "uploads").resolve()
        path = (upload_dir / storage_key).resolve()
        if upload_dir not in path.parents:
            raise ValueError("material storage path escaped its course directory")
        return path

    def save(self, user, course_id: str, suffix: str, data: bytes) -> str:
        storage_key = f"{uuid.uuid4().hex}{suffix}"
        path = self._path(user, course_id, storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return storage_key

    def read(self, user, course_id: str, storage_key: str) -> bytes:
        return self._path(user, course_id, storage_key).read_bytes()

    def delete(self, user, course_id: str, storage_key: str) -> None:
        path = self._path(user, course_id, storage_key)
        if path.exists():
            path.unlink()


object_storage: MaterialObjectStorage = LocalMaterialObjectStorage()
