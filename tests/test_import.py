from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from finanzplaner.csv_import import parse_dkb_csv
from finanzplaner.db import SessionLocal
from finanzplaner.errors import ValidationError
from finanzplaner.models import ImportBatch, Transaction
from finanzplaner.security import Actor
from finanzplaner.services import FinanceService

from .conftest import dkb_csv


def test_parser_handles_dkb_edge_cases() -> None:
    long_purpose = "Sehr lang " + "x" * 12_000
    rows = [
        ["01.01.26", "01.01.2026", "Gebucht", "", "Nullinfo", long_purpose, "Info", "", "0,00", "", "", ""],
        ["02.01.26", "02.01.26", "Gebucht", "Quelle", "", "", "Überweisung", "", "12,34", "", "", ""],
    ]
    parsed = parse_dkb_csv(dkb_csv(rows, balance="572,26"))
    assert parsed.reported_balance_cents == 57_226
    assert parsed.transactions[0].amount_cents == 0
    assert parsed.transactions[0].direction == "incoming"
    assert parsed.transactions[0].fields["Verwendungszweck"] == long_purpose
    assert parsed.transactions[1].fields["Zahlungsempfänger*in"] == ""


def test_parser_aligns_stale_period_year_with_balance_and_transactions() -> None:
    parsed = parse_dkb_csv(
        dkb_csv(
            start="01.01.20",
            end="26.07.20",
            balance_date="26.07.26",
        )
    )

    assert parsed.export_from.isoformat() == "2026-01-01"
    assert parsed.export_to.isoformat() == "2026-07-26"


def test_parser_preserves_four_digit_years_in_multi_year_period() -> None:
    rows = [
        ["02.01.2025", "02.01.2025", "Gebucht", "Quelle", "", "", "Überweisung", "", "12,34", "", "", ""],
        ["31.07.2026", "31.07.2026", "Gebucht", "", "Ziel", "", "Überweisung", "", "-12,34", "", "", ""],
    ]

    parsed = parse_dkb_csv(
        dkb_csv(
            rows,
            start="01.01.2025",
            end="31.07.2026",
            balance_date="31.07.2026",
        )
    )

    assert parsed.export_from.isoformat() == "2025-01-01"
    assert parsed.export_to.isoformat() == "2026-07-31"


def test_committed_browser_demo_fixture_is_valid_and_synthetic() -> None:
    payload = Path("tests/fixtures/dkb-browser-demo.csv").read_bytes()
    parsed = parse_dkb_csv(payload)
    assert parsed.account_iban == "DE02120300000000202051"
    assert parsed.export_from.isoformat() == "2026-01-01"
    assert parsed.export_to.isoformat() == "2026-06-30"
    assert len(parsed.transactions) == 24


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"not;the;layout\n", "import_layout"),
        (
            dkb_csv([["01.01.26", "01.01.26", "Vorgemerkt", "", "X", "", "Info", "", "1,00", "", "", ""]]),
            "unsupported_status",
        ),
        (
            dkb_csv([["01.01.26", "01.01.26", "Gebucht", "", "X"]]),
            "import_row",
        ),
    ],
)
def test_parser_rejects_unknown_or_malformed_input(payload: bytes, code: str) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_dkb_csv(payload)
    assert caught.value.code == code


def test_occurrence_aware_import_and_overlap(admin, shared_account) -> None:
    repeated = [
        ["03.01.26", "03.01.26", "Gebucht", "", "Bäckerei", "Brötchen", "Karte", "", "-5,00", "", "", ""],
        ["03.01.26", "03.01.26", "Gebucht", "", "Bäckerei", "Brötchen", "Karte", "", "-5,00", "", "", ""],
    ]
    actor = Actor.human(admin)
    with SessionLocal() as db:
        service = FinanceService(db)
        first = service.import_dkb(actor, dkb_csv(repeated), max_bytes=10_000_000, expected_account_id=shared_account.id)
        assert first.inserted_count == 2
        assert first.duplicate_count == 0
        assert db.scalar(select(func.count(Transaction.id))) == 2
        assert all(tx.category_id is None for tx in db.scalars(select(Transaction)).all())
        second = service.import_dkb(actor, dkb_csv(repeated), max_bytes=10_000_000, expected_account_id=shared_account.id)
        assert second.inserted_count == 0
        assert second.duplicate_count == 2
        assert db.scalar(select(func.count(Transaction.id))) == 2

        overlap = repeated + [
            ["04.01.26", "04.01.26", "Gebucht", "", "Café", "Kaffee", "Karte", "", "-3,50", "", "", ""],
        ]
        third = service.import_dkb(actor, dkb_csv(overlap), max_bytes=10_000_000, expected_account_id=shared_account.id)
        assert third.inserted_count == 1
        assert db.scalar(select(func.count(Transaction.id))) == 3


def test_account_mismatch_is_atomic(admin, shared_account) -> None:
    actor = Actor.human(admin)
    with SessionLocal() as db:
        with pytest.raises(ValidationError) as caught:
            FinanceService(db).import_dkb(
                actor,
                dkb_csv(iban="DE12500105170648489890"),
                max_bytes=10_000_000,
                expected_account_id=shared_account.id,
            )
        assert caught.value.code == "account_mismatch"
        assert db.scalar(select(func.count(ImportBatch.id))) == 0
        assert db.scalar(select(func.count(Transaction.id))) == 0


def test_raw_file_is_not_persisted(admin, shared_account, tmp_path: Path) -> None:
    payload = dkb_csv()
    with SessionLocal() as db:
        FinanceService(db).import_dkb(
            Actor.human(admin),
            payload,
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        tx = db.scalar(select(Transaction))
        assert tx.raw_fields["Verwendungszweck"] == "Wocheneinkauf; mit Trennzeichen"
    assert not any(path.read_bytes() == payload for path in tmp_path.rglob("*") if path.is_file())


def test_private_sample_aggregate_validation_without_payload_output() -> None:
    path = Path("/Users/streller/Downloads/sample-transactions-35.csv")
    if not path.exists():
        pytest.skip("private sample is not present")
    parsed = parse_dkb_csv(path.read_bytes())
    assert len(parsed.transactions) == 342
    assert parsed.reported_balance_cents == 57_226
    assert sum(tx.direction == "outgoing" for tx in parsed.transactions) == 325
    assert sum(tx.direction == "incoming" for tx in parsed.transactions) == 17
    assert sum(tx.amount_cents == 0 for tx in parsed.transactions) == 1
