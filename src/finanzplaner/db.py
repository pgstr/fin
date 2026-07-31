from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def create_sqlite_engine(settings: Settings | None = None) -> Engine:
    config = settings or get_settings()
    Path(config.database_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        config.database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

    return engine


engine = create_sqlite_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def database_is_ready(active_engine: Engine | None = None) -> bool:
    try:
        with (active_engine or engine).connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        return True
    except Exception:
        return False

