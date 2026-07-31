from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from finanzplaner.backup import create_backup, list_backups, verify_backup
from finanzplaner.config import Settings


def test_online_backup_verifies_and_restores_equivalent_database(tmp_path) -> None:
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO example(value) VALUES ('kept')")
    settings = Settings(
        ENVIRONMENT="test",
        DATABASE_PATH=source,
        BACKUP_DIR=tmp_path / "backups",
        SESSION_SECRET="test-session-secret-with-more-than-thirty-two-characters",
        SETUP_TOKEN="test-setup-token-with-enough-entropy",
    )
    backup = create_backup(settings, now=datetime(2026, 7, 25, 3, 15, tzinfo=UTC))
    assert verify_backup(backup)
    with closing(sqlite3.connect(backup)) as restored:
        assert restored.execute("SELECT value FROM example").fetchone()[0] == "kept"
    infos = list_backups(settings)
    assert len(infos) == 2
    assert all(info.valid for info in infos)
