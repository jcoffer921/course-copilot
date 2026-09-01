"""Verified backups for OnTrack's SQLite database and private course files."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BACKUP_VERSION = 1


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_name(timestamp=None) -> str:
    stamp = (timestamp or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"ontrack-backup-{stamp}.zip"


def create_backup(database_path, courses_dir, output_dir, *, keep=None, timestamp=None) -> Path:
    database_path, courses_dir, output_dir = map(Path, (database_path, courses_dir, output_dir))
    if not database_path.is_file():
        raise BackupError(f"Database does not exist: {database_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / _archive_name(timestamp)
    with tempfile.TemporaryDirectory(prefix="ontrack-backup-") as temp_name:
        staging = Path(temp_name)
        staged_db = staging / "db.sqlite3"
        source = sqlite3.connect(str(database_path))
        target = sqlite3.connect(str(staged_db))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        if courses_dir.exists():
            shutil.copytree(courses_dir, staging / "courses")
        files = {}
        for path in sorted(p for p in staging.rglob("*") if p.is_file()):
            relative = path.relative_to(staging).as_posix()
            files[relative] = {"sha256": _sha256(path), "size": path.stat().st_size}
        manifest = {
            "version": BACKUP_VERSION,
            "created_at": (timestamp or datetime.now(timezone.utc)).isoformat(),
            "files": files,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary_archive = destination.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(p for p in staging.rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(staging).as_posix())
        os.replace(temporary_archive, destination)
    if keep is not None and keep > 0:
        archives = sorted(output_dir.glob("ontrack-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in archives[keep:]:
            old.unlink()
    return destination


def verify_backup(archive_path) -> dict:
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise BackupError(f"Backup does not exist: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise BackupError("Backup contains duplicate members.")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not (
                name == "manifest.json" or name == "db.sqlite3" or name.startswith("courses/")
            ):
                raise BackupError(f"Unsafe or unexpected archive member: {name}")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BackupError("Backup manifest is missing or invalid.") from exc
        if manifest.get("version") != BACKUP_VERSION or "db.sqlite3" not in manifest.get("files", {}):
            raise BackupError("Unsupported or incomplete backup.")
        if set(manifest["files"]) != set(names) - {"manifest.json"}:
            raise BackupError("Backup contents do not match its manifest.")
        for name, metadata in manifest["files"].items():
            payload = archive.read(name)
            if len(payload) != metadata["size"] or hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
                raise BackupError(f"Checksum validation failed for {name}.")
    return manifest


def restore_backup(archive_path, database_path, courses_dir, recovery_dir, *, confirmation):
    if confirmation != "RESTORE ONTRACK":
        raise BackupError('Pass confirmation="RESTORE ONTRACK" to restore.')
    manifest = verify_backup(archive_path)
    database_path, courses_dir, recovery_dir = map(Path, (database_path, courses_dir, recovery_dir))
    recovery_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery = recovery_dir / f"pre-restore-{stamp}"
    recovery.mkdir()
    with tempfile.TemporaryDirectory(prefix="ontrack-restore-", dir=str(database_path.parent)) as temp_name:
        staging = Path(temp_name)
        with zipfile.ZipFile(archive_path) as archive:
            for name in manifest["files"]:
                target = staging / PurePosixPath(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
        if database_path.exists():
            shutil.move(str(database_path), recovery / "db.sqlite3")
        if courses_dir.exists():
            shutil.move(str(courses_dir), recovery / "courses")
        shutil.move(str(staging / "db.sqlite3"), database_path)
        restored_courses = staging / "courses"
        if restored_courses.exists():
            shutil.move(str(restored_courses), courses_dir)
        else:
            courses_dir.mkdir(parents=True, exist_ok=True)
    return {"manifest": manifest, "recovery_path": str(recovery)}
