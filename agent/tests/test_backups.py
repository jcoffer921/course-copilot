import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.services import backups


def _database(path, value="original"):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE sample (value TEXT)")
    connection.execute("INSERT INTO sample VALUES (?)", [value])
    connection.commit()
    connection.close()


def _value(path):
    connection = sqlite3.connect(path)
    value = connection.execute("SELECT value FROM sample").fetchone()[0]
    connection.close()
    return value


def test_backup_captures_database_and_courses_and_verifies(tmp_path):
    database = tmp_path / "db.sqlite3"
    courses = tmp_path / "courses"
    courses.mkdir()
    (courses / "notes.txt").write_text("private notes", encoding="utf-8")
    _database(database)

    archive = backups.create_backup(
        database, courses, tmp_path / "backups",
        timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    manifest = backups.verify_backup(archive)

    assert archive.name == "ontrack-backup-20260831T000000Z.zip"
    assert set(manifest["files"]) == {"db.sqlite3", "courses/notes.txt"}


def test_backup_detects_tampering(tmp_path):
    database = tmp_path / "db.sqlite3"
    _database(database)
    archive = backups.create_backup(database, tmp_path / "courses", tmp_path / "backups")
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("db.sqlite3", b"tampered")

    with pytest.raises(backups.BackupError):
        backups.verify_backup(archive)


def test_restore_requires_confirmation_and_retains_recovery_copy(tmp_path):
    database = tmp_path / "db.sqlite3"
    courses = tmp_path / "courses"
    courses.mkdir()
    (courses / "notes.txt").write_text("old", encoding="utf-8")
    _database(database, "backup")
    archive = backups.create_backup(database, courses, tmp_path / "backups")
    database.unlink()
    _database(database, "current")
    (courses / "notes.txt").write_text("current", encoding="utf-8")

    with pytest.raises(backups.BackupError):
        backups.restore_backup(archive, database, courses, tmp_path / "recovery", confirmation="no")
    result = backups.restore_backup(
        archive, database, courses, tmp_path / "recovery", confirmation="RESTORE ONTRACK",
    )

    assert _value(database) == "backup"
    assert (courses / "notes.txt").read_text(encoding="utf-8") == "old"
    recovery = Path(result["recovery_path"])
    assert _value(recovery / "db.sqlite3") == "current"
    assert (recovery / "courses" / "notes.txt").read_text(encoding="utf-8") == "current"
