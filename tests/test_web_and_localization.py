from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select

from finanzplaner.categories import stable_category_id
from finanzplaner.db import SessionLocal
from finanzplaner.i18n import TRANSLATIONS, missing_translation_keys
from finanzplaner.models import Account, Transaction, User
from finanzplaner.security import Actor, create_web_session, hash_password
from finanzplaner.services import FinanceService
from finanzplaner.web import settings

from .conftest import csrf_from, dkb_csv


def test_translation_catalogs_are_complete() -> None:
    assert missing_translation_keys() == {"de": set(), "en": set()}
    assert TRANSLATIONS["de"]["app.name"] == "Fin"
    assert TRANSLATIONS["en"]["app.name"] == "Fin"
    assert "privacy.host_notice" not in TRANSLATIONS["de"]
    assert "privacy.host_notice" not in TRANSLATIONS["en"]
    assert TRANSLATIONS["de"]["nav.overview"] == "Übersicht"
    assert TRANSLATIONS["en"]["nav.overview"] == "Overview"


def test_first_run_setup_login_and_rate_safe_errors(app_client) -> None:
    response = app_client.get("/setup")
    token = re.search(r'name="form_token" value="([^"]+)', response.text).group(1)
    response = app_client.post(
        "/setup",
        data={
            "username": "philipp",
            "password": "correct horse battery",
            "setup_token": "test-setup-token-with-enough-entropy",
            "form_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.cookies.get("fp_session")
    assert app_client.get("/setup").status_code == 404


def test_full_browser_workflow_and_english_locale(authenticated_client) -> None:
    import_page = authenticated_client.get("/import")
    csrf = csrf_from(import_page)
    imported = authenticated_client.post(
        "/import",
        data={
            "csrf_token": csrf,
            "expected_account_id": "",
            "new_account_name": "Gemeinsames Girokonto",
            "new_account_visibility": "shared",
        },
        files={"file": ("dkb.csv", dkb_csv(), "text/csv")},
        follow_redirects=False,
    )
    assert imported.status_code == 303
    location = imported.headers["location"]
    account_id = re.search(r"/accounts/([^/]+)/", location).group(1)
    result = authenticated_client.get(location)
    assert "2 Buchungen verarbeitet" in result.text
    overview = authenticated_client.get(f"/accounts/{account_id}/overview?month=2026-01")
    assert overview.status_code == 200
    assert "Gemeinsames Girokonto" in overview.text
    assert "Kontoverlauf" in overview.text
    assert "data-balance-chart" in overview.text
    assert "data-chart-point" in overview.text
    transactions = authenticated_client.get(f"/accounts/{account_id}/transactions?month=2026-01")
    assert "Supermarkt am Markt" in transactions.text
    assert 'class="category-editor"' in transactions.text
    assert "data-auto-submit" in transactions.text
    with SessionLocal() as db:
        tx = db.scalar(select(Transaction).where(Transaction.amount_cents < 0))
    detail = authenticated_client.get(f"/transactions/{tx.id}")
    csrf = csrf_from(detail)
    categorized = authenticated_client.post(
        f"/transactions/{tx.id}/category",
        data={
            "csrf_token": csrf,
            "revision": tx.revision,
            "category_id": stable_category_id("groceries.general"),
            "return_to": f"/accounts/{account_id}/transactions?month=2026-01",
        },
        follow_redirects=False,
    )
    assert categorized.status_code == 303
    assert categorized.headers["location"] == (
        f"/accounts/{account_id}/transactions?month=2026-01"
    )
    note = authenticated_client.post(
        f"/transactions/{tx.id}/notes",
        data={"csrf_token": csrf, "content": "In der Haushaltsrunde besprochen."},
        follow_redirects=False,
    )
    assert note.status_code == 303

    settings = authenticated_client.get("/settings")
    csrf = csrf_from(settings)
    switched = authenticated_client.post(
        "/settings", data={"csrf_token": csrf, "locale": "en"}, follow_redirects=False
    )
    assert switched.status_code == 303
    english = authenticated_client.get(f"/accounts/{account_id}/transactions?month=2026-01")
    assert "Transactions" in english.text
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "philipp"))
        assert user.locale == "en"
        service = FinanceService(db)
        _token, raw = service.create_agent_token(
            Actor.human(user),
            name="Review agent",
            account_ids=[account_id],
            capabilities=["reviews:write"],
            expires_at=None,
        )
        service.save_review(
            service.authenticate_agent(raw),
            account_id,
            date(2026, 1, 1),
            "## Agent review\n\nA calm synthetic month.",
            0,
        )
    review_overview = authenticated_client.get(
        f"/accounts/{account_id}/overview?month=2026-01"
    )
    assert "A calm synthetic month." in review_overview.text


def test_annual_forecast_table_separates_minimum_and_maximum(
    authenticated_client,
) -> None:
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
        for month in range(1, 7)
    ]
    import_page = authenticated_client.get("/import")
    imported = authenticated_client.post(
        "/import",
        data={
            "csrf_token": csrf_from(import_page),
            "expected_account_id": "",
            "new_account_name": "Forecast account",
            "new_account_visibility": "shared",
        },
        files={
            "file": (
                "dkb.csv",
                dkb_csv(
                    rows,
                    start="01.01.26",
                    end="30.06.26",
                    balance="500,00",
                    balance_date="30.06.26",
                ),
                "text/csv",
            )
        },
        follow_redirects=False,
    )
    account_id = re.search(
        r"/accounts/([^/]+)/", imported.headers["location"]
    ).group(1)

    forecast = authenticated_client.get(f"/accounts/{account_id}/forecast")

    assert forecast.status_code == 200
    assert "Jahresprognose" in forecast.text
    assert ">Minimum<" in forecast.text
    assert ">Maximum<" in forecast.text
    assert ">Unsicherheitsbereich<" not in forecast.text
    assert "Variabler Cashflow" not in forecast.text


def test_required_pages_and_csrf(authenticated_client, shared_account) -> None:
    paths = [
        f"/accounts/{shared_account.id}/overview",
        f"/accounts/{shared_account.id}/transactions",
        f"/accounts/{shared_account.id}/forecast",
        f"/accounts/{shared_account.id}/trends",
        f"/accounts/{shared_account.id}/import",
        f"/accounts/{shared_account.id}/recurring",
        f"/accounts/{shared_account.id}/review",
        "/categories",
        "/users",
        "/tokens",
        "/settings",
    ]
    for path in paths:
        response = authenticated_client.get(path)
        assert response.status_code == 200, path
        assert "<main" in response.text
        assert 'name="viewport"' in response.text
    rejected = authenticated_client.post(
        "/settings", data={"csrf_token": "wrong", "locale": "en"}
    )
    assert rejected.status_code == 403


def test_private_account_ids_do_not_leak_over_http(authenticated_client) -> None:
    with SessionLocal() as db:
        owner = User(
            username="private-owner",
            password_hash=hash_password("another secure password"),
            locale="de",
        )
        db.add(owner)
        db.flush()
        private_account = Account(
            display_name="Vertrauliches Konto",
            iban="DE44500105175407324931",
            visibility="private",
            owner_id=owner.id,
            created_by_id=owner.id,
        )
        db.add(private_account)
        db.commit()
        private_id = private_account.id

    # Administrators do not implicitly bypass account privacy.
    hidden = authenticated_client.get(f"/accounts/{private_id}/overview")
    unknown = authenticated_client.get(
        "/accounts/00000000-0000-0000-0000-000000000000/overview"
    )
    assert hidden.status_code == unknown.status_code == 404
    assert "Vertrauliches Konto" not in hidden.text


def test_localized_request_validation(authenticated_client) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "philipp"))
        user.locale = "en"
        signed, _session = create_web_session(db, settings, user)
        db.commit()
    authenticated_client.cookies.set("fp_session", signed)
    invalid = authenticated_client.post("/settings", data={})
    assert invalid.status_code == 422
    assert "Please check the input." in invalid.text
