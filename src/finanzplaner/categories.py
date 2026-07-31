from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, Category, CategoryAssignmentEvent, Transaction

NAMESPACE = uuid.UUID("8faea644-af83-4a08-9d91-b16f85003750")


def stable_category_id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


TAXONOMY: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "housing",
        "Wohnen",
        "Housing",
        [
            ("rent-mortgage", "Miete & Kredit", "Rent & mortgage"),
            ("utilities", "Nebenkosten", "Utilities"),
            ("internet-landline", "Internet & Festnetz", "Internet & landline"),
            ("household-repairs", "Haushalt & Reparaturen", "Household & repairs"),
        ],
    ),
    (
        "vehicle",
        "Auto",
        "Car",
        [
            ("loan", "Autokredit", "Car loan"),
            ("fuel-charging", "Tanken & Laden", "Fuel & charging"),
            ("parking-maintenance", "Parken & Wartung", "Parking & maintenance"),
        ],
    ),
    (
        "public-transport",
        "ÖPNV",
        "Public transport",
        [
            ("general", "ÖPNV", "Public transport"),
        ],
    ),
    (
        "groceries",
        "Lebensmittel",
        "Groceries",
        [
            ("general", "Lebensmittel", "Groceries"),
        ],
    ),
    (
        "mobile-phone",
        "Mobilfunk",
        "Mobile phone",
        [
            ("general", "Mobilfunk", "Mobile phone"),
        ],
    ),
    (
        "drugstore",
        "Drogerie",
        "Drugstore",
        [
            ("general", "Drogerie", "Drugstore"),
        ],
    ),
    (
        "dining",
        "Gastronomie",
        "Dining",
        [
            ("restaurant-cafe", "Restaurant & Café", "Restaurant & café"),
            ("takeaway-delivery", "Imbiss & Lieferung", "Takeaway & delivery"),
        ],
    ),
    (
        "insurance",
        "Versicherungen",
        "Insurance",
        [
            ("vehicle", "Kfz-Versicherung", "Car insurance"),
            ("health", "Krankenversicherung", "Health insurance"),
            ("other", "Sonstige Versicherung", "Other insurance"),
        ],
    ),
    (
        "health",
        "Gesundheit",
        "Health",
        [
            ("treatment", "Arzt & Behandlung", "Doctor & treatment"),
            ("pharmacy", "Apotheke", "Pharmacy"),
        ],
    ),
    (
        "digital",
        "Abos & Digitales",
        "Subscriptions & digital",
        [
            ("streaming", "Streaming", "Streaming"),
            ("software-cloud", "Software & Cloud", "Software & cloud"),
            ("memberships", "Mitgliedschaften", "Memberships"),
        ],
    ),
    (
        "leisure",
        "Freizeit",
        "Leisure",
        [
            ("hobbies-sports", "Sport & Hobbys", "Sports & hobbies"),
            ("activities-events", "Ausflüge & Events", "Activities & events"),
        ],
    ),
    (
        "shopping",
        "Shopping",
        "Shopping",
        [
            ("clothing", "Kleidung & Schuhe", "Clothing & shoes"),
            ("electronics", "Elektronik", "Electronics"),
            ("general", "Allgemeines Shopping", "General shopping"),
        ],
    ),
    (
        "pets",
        "Haustier",
        "Pets",
        [
            ("general", "Haustier", "Pets"),
        ],
    ),
    (
        "vacation",
        "Urlaub",
        "Vacation",
        [
            ("general", "Urlaub", "Vacation"),
        ],
    ),
    (
        "education",
        "Bildung",
        "Education",
        [
            ("general", "Bildung", "Education"),
        ],
    ),
    (
        "fees",
        "Steuern & Gebühren",
        "Taxes & fees",
        [
            ("taxes-government", "Steuern & Behörden", "Taxes & government"),
            ("bank-fees", "Bankgebühren", "Bank fees"),
        ],
    ),
    (
        "cash",
        "Bargeld",
        "Cash",
        [
            ("cash-withdrawal", "Bargeld", "Cash"),
        ],
    ),
    (
        "income",
        "Einnahmen",
        "Income",
        [
            ("household-contribution", "Gehalt & Haushaltsbeitrag", "Salary & household contribution"),
            ("refund", "Erstattungen", "Refunds"),
            ("other-income", "Sonstige Einnahmen", "Other income"),
        ],
    ),
    (
        "transfers",
        "Umbuchungen",
        "Transfers",
        [
            ("internal-transfer", "Interne Umbuchung", "Internal transfer"),
            ("non-budget", "Nicht budgetwirksam", "Non-budget transaction"),
        ],
    ),
]

LEGACY_CATEGORY_MAP = {
    "income.salary-wages": "income.household-contribution",
    "income.interest-investment-income": "income.other-income",
    "income.sale": "income.other-income",
    "housing.energy": "housing.utilities",
    "housing.water-sewage": "housing.utilities",
    "housing.broadcasting-fee": "fees.taxes-government",
    "housing.household-goods": "housing.household-repairs",
    "housing.furniture": "housing.household-repairs",
    "housing.repairs-maintenance": "housing.household-repairs",
    "groceries.groceries": "groceries.general",
    "groceries.bakery": "groceries.general",
    "groceries.drugstore": "drugstore.general",
    "dining.restaurant": "dining.restaurant-cafe",
    "dining.cafe": "dining.restaurant-cafe",
    "dining.delivery-takeaway": "dining.takeaway-delivery",
    "mobility.fuel": "vehicle.fuel-charging",
    "mobility.ev-charging": "vehicle.fuel-charging",
    "mobility.public-transport": "public-transport.general",
    "mobility.vehicle-costs": "vehicle.parking-maintenance",
    "mobility.parking-tolls": "vehicle.parking-maintenance",
    "mobility.taxi-rental-car": "public-transport.general",
    "insurance.liability": "insurance.other",
    "insurance.home-contents": "insurance.other",
    "insurance.vehicle-insurance": "insurance.vehicle",
    "insurance.health-insurance": "insurance.health",
    "insurance.life-insurance": "insurance.other",
    "insurance.other-insurance": "insurance.other",
    "health.doctor-treatment": "health.treatment",
    "health.therapy": "health.treatment",
    "health.medical-aids": "health.treatment",
    "communication.mobile-phone": "mobile-phone.general",
    "communication.software-cloud": "digital.software-cloud",
    "communication.streaming-media": "digital.streaming",
    "communication.memberships": "digital.memberships",
    "leisure.hobbies": "leisure.hobbies-sports",
    "leisure.sports": "leisure.hobbies-sports",
    "leisure.events": "leisure.activities-events",
    "leisure.books-media": "leisure.hobbies-sports",
    "shopping.clothing-shoes": "shopping.clothing",
    "shopping.general-shopping": "shopping.general",
    "family.childcare": "education.general",
    "family.school-education": "education.general",
    "family.children-needs": "shopping.general",
    "travel.accommodation": "vacation.general",
    "travel.travel-transport": "vacation.general",
    "travel.activities": "vacation.general",
    "finance.bank-fees": "fees.bank-fees",
    "finance.taxes-levies": "fees.taxes-government",
    "finance.loan-interest": "fees.bank-fees",
    "finance.administration-government": "fees.taxes-government",
    "gifts.gifts": "shopping.general",
    "cash.cash-deposit": "cash.cash-withdrawal",
    "other.account-information": "transfers.non-budget",
}

SYSTEM_ACTOR_ID = stable_category_id("system.taxonomy-migration")


def seed_categories(db: Session) -> None:
    existing = {category.key: category for category in db.scalars(select(Category)).all()}
    desired_keys: set[str] = set()
    for root_order, (root_key, de, en, leaves) in enumerate(TAXONOMY):
        desired_keys.add(root_key)
        root = existing.get(root_key)
        if root is None:
            root = Category(
                id=stable_category_id(root_key),
                key=root_key,
                label_de=de,
                label_en=en,
                builtin=True,
                assignable=False,
                sort_order=root_order,
            )
            db.add(root)
            db.flush()
            existing[root_key] = root
        root.parent_id = None
        root.label_de = de
        root.label_en = en
        root.builtin = True
        root.assignable = False
        root.sort_order = root_order
        root.active = True
        for leaf_order, (leaf_slug, leaf_de, leaf_en) in enumerate(leaves):
            key = f"{root_key}.{leaf_slug}"
            desired_keys.add(key)
            category = existing.get(key)
            if category is None:
                category = Category(
                    id=stable_category_id(key),
                    key=key,
                    parent_id=root.id,
                    label_de=leaf_de,
                    label_en=leaf_en,
                    builtin=True,
                    assignable=True,
                    sort_order=leaf_order,
                )
                db.add(category)
                existing[key] = category
            category.parent_id = root.id
            category.label_de = leaf_de
            category.label_en = leaf_en
            category.builtin = True
            category.assignable = True
            category.sort_order = leaf_order
            category.active = True

    migrated = 0
    for legacy_key, current_key in LEGACY_CATEGORY_MAP.items():
        legacy = existing.get(legacy_key)
        current = existing.get(current_key)
        if legacy is None or current is None or legacy.id == current.id:
            continue
        transactions = db.scalars(select(Transaction).where(Transaction.category_id == legacy.id)).all()
        for transaction in transactions:
            previous_category_id = transaction.category_id
            transaction.category_id = current.id
            transaction.category_actor_type = "system"
            transaction.category_actor_id = SYSTEM_ACTOR_ID
            transaction.revision += 1
            db.add(
                CategoryAssignmentEvent(
                    transaction_id=transaction.id,
                    previous_category_id=previous_category_id,
                    category_id=current.id,
                    actor_type="system",
                    actor_id=SYSTEM_ACTOR_ID,
                    revision=transaction.revision,
                )
            )
            migrated += 1

    for category in existing.values():
        if category.builtin and category.key not in desired_keys:
            category.active = False

    if migrated:
        db.add(
            AuditEvent(
                actor_type="system",
                actor_id=SYSTEM_ACTOR_ID,
                action="taxonomy.migrate",
                object_type="category_taxonomy",
                object_id=None,
                details={"transaction_count": migrated},
            )
        )
    db.commit()


def normalize_category_key(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", value.lower())).strip("-")


def category_label(category: Category | None, locale: str) -> str | None:
    if category is None:
        return None
    if locale == "en" and category.label_en:
        return category.label_en
    return category.label_de
