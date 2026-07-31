from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from finanzplaner.categories import stable_category_id
from finanzplaner.db import SessionLocal
from finanzplaner.errors import NotFoundError, PermissionDeniedError
from finanzplaner.models import (
    Account,
    AuditEvent,
    Category,
    CategoryAssignmentEvent,
    Transaction,
    User,
)
from finanzplaner.security import Actor, hash_password
from finanzplaner.services import FinanceService

from .conftest import dkb_csv


def make_user(db, username: str) -> User:
    user = User(username=username, password_hash=hash_password("a secure password"), locale="de")
    db.add(user)
    db.flush()
    return user


def test_shared_and_private_horizontal_authorization(admin, shared_account) -> None:
    with SessionLocal() as db:
        user_a = make_user(db, "alice")
        user_b = make_user(db, "bernd")
        private_a = Account(
            display_name="Alice privat",
            iban="DE12500105170648489890",
            visibility="private",
            owner_id=user_a.id,
            created_by_id=user_a.id,
        )
        private_b = Account(
            display_name="Bernd privat",
            iban="DE44500105175407324931",
            visibility="private",
            owner_id=user_b.id,
            created_by_id=user_b.id,
        )
        db.add_all([private_a, private_b])
        db.commit()
        service = FinanceService(db)
        visible_a = {account.id for account in service.list_accounts(Actor.human(user_a))}
        visible_b = {account.id for account in service.list_accounts(Actor.human(user_b))}
        assert visible_a == {shared_account.id, private_a.id}
        assert visible_b == {shared_account.id, private_b.id}
        with pytest.raises(NotFoundError):
            service.get_account(Actor.human(user_a), private_b.id)
        with pytest.raises(NotFoundError):
            service.summary(Actor.human(user_a), private_b.id, date(2026, 1, 1))


def test_human_category_is_authoritative_and_agent_batch_idempotent(admin, shared_account) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        service.import_dkb(
            Actor.human(admin),
            dkb_csv(),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        tx = db.scalar(select(Transaction).order_by(Transaction.amount_cents))
        human = Actor.human(admin)
        groceries = stable_category_id("groceries.general")
        result = service.categorize(human, tx.id, groceries, tx.revision)
        db.commit()
        assert result["status"] == "applied"
        token, raw = service.create_agent_token(
            human,
            name="Test agent",
            account_ids=[shared_account.id],
            capabilities=["transactions:read", "transactions:categorize", "notes:write", "tags:write"],
            expires_at=None,
        )
        agent = service.authenticate_agent(raw)
        assert agent
        conflict = service.categorize_batch(
            agent,
            [{"transaction_id": tx.id, "category_id": stable_category_id("dining.restaurant-cafe"), "expected_revision": 2}],
            idempotency_key="same-request",
        )
        assert conflict["results"][0]["code"] == "human_authoritative"
        event_count = db.scalar(select(func.count(AuditEvent.id)))
        repeated = service.categorize_batch(
            agent,
            [{"transaction_id": tx.id, "category_id": stable_category_id("dining.restaurant-cafe"), "expected_revision": 2}],
            idempotency_key="same-request",
        )
        assert repeated == conflict
        assert db.scalar(select(func.count(AuditEvent.id))) == event_count

        service.categorize(human, tx.id, None, 2)
        db.commit()
        applied = service.categorize_batch(
            agent,
            [{"transaction_id": tx.id, "category_id": groceries, "expected_revision": 3}],
            idempotency_key="after-human-clear",
        )
        assert applied["results"][0]["status"] == "applied"


def test_agent_scope_and_annotations_preserve_authorship(admin, shared_account) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        service.import_dkb(
            Actor.human(admin), dkb_csv(), max_bytes=10_000_000, expected_account_id=shared_account.id
        )
        tx = db.scalar(select(Transaction))
        human_note = service.add_note(Actor.human(admin), tx.id, "Menschliche Notiz")
        service.add_tags(Actor.human(admin), tx.id, ["Prüfen"])
        _token, raw = service.create_agent_token(
            Actor.human(admin),
            name="Annotator",
            account_ids=[shared_account.id],
            capabilities=["transactions:read", "notes:write", "tags:write"],
            expires_at=None,
        )
        agent = service.authenticate_agent(raw)
        service.add_note(agent, tx.id, "Agenten-Notiz")
        service.add_tags(agent, tx.id, ["Prüfen", "regelmäßig"])
        refreshed = service.get_transaction(Actor.human(admin), tx.id)
        assert {note.content for note in refreshed.notes} == {"Menschliche Notiz", "Agenten-Notiz"}
        assert human_note.content == "Menschliche Notiz"
        assert {link.author_type for link in refreshed.tag_links if link.tag.normalized_name == "prüfen"} == {
            "human",
            "agent",
        }
        with pytest.raises(PermissionDeniedError):
            service.categorize(agent, tx.id, stable_category_id("groceries.general"), tx.revision)


def test_archived_root_hides_its_active_leaves(admin) -> None:
    with SessionLocal() as db:
        root = db.get(Category, stable_category_id("dining"))
        leaf_id = stable_category_id("dining.restaurant-cafe")
        root.active = False
        db.commit()
        visible_ids = {
            category.id for category in FinanceService(db).list_categories(Actor.human(admin))
        }
        assert root.id not in visible_ids
        assert leaf_id not in visible_ids
        archived_ids = {
            category.id
            for category in FinanceService(db).list_categories(
                Actor.human(admin), include_archived=True
            )
        }
        assert {root.id, leaf_id} <= archived_ids


def test_seed_categories_migrates_legacy_assignments_and_archives_old_builtin(
    admin, shared_account
) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        service.import_dkb(
            Actor.human(admin),
            dkb_csv(),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        legacy = Category(
            id=stable_category_id("groceries.bakery"),
            key="groceries.bakery",
            parent_id=stable_category_id("groceries"),
            label_de="Bäckerei",
            label_en="Bakery",
            builtin=True,
            assignable=True,
        )
        db.add(legacy)
        db.flush()
        tx = db.scalar(select(Transaction).where(Transaction.amount_cents < 0))
        tx.category_id = legacy.id
        tx.category_actor_type = "human"
        tx.category_actor_id = admin.id
        db.commit()

        from finanzplaner.categories import seed_categories

        seed_categories(db)
        db.refresh(tx)
        db.refresh(legacy)

        assert tx.category_id == stable_category_id("groceries.general")
        assert tx.category_actor_type == "system"
        assert tx.revision == 2
        assert not legacy.active
        event = db.scalar(
            select(CategoryAssignmentEvent).where(
                CategoryAssignmentEvent.transaction_id == tx.id
            )
        )
        assert event
        assert event.previous_category_id == legacy.id
        assert event.category_id == stable_category_id("groceries.general")
