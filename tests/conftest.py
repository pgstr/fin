from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="finanzplaner-tests-"))
TEST_DB_PATH = TEST_ROOT / "test.db"
os.environ.update(
    {
        "DATABASE_PATH": str(TEST_DB_PATH),
        "BACKUP_DIR": str(TEST_ROOT / "backups"),
        "SESSION_SECRET": "test-session-secret-with-more-than-thirty-two-characters",
        "SETUP_TOKEN": "test-setup-token-with-enough-entropy",
        "ENVIRONMENT": "test",
        "TRUSTED_HOSTS": "testserver,127.0.0.1,localhost,finanzen.home.arpa",
    }
)

from fastapi.testclient import TestClient
from sqlalchemy import text

from finanzplaner.categories import seed_categories
from finanzplaner.db import Base, SessionLocal, engine
from finanzplaner.models import Account, User
from finanzplaner.security import create_web_session, hash_password
from finanzplaner.web import app, settings


def dkb_csv(
    rows: list[list[str]] | None = None,
    *,
    iban: str = "DE02120300000000202051",
    start: str = "01.01.26",
    end: str = "31.01.26",
    balance: str = "1.234,56",
    balance_date: str = "31.01.26",
    bom: bool = True,
) -> bytes:
    transaction_rows = rows or [
        [
            "03.01.26",
            "03.01.26",
            "Gebucht",
            "",
            "Supermarkt am Markt",
            "Wocheneinkauf; mit Trennzeichen",
            "Kartenzahlung",
            "DE44500105175407324931",
            "-45,67",
            "",
            "",
            "",
        ],
        [
            "04.01.26",
            "04.01.26",
            "Gebucht",
            "Arbeitgeber GmbH",
            "",
            "Gehalt",
            "Überweisung",
            "DE44500105175407324931",
            "2.000,00",
            "",
            "",
            "",
        ],
    ]
    import csv
    import io

    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", quotechar='"', lineterminator="\n")
    writer.writerow(["Kontotyp", "Girokonto"])
    writer.writerow(["IBAN", iban])
    writer.writerow(["Zeitraum", f"{start} - {end}"])
    writer.writerow([f"Kontostand vom {balance_date}", f"{balance}\u00a0€"])
    writer.writerow([])
    writer.writerow(
        [
            "Buchungsdatum",
            "Wertstellung",
            "Status",
            "Zahlungspflichtige*r",
            "Zahlungsempfänger*in",
            "Verwendungszweck",
            "Umsatztyp",
            "IBAN",
            "Betrag (€)",
            "Gläubiger-ID",
            "Mandatsreferenz",
            "Kundenreferenz",
        ]
    )
    writer.writerows(transaction_rows)
    encoded = stream.getvalue().encode("utf-8")
    return b"\xef\xbb\xbf" + encoded if bom else encoded


@pytest.fixture(scope="session")
def app_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def clean_database(app_client: TestClient) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
        connection.execute(text("PRAGMA foreign_keys=ON"))
    with SessionLocal() as db:
        seed_categories(db)
    app_client.cookies.clear()
    yield


@pytest.fixture
def admin() -> User:
    with SessionLocal() as db:
        user = User(
            username="philipp",
            password_hash=hash_password("correct horse battery"),
            is_admin=True,
            locale="de",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


@pytest.fixture
def authenticated_client(app_client: TestClient, admin: User) -> TestClient:
    with SessionLocal() as db:
        user = db.get(User, admin.id)
        signed, _session = create_web_session(db, settings, user)
        db.commit()
    app_client.cookies.set("fp_session", signed)
    return app_client


@pytest.fixture
def shared_account(admin: User) -> Account:
    with SessionLocal() as db:
        account = Account(
            display_name="Gemeinsames Girokonto",
            iban="DE02120300000000202051",
            visibility="shared",
            owner_id=None,
            created_by_id=admin.id,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account


def csrf_from(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)', response.text)
    assert match
    return match.group(1)
