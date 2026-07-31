from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings, get_settings


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    valid: bool
    size: int


def verify_backup(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        uri = f"file:{path.resolve()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            return bool(result and result[0] == "ok")
    except sqlite3.Error:
        return False


def _atomic_copy(source: Path, destination: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _prune(directory: Path, pattern: str, keep: int) -> None:
    files = sorted(directory.glob(pattern), reverse=True)
    for stale in files[keep:]:
        stale.unlink()


def create_backup(
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> Path:
    config = settings or get_settings()
    backup_dir = config.backup_dir.resolve()
    daily_dir = backup_dir / "daily"
    monthly_dir = backup_dir / "monthly"
    daily_dir.mkdir(parents=True, exist_ok=True)
    monthly_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).astimezone()
    daily = daily_dir / f"finanzplaner-{timestamp:%Y-%m-%dT%H%M%S%z}.sqlite3"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".finanzplaner-", suffix=".tmp", dir=daily_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with (
            closing(sqlite3.connect(config.database_path)) as source,
            closing(sqlite3.connect(temporary)) as target,
        ):
            source.backup(target)
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            target.commit()
        if not verify_backup(temporary):
            raise RuntimeError("backup integrity_check failed")
        os.replace(temporary, daily)
    finally:
        temporary.unlink(missing_ok=True)
    monthly = monthly_dir / f"finanzplaner-{timestamp:%Y-%m}.sqlite3"
    if not monthly.exists():
        _atomic_copy(daily, monthly)
        if not verify_backup(monthly):
            monthly.unlink(missing_ok=True)
            raise RuntimeError("monthly backup integrity_check failed")
    _prune(daily_dir, "finanzplaner-*.sqlite3", 14)
    _prune(monthly_dir, "finanzplaner-*.sqlite3", 12)
    return daily


def list_backups(settings: Settings | None = None) -> list[BackupInfo]:
    config = settings or get_settings()
    paths = sorted(config.backup_dir.glob("**/finanzplaner-*.sqlite3"), reverse=True)
    return [BackupInfo(path=path, valid=verify_backup(path), size=path.stat().st_size) for path in paths]
