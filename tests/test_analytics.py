from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from finanzplaner.analytics import (
    balance_forecast,
    balance_on,
    budget_balance_on,
    category_trend,
    complete_coverage,
    month_summary,
    year_summary,
)
from finanzplaner.categories import stable_category_id
from finanzplaner.db import SessionLocal
from finanzplaner.models import Category, ImportBatch, Transaction, TransferLink, User
from finanzplaner.security import Actor, hash_password
from finanzplaner.services import FinanceService
from finanzplaner.web import build_chart

from .conftest import dkb_csv


def add_coverage_batch(
    db, admin, shared_account, start: date, end: date, suffix: str
) -> None:
    db.add(
        ImportBatch(
            account_id=shared_account.id,
            uploader_id=admin.id,
            file_sha256=suffix.rjust(64, "0"),
            export_from=start,
            export_to=end,
            reported_balance_cents=0,
            reported_balance_date=end,
            row_count=0,
            inserted_count=0,
            duplicate_count=0,
        )
    )


def test_coverage_merges_adjacent_and_overlapping_import_periods(
    admin, shared_account
) -> None:
    with SessionLocal() as db:
        add_coverage_batch(
            db, admin, shared_account, date(2026, 1, 1), date(2026, 1, 15), "1"
        )
        add_coverage_batch(
            db, admin, shared_account, date(2026, 1, 16), date(2026, 1, 31), "2"
        )
        db.flush()

        assert complete_coverage(
            db, shared_account.id, date(2026, 1, 1), date(2026, 1, 31)
        )

        db.query(ImportBatch).delete()
        add_coverage_batch(
            db, admin, shared_account, date(2026, 1, 1), date(2026, 1, 20), "3"
        )
        add_coverage_batch(
            db, admin, shared_account, date(2026, 1, 10), date(2026, 1, 31), "4"
        )
        db.flush()

        assert complete_coverage(
            db, shared_account.id, date(2026, 1, 1), date(2026, 1, 31)
        )


def test_coverage_keeps_real_date_gap_incomplete(admin, shared_account) -> None:
    with SessionLocal() as db:
        add_coverage_batch(
            db, admin, shared_account, date(2026, 1, 1), date(2026, 1, 15), "1"
        )
        add_coverage_batch(
            db, admin, shared_account, date(2026, 1, 17), date(2026, 1, 31), "2"
        )
        db.flush()

        assert not complete_coverage(
            db, shared_account.id, date(2026, 1, 1), date(2026, 1, 31)
        )


def test_unique_transfer_matching_never_assigns_category(admin) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        actor = Actor.human(admin)
        account_a = service.create_account(
            actor,
            display_name="Gemeinsam",
            iban="DE02120300000000202051",
            visibility="shared",
        )
        account_b = service.create_account(
            actor,
            display_name="Privat",
            iban="DE12500105170648489890",
            visibility="private",
        )
        db.commit()
        outgoing = [["03.01.26", "03.01.26", "Gebucht", "", "Eigenkonto", "Transfer", "Überweisung", account_b.iban, "-100,00", "", "", ""]]
        incoming = [["04.01.26", "04.01.26", "Gebucht", "Eigenkonto", "", "Transfer", "Überweisung", account_a.iban, "100,00", "", "", ""]]
        service.import_dkb(actor, dkb_csv(outgoing, iban=account_a.iban), max_bytes=10_000_000, expected_account_id=account_a.id)
        service.import_dkb(actor, dkb_csv(incoming, iban=account_b.iban), max_bytes=10_000_000, expected_account_id=account_b.id)
        assert db.scalar(select(TransferLink)) is not None
        assert service.match_transfers() == 0
        transactions = db.scalars(select(Transaction)).all()
        assert all(tx.category_id is None for tx in transactions)
        shared_transaction = next(tx for tx in transactions if tx.account_id == account_a.id)
        presentation = service.get_transfer_presentation(actor, shared_transaction.id)
        assert presentation and not presentation["private_counterpart"]
        shared_only_user = User(
            username="shared-only",
            password_hash=hash_password("shared user password"),
            locale="de",
        )
        db.add(shared_only_user)
        db.commit()
        redacted = service.get_transfer_presentation(
            Actor.human(shared_only_user), shared_transaction.id
        )
        assert redacted == {"linked": True, "private_counterpart": True}


def test_ambiguous_transfer_remains_unlinked(admin) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        actor = Actor.human(admin)
        account_a = service.create_account(actor, display_name="A", iban="DE02120300000000202051", visibility="shared")
        account_b = service.create_account(actor, display_name="B", iban="DE12500105170648489890", visibility="private")
        db.commit()
        outgoing = [["03.01.26", "03.01.26", "Gebucht", "", "B", "Transfer", "Überweisung", account_b.iban, "-100,00", "", "", ""]]
        incoming = [
            ["03.01.26", "03.01.26", "Gebucht", "A", "", "Transfer", "Überweisung", account_a.iban, "100,00", "", "", ""],
            ["04.01.26", "04.01.26", "Gebucht", "A", "", "Transfer", "Überweisung", account_a.iban, "100,00", "", "", ""],
        ]
        service.import_dkb(actor, dkb_csv(outgoing, iban=account_a.iban), max_bytes=10_000_000, expected_account_id=account_a.id)
        service.import_dkb(actor, dkb_csv(incoming, iban=account_b.iban), max_bytes=10_000_000, expected_account_id=account_b.id)
        assert service.match_transfers() == 0


def test_internal_transfers_are_excluded_from_budget_totals(admin, shared_account) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        actor = Actor.human(admin)
        service.import_dkb(
            actor,
            dkb_csv(),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        transactions = db.scalars(select(Transaction)).all()
        incoming = next(tx for tx in transactions if tx.amount_cents > 0)
        outgoing = next(tx for tx in transactions if tx.amount_cents < 0)
        service.categorize(
            actor,
            incoming.id,
            stable_category_id("transfers.internal-transfer"),
            incoming.revision,
        )
        service.categorize(
            actor,
            outgoing.id,
            stable_category_id("groceries.general"),
            outgoing.revision,
        )
        db.commit()

        summary = service.summary(actor, shared_account.id, date(2026, 1, 1))

        assert summary["incoming_cents"] == 0
        assert summary["outgoing_cents"] == 4_567
        assert summary["net_cents"] == -4_567
        assert {item["key"] for item in summary["breakdown"]} == {"groceries"}


def test_budget_balance_excludes_non_budget_transactions_without_changing_real_balance(
    admin, shared_account
) -> None:
    rows = [
        [
            "10.01.26",
            "10.01.26",
            "Gebucht",
            "Arbeitgeber",
            "",
            "Einnahme",
            "Überweisung",
            "",
            "500,00",
            "",
            "",
            "",
        ],
        [
            "20.01.26",
            "20.01.26",
            "Gebucht",
            "",
            "Umbuchung",
            "Nicht budgetwirksam",
            "Überweisung",
            "",
            "-100,00",
            "",
            "",
            "",
        ],
    ]
    with SessionLocal() as db:
        service = FinanceService(db)
        service.import_dkb(
            Actor.human(admin),
            dkb_csv(rows, balance="1.000,00"),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        transfer = db.scalar(
            select(Transaction).where(Transaction.display_counterparty == "Umbuchung")
        )
        service.categorize(
            Actor.human(admin),
            transfer.id,
            stable_category_id("transfers.non-budget"),
            transfer.revision,
        )
        db.commit()

        actual, _snapshot_date, actual_reliable = balance_on(
            db, shared_account.id, date(2026, 1, 31)
        )
        budget, budget_reliable = budget_balance_on(
            db,
            shared_account.id,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        assert actual_reliable
        assert actual == 100_000
        assert budget_reliable
        assert budget == 110_000

        chart = build_chart(
            db,
            shared_account.id,
            {},
            date(2026, 1, 1),
            today=date(2026, 1, 31),
        )
        assert [point["value"] for point in chart["actual"]] == [100_000]
        assert [point["value"] for point in chart["budget"]] == [110_000]


def test_forecast_history_excludes_non_budget_transactions(admin, shared_account) -> None:
    rows = []
    for month in range(1, 7):
        rows.extend(
            [
                [
                    f"05.{month:02d}.26",
                    f"05.{month:02d}.26",
                    "Gebucht",
                    "Einnahme",
                    "",
                    "Budgetwirksam",
                    "Überweisung",
                    "",
                    "100,00",
                    "",
                    "",
                    "",
                ],
                [
                    f"20.{month:02d}.26",
                    f"20.{month:02d}.26",
                    "Gebucht",
                    "",
                    "Umbuchung",
                    "Nicht budgetwirksam",
                    "Überweisung",
                    "",
                    "-1.000,00",
                    "",
                    "",
                    "",
                ],
            ]
        )
    with SessionLocal() as db:
        service = FinanceService(db)
        service.import_dkb(
            Actor.human(admin),
            dkb_csv(
                rows,
                start="01.01.26",
                end="30.06.26",
                balance_date="30.06.26",
            ),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        for transaction in db.scalars(
            select(Transaction).where(Transaction.display_counterparty == "Umbuchung")
        ):
            service.categorize(
                Actor.human(admin),
                transaction.id,
                stable_category_id("transfers.non-budget"),
                transaction.revision,
            )
        db.commit()

        forecast = balance_forecast(db, shared_account.id, today=date(2026, 7, 15))

        assert forecast["available"]
        assert [point["variable_cashflow_cents"] for point in forecast["points"][1:]] == [
            10_000
        ] * 6


def test_year_summary_reconciles_months_categories_coverage_and_reviews(
    admin, shared_account
) -> None:
    actor = Actor.human(admin)
    groceries_id = stable_category_id("groceries.general")
    imports = [
        (
            "01.01.26",
            "31.01.26",
            [
                ["05.01.26", "05.01.26", "Gebucht", "Arbeitgeber", "", "Januar", "Überweisung", "", "500,00", "", "", ""],
                ["10.01.26", "10.01.26", "Gebucht", "", "Markt", "Januar", "Karte", "", "-100,00", "", "", ""],
            ],
        ),
        (
            "01.02.26",
            "28.02.26",
            [
                ["05.02.26", "05.02.26", "Gebucht", "Arbeitgeber", "", "Februar", "Überweisung", "", "600,00", "", "", ""],
                ["10.02.26", "10.02.26", "Gebucht", "", "Markt", "Februar", "Karte", "", "-200,00", "", "", ""],
                ["12.02.26", "12.02.26", "Gebucht", "", "Sonstiges", "Februar", "Karte", "", "-50,00", "", "", ""],
            ],
        ),
    ]

    with SessionLocal() as db:
        service = FinanceService(db)
        for start, end, rows in imports:
            service.import_dkb(
                actor,
                dkb_csv(
                    rows,
                    start=start,
                    end=end,
                    balance="2.000,00",
                    balance_date=end,
                ),
                max_bytes=10_000_000,
                expected_account_id=shared_account.id,
            )
        groceries = db.scalars(
            select(Transaction).where(
                Transaction.account_id == shared_account.id,
                Transaction.display_counterparty == "Markt",
            )
        ).all()
        for transaction in groceries:
            service.categorize(actor, transaction.id, groceries_id, transaction.revision)
        db.commit()
        service.save_review(
            actor,
            shared_account.id,
            date(2026, 1, 1),
            "## Januar\n\nRuhiger Monat.",
            expected_revision=0,
        )

        summary = year_summary(
            db,
            shared_account.id,
            2026,
            "de",
            today=date(2027, 1, 1),
        )

        assert len(summary["months"]) == 12
        assert summary["incoming_cents"] == sum(
            month["incoming_cents"] for month in summary["months"]
        )
        assert summary["outgoing_cents"] == sum(
            month["outgoing_cents"] for month in summary["months"]
        )
        assert summary["net_cents"] == sum(
            month["net_cents"] for month in summary["months"]
        )
        assert summary["incoming_cents"] == 110_000
        assert summary["outgoing_cents"] == 35_000
        assert summary["net_cents"] == 75_000
        assert summary["category_totals"] == [
            {
                "category_id": stable_category_id("groceries"),
                "key": "groceries",
                "label": "Lebensmittel",
                "amount_cents": 30_000,
            },
            {
                "category_id": None,
                "key": None,
                "label": None,
                "amount_cents": 5_000,
            },
        ]
        assert [month["coverage_complete"] for month in summary["months"][:2]] == [
            True,
            True,
        ]
        assert summary["incomplete_months"] == [
            date(2026, month, 1) for month in range(3, 13)
        ]
        assert not summary["coverage_complete"]
        assert summary["review_count"] == 1
        assert summary["months"][0]["review"].content == "## Januar\n\nRuhiger Monat."


def test_category_trend_preserves_calendar_spacing_and_archived_history(
    admin, shared_account
) -> None:
    actor = Actor.human(admin)
    category_id = stable_category_id("groceries.general")
    months = [(1, -10_000), (3, -20_000), (4, -30_000)]

    with SessionLocal() as db:
        service = FinanceService(db)
        for month, amount in months:
            amount_text = f"-{abs(amount) // 100},{abs(amount) % 100:02d}"
            batch = service.import_dkb(
                actor,
                dkb_csv(
                    [
                        [
                            f"15.{month:02d}.26",
                            f"15.{month:02d}.26",
                            "Gebucht",
                            "",
                            "Trend",
                            f"Monat {month}",
                            "Karte",
                            "",
                            amount_text,
                            "",
                            "",
                            "",
                        ]
                    ],
                    start=f"01.{month:02d}.26",
                    end=f"{31 if month in {1, 3} else 30}.{month:02d}.26",
                    balance_date=f"{31 if month in {1, 3} else 30}.{month:02d}.26",
                ),
                max_bytes=10_000_000,
                expected_account_id=shared_account.id,
            )
            transaction = db.scalar(
                select(Transaction).where(Transaction.import_batch_id == batch.id)
            )
            service.categorize(actor, transaction.id, category_id, transaction.revision)
            db.commit()

        category = db.get(Category, category_id)
        category.active = False
        db.commit()

        trend = service.trend(actor, shared_account.id, category_id)
        direct = category_trend(
            db, shared_account.id, category_id, "de", today=date(2026, 5, 15)
        )

        assert trend["category_id"] == category_id
        assert direct["linear_monthly_change_cents"] == -6_429
        assert all(
            item["amount_cents"] is None for item in direct["moving_average"]
        )


def test_current_month_uses_today_balance_without_future_coverage(
    admin, shared_account
) -> None:
    rows = [
        [
            "10.07.26",
            "10.07.26",
            "Gebucht",
            "",
            "Supermarkt",
            "Einkauf",
            "Karte",
            "",
            "-10,00",
            "",
            "",
            "",
        ]
    ]
    with SessionLocal() as db:
        FinanceService(db).import_dkb(
            Actor.human(admin),
            dkb_csv(
                rows,
                start="01.07.20",
                end="26.07.20",
                balance="483,53",
                balance_date="26.07.26",
            ),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )

        summary = month_summary(
            db,
            shared_account.id,
            date(2026, 7, 1),
            "de",
            today=date(2026, 7, 26),
        )
        chart = build_chart(
            db,
            shared_account.id,
            {"points": []},
            date(2026, 7, 1),
            today=date(2026, 7, 26),
        )

        assert summary["closing_balance_cents"] == 48_353
        assert summary["balance_effective_date"] == date(2026, 7, 26)
        assert summary["balance_reliable"]
        assert summary["closing_balance_reliable"]
        assert summary["coverage_complete"]
        assert chart["actual"][-1]["month"] == date(2026, 7, 1)
        assert chart["actual"][-1]["date"] == date(2026, 7, 26)
        assert chart["actual"][-1]["value"] == 48_353
        assert chart["min_cents"] == 0
        assert chart["max_cents"] == 50_000
        assert [point["month"].month for point in chart["axis_points"]] == list(
            range(1, 13)
        )
        assert chart["forecast_dots"] == []


def test_recurring_detection_and_forecast_are_deterministic(admin, shared_account) -> None:
    rows = []
    for month in range(1, 7):
        rows.extend(
            [
                [f"01.{month:02d}.26", f"01.{month:02d}.26", "Gebucht", "Arbeitgeber", "", "Gehalt", "Überweisung", "", "2.000,00", "", "", ""],
                [f"03.{month:02d}.26", f"03.{month:02d}.26", "Gebucht", "", "Vermieter", "Miete", "Lastschrift", "", "-900,00", "", "", ""],
                [f"15.{month:02d}.26", f"15.{month:02d}.26", "Gebucht", "", "Variable Kosten", "Monat", "Karte", "", f"-{100 + month},00", "", "", ""],
            ]
        )
    with SessionLocal() as db:
        service = FinanceService(db)
        actor = Actor.human(admin)
        service.import_dkb(
            actor,
            dkb_csv(rows, start="01.01.26", end="30.06.26", balance="5.000,00", balance_date="30.06.26"),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        series = service.detect_recurring(actor, shared_account.id)
        rent = next(item for item in series if "vermieter" in item.normalized_counterparty)
        service.update_recurring(actor, rent.id, status="confirmed", enabled=True)
        rerun = service.detect_recurring(actor, shared_account.id)
        preserved = next(item for item in rerun if item.id == rent.id)
        assert preserved.status == "confirmed"
        assert preserved.manually_overridden
        first = balance_forecast(db, shared_account.id, today=date(2026, 7, 15))
        second = balance_forecast(db, shared_account.id, today=date(2026, 7, 15))
        assert first == second
        assert first["available"]
        assert len(first["points"]) == 7
        assert first["recurring"]
        assert first["points"][1]["recurring_cashflow_cents"] == -90_000
        assert first["points"][1]["variable_cashflow_cents"] > 0
        assert all(point["low_cents"] <= point["balance_cents"] <= point["high_cents"] for point in first["points"])


def test_recurring_series_keep_incoming_and_outgoing_directions_separate(
    admin, shared_account
) -> None:
    rows = []
    for month in range(1, 7):
        rows.extend(
            [
                [
                    f"01.{month:02d}.26",
                    f"01.{month:02d}.26",
                    "Gebucht",
                    "Gleicher Partner",
                    "",
                    "Erstattung",
                    "Überweisung",
                    "",
                    "100,00",
                    "",
                    "",
                    "",
                ],
                [
                    f"03.{month:02d}.26",
                    f"03.{month:02d}.26",
                    "Gebucht",
                    "",
                    "Gleicher Partner",
                    "Abbuchung",
                    "Lastschrift",
                    "",
                    "-100,00",
                    "",
                    "",
                    "",
                ],
            ]
        )

    with SessionLocal() as db:
        service = FinanceService(db)
        series = service.import_dkb(
            Actor.human(admin),
            dkb_csv(
                rows,
                start="01.01.26",
                end="30.06.26",
                balance_date="30.06.26",
            ),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        assert series.inserted_count == 12
        detected = service.detect_recurring(Actor.human(admin), shared_account.id)

        partner_series = [
            item for item in detected if item.normalized_counterparty == "gleicher partner"
        ]
        assert {item.direction for item in partner_series} == {"incoming", "outgoing"}
        assert {item.typical_amount_cents for item in partner_series} == {10_000, -10_000}


def test_forecast_uses_stable_total_cashflow_and_stops_in_december(
    admin, shared_account
) -> None:
    monthly_amounts = [27_559, -41_851, -1_015, -9_488, 9_985, 8_543]
    rows = []
    for month, amount in enumerate(monthly_amounts, start=1):
        amount_text = f"{abs(amount) // 100},{abs(amount) % 100:02d}"
        if amount < 0:
            amount_text = f"-{amount_text}"
        rows.append(
            [
                f"15.{month:02d}.26",
                f"15.{month:02d}.26",
                "Gebucht",
                "Test",
                "",
                "Monatlicher Saldo",
                "Überweisung",
                "",
                amount_text,
                "",
                "",
                "",
            ]
        )

    with SessionLocal() as db:
        FinanceService(db).import_dkb(
            Actor.human(admin),
            dkb_csv(
                rows,
                start="01.01.26",
                end="30.06.26",
                balance="483,53",
                balance_date="30.06.26",
            ),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )

        forecast = balance_forecast(
            db, shared_account.id, today=date(2026, 7, 15)
        )

        assert forecast["available"]
        assert forecast["method"] == (
            "median-monthly-net-with-confirmed-recurring-separation"
        )
        assert forecast["points"][-1]["month"] == date(2026, 12, 1)
        assert [
            point["variable_cashflow_cents"] for point in forecast["points"][1:]
        ] == [3_764] * 6
        chart = build_chart(
            db,
            shared_account.id,
            forecast,
            date(2026, 7, 1),
            today=date(2026, 7, 15),
        )
        assert [point["month"].month for point in chart["actual"]] == list(
            range(1, 7)
        )
        assert [point["month"].month for point in chart["forecast_dots"]] == list(
            range(7, 13)
        )


@pytest.mark.parametrize(
    ("snapshot_month", "expected_point_count"),
    [(1, 12), (6, 7), (12, 1)],
)
def test_annual_forecast_horizon_ends_in_december(
    admin, shared_account, snapshot_month: int, expected_point_count: int
) -> None:
    last_day = 31 if snapshot_month in {1, 3, 5, 7, 8, 10, 12} else 30
    rows = [
        [
            f"15.{month:02d}.26",
            f"15.{month:02d}.26",
            "Gebucht",
            "Test",
            "",
            "Monatlicher Saldo",
            "Überweisung",
            "",
            "100,00",
            "",
            "",
            "",
        ]
        for month in range(1, snapshot_month + 1)
    ]
    next_month = (
        date(2027, 1, 15)
        if snapshot_month == 12
        else date(2026, snapshot_month + 1, 15)
    )

    with SessionLocal() as db:
        FinanceService(db).import_dkb(
            Actor.human(admin),
            dkb_csv(
                rows,
                start="01.01.26",
                end=f"{last_day:02d}.{snapshot_month:02d}.26",
                balance="500,00",
                balance_date=f"{last_day:02d}.{snapshot_month:02d}.26",
            ),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )

        forecast = balance_forecast(db, shared_account.id, today=next_month)

        assert forecast["available"]
        assert len(forecast["points"]) == expected_point_count
        assert forecast["points"][-1]["month"] == date(2026, 12, 1)
