from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from finanzplaner.categories import stable_category_id
from finanzplaner.db import SessionLocal
from finanzplaner.i18n import TRANSLATIONS, missing_translation_keys
from finanzplaner.models import Account, Category, Transaction, TransactionNote, User, WebSession
from finanzplaner.security import Actor, create_web_session, hash_password
from finanzplaner.services import FinanceService
from finanzplaner.web import login_limiter, settings

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


def test_login_failures_rate_limit_secure_cookie_and_invalid_sessions(
    app_client, admin, monkeypatch
) -> None:
    key = "testclient:philipp"
    login_limiter.clear(key)
    login_page = app_client.get("/login")
    form_token = re.search(
        r'name="form_token" value="([^"]+)', login_page.text
    ).group(1)
    for _attempt in range(settings.login_attempts):
        failed = app_client.post(
            "/login",
            data={
                "username": "philipp",
                "password": "wrong password",
                "form_token": form_token,
                "next_url": "/settings",
            },
        )
        assert failed.status_code == 401
        assert "fp_session" not in failed.cookies
    limited = app_client.post(
        "/login",
        data={
            "username": "philipp",
            "password": "correct horse battery",
            "form_token": form_token,
            "next_url": "/settings",
        },
    )
    assert limited.status_code == 429

    login_limiter.clear(key)
    monkeypatch.setattr(settings, "cookie_secure", True)
    logged_in = app_client.post(
        "/login",
        data={
            "username": "philipp",
            "password": "correct horse battery",
            "form_token": form_token,
            "next_url": "//attacker.invalid",
        },
        follow_redirects=False,
    )
    assert logged_in.status_code == 303
    assert logged_in.headers["location"] == "/"
    assert "Secure" in logged_in.headers["set-cookie"]

    with SessionLocal() as db:
        user = db.get(User, admin.id)
        expired_cookie, expired_session = create_web_session(db, settings, user)
        expired_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    app_client.cookies.set("fp_session", expired_cookie)
    expired = app_client.get("/settings", follow_redirects=False)
    assert expired.status_code == 303
    assert expired.headers["location"] == "/login?next=/settings"

    with SessionLocal() as db:
        user = db.get(User, admin.id)
        disabled_cookie, _session = create_web_session(db, settings, user)
        user.active = False
        db.commit()
    app_client.cookies.set("fp_session", disabled_cookie)
    disabled = app_client.get("/settings", follow_redirects=False)
    assert disabled.status_code == 303
    assert disabled.headers["location"] == "/login?next=/settings"


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


def test_admin_user_and_category_workflows(authenticated_client) -> None:
    users_page = authenticated_client.get("/users")
    csrf = csrf_from(users_page)
    created = authenticated_client.post(
        "/users",
        data={
            "csrf_token": csrf,
            "username": "hausmitglied",
            "password": "a household password",
            "locale": "en",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "hausmitglied"))
        assert user and user.locale == "en"
        _signed, session = create_web_session(db, settings, user)
        db.commit()
        user_id = user.id
        session_hash = session.token_hash

    disabled = authenticated_client.post(
        f"/users/{user_id}/status",
        data={"csrf_token": csrf, "active": "false"},
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    with SessionLocal() as db:
        assert db.get(WebSession, session_hash) is None
        assert not db.get(User, user_id).active

    enabled = authenticated_client.post(
        f"/users/{user_id}/status",
        data={"csrf_token": csrf, "active": "true"},
        follow_redirects=False,
    )
    assert enabled.status_code == 303
    reset = authenticated_client.post(
        f"/users/{user_id}/password",
        data={"csrf_token": csrf, "password": "a replacement password"},
        follow_redirects=False,
    )
    assert reset.status_code == 303

    categories_page = authenticated_client.get("/categories")
    category_csrf = csrf_from(categories_page)
    category_created = authenticated_client.post(
        "/categories",
        data={
            "csrf_token": category_csrf,
            "parent_id": stable_category_id("groceries"),
            "key": "haushaltstest",
            "label_de": "Haushaltstest",
            "label_en": "Household test",
            "sort_order": 77,
        },
        follow_redirects=False,
    )
    assert category_created.status_code == 303
    with SessionLocal() as db:
        category = db.scalar(
            select(Category).where(Category.key == "groceries.haushaltstest")
        )
        assert category
        category_id = category.id
    category_updated = authenticated_client.post(
        f"/categories/{category_id}",
        data={
            "csrf_token": category_csrf,
            "label_de": "Haushaltstest geändert",
            "label_en": "Household test changed",
            "sort_order": 78,
            "active": "false",
        },
        follow_redirects=False,
    )
    assert category_updated.status_code == 303
    with SessionLocal() as db:
        category = db.get(Category, category_id)
        assert category.label_de == "Haushaltstest geändert"
        assert category.sort_order == 78
        assert not category.active

    rejected_mutations = [
        (
            "/users",
            {
                "username": "blocked",
                "password": "a household password",
                "locale": "de",
            },
        ),
        (
            f"/users/{user_id}/status",
            {"active": "false"},
        ),
        (
            f"/users/{user_id}/password",
            {"password": "another replacement"},
        ),
        (
            "/categories",
            {
                "parent_id": stable_category_id("groceries"),
                "key": "blocked",
                "label_de": "Blockiert",
                "sort_order": "0",
            },
        ),
        (
            f"/categories/{category_id}",
            {
                "label_de": "Blockiert",
                "sort_order": "0",
                "active": "true",
            },
        ),
    ]
    for path, data in rejected_mutations:
        response = authenticated_client.post(path, data={"csrf_token": "wrong", **data})
        assert response.status_code == 403, path


def test_non_admin_cannot_use_administration_mutations(app_client) -> None:
    with SessionLocal() as db:
        user = User(
            username="member",
            password_hash=hash_password("a household password"),
            locale="de",
        )
        db.add(user)
        db.flush()
        signed, session = create_web_session(db, settings, user)
        db.commit()
        user_id = user.id
        csrf = session.csrf_token
    app_client.cookies.set("fp_session", signed)

    assert app_client.get("/users").status_code == 403
    assert app_client.get("/categories").status_code == 403
    attempts = [
        (
            "/users",
            {
                "username": "blocked",
                "password": "a household password",
                "locale": "de",
            },
        ),
        (f"/users/{user_id}/status", {"active": "true"}),
        (f"/users/{user_id}/password", {"password": "another replacement"}),
        (
            "/categories",
            {
                "key": "blocked",
                "label_de": "Blockiert",
                "sort_order": "0",
            },
        ),
        (
            f"/categories/{stable_category_id('groceries.general')}",
            {
                "label_de": "Blockiert",
                "sort_order": "0",
                "active": "true",
            },
        ),
    ]
    for path, data in attempts:
        response = app_client.post(path, data={"csrf_token": csrf, **data})
        assert response.status_code == 403, path


def test_private_import_and_human_note_edit_delete(
    app_client, authenticated_client, admin
) -> None:
    import_page = authenticated_client.get("/import")
    imported = authenticated_client.post(
        "/import",
        data={
            "csrf_token": csrf_from(import_page),
            "expected_account_id": "",
            "new_account_name": "Mein Privatkonto",
            "new_account_visibility": "private",
        },
        files={"file": ("dkb.csv", dkb_csv(), "text/csv")},
        follow_redirects=False,
    )
    assert imported.status_code == 303
    account_id = re.search(
        r"/accounts/([^/]+)/", imported.headers["location"]
    ).group(1)
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        assert account.visibility == "private"
        assert account.owner_id == admin.id
        transaction = db.scalar(
            select(Transaction).where(
                Transaction.account_id == account_id,
                Transaction.amount_cents < 0,
            )
        )
        transaction_id = transaction.id

    detail = authenticated_client.get(f"/transactions/{transaction_id}")
    csrf = csrf_from(detail)
    added = authenticated_client.post(
        f"/transactions/{transaction_id}/notes",
        data={"csrf_token": csrf, "content": "Originale Notiz"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    with SessionLocal() as db:
        note = db.scalar(
            select(TransactionNote).where(
                TransactionNote.transaction_id == transaction_id
            )
        )
        assert note
        note_id = note.id

    edited = authenticated_client.post(
        f"/notes/{note_id}",
        data={"csrf_token": csrf, "content": "Bearbeitete Notiz"},
        follow_redirects=False,
    )
    assert edited.status_code == 303
    with SessionLocal() as db:
        assert db.get(TransactionNote, note_id).content == "Bearbeitete Notiz"

    admin_cookie = authenticated_client.cookies.get("fp_session")
    with SessionLocal() as db:
        other_user = User(
            username="other-note-author",
            password_hash=hash_password("another secure password"),
            locale="de",
        )
        db.add(other_user)
        db.flush()
        other_cookie, other_session = create_web_session(db, settings, other_user)
        db.commit()
        other_csrf = other_session.csrf_token
    app_client.cookies.set("fp_session", other_cookie)
    denied = app_client.post(
        f"/notes/{note_id}",
        data={"csrf_token": other_csrf, "content": "Fremde Änderung"},
    )
    assert denied.status_code == 404
    app_client.cookies.set("fp_session", admin_cookie)

    rejected = authenticated_client.post(
        f"/notes/{note_id}",
        data={"csrf_token": "wrong", "delete": "true"},
    )
    assert rejected.status_code == 403
    deleted = authenticated_client.post(
        f"/notes/{note_id}",
        data={"csrf_token": csrf, "delete": "true"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    with SessionLocal() as db:
        assert db.get(TransactionNote, note_id) is None
        assert db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.account_id == account_id
            )
        ) == 2


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


def test_all_authenticated_mutations_reject_invalid_csrf(
    authenticated_client, admin, shared_account
) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    requests = [
        ("/logout", {}),
        (
            f"/transactions/{unknown}/category",
            {"revision": "1", "category_id": ""},
        ),
        (f"/transactions/{unknown}/notes", {"content": "Notiz"}),
        (f"/notes/{unknown}", {"content": "Notiz"}),
        (f"/transactions/{unknown}/tags", {"tags": "tag"}),
        (
            f"/accounts/{shared_account.id}/import",
            {"expected_account_id": shared_account.id},
        ),
        (
            "/import",
            {
                "new_account_name": "Nicht angelegt",
                "new_account_visibility": "shared",
            },
        ),
        (
            "/categories",
            {"key": "blocked", "label_de": "Blockiert", "sort_order": "0"},
        ),
        (
            f"/categories/{stable_category_id('groceries.general')}",
            {"label_de": "Blockiert", "sort_order": "0", "active": "true"},
        ),
        (f"/accounts/{shared_account.id}/recurring/detect", {}),
        (
            f"/recurring/{unknown}",
            {
                "status": "confirmed",
                "cadence": "monthly",
                "typical_amount": "10,00",
                "expected_next_date": "2026-08-01",
                "enabled": "true",
            },
        ),
        (
            f"/accounts/{shared_account.id}/review",
            {"month": "2026-01", "content": "Review", "expected_revision": "0"},
        ),
        (
            "/users",
            {
                "username": "blocked",
                "password": "a household password",
                "locale": "de",
            },
        ),
        (f"/users/{admin.id}/status", {"active": "true"}),
        (
            f"/users/{admin.id}/password",
            {"password": "another replacement"},
        ),
        (
            "/tokens",
            {
                "name": "Blocked",
                "account_ids": shared_account.id,
                "capabilities": "transactions:read",
            },
        ),
        (f"/tokens/{unknown}/revoke", {}),
        ("/settings", {"locale": "en"}),
    ]
    for path, data in requests:
        request = {"data": {"csrf_token": "wrong", **data}}
        if path == "/import" or path.endswith("/import"):
            request["files"] = {"file": ("dkb.csv", dkb_csv(), "text/csv")}
        response = authenticated_client.post(path, **request)
        assert response.status_code == 403, path


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
