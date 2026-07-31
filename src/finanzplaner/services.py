from __future__ import annotations

import base64
import json
import re
import secrets
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import bleach
from markdown_it import MarkdownIt
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .analytics import (
    add_months,
    balance_forecast,
    category_trend,
    month_start,
    month_summary,
)
from .categories import normalize_category_key
from .csv_import import (
    audit_payload,
    display_counterparty,
    normalize_iban,
    occurrence_signatures,
    parse_dkb_csv,
)
from .errors import AppError, ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from .models import (
    Account,
    AgentToken,
    AuditEvent,
    BalanceSnapshot,
    Category,
    CategoryAssignmentEvent,
    IdempotencyRecord,
    ImportBatch,
    MonthlyReview,
    RecurringSeries,
    Tag,
    Transaction,
    TransactionNote,
    TransactionTag,
    TransferLink,
    User,
    WebSession,
    utc_now,
)
from .security import Actor, digest_token, hash_password, validate_username, verify_password

CAPABILITIES = {
    "transactions:read",
    "transactions:categorize",
    "notes:write",
    "tags:write",
    "analytics:read",
    "reviews:read",
    "reviews:write",
}
markdown = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
SAFE_TAGS = {
    "p", "br", "strong", "em", "ul", "ol", "li", "blockquote", "code", "pre", "h1", "h2", "h3",
    "h4", "a", "hr",
}


def render_markdown(value: str) -> str:
    rendered = markdown.render(value)
    return bleach.clean(
        rendered,
        tags=SAFE_TAGS,
        attributes={"a": ["href", "title", "rel"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
        offset = int(value["o"])
        return max(0, offset)
    except Exception as exc:
        raise ValidationError("invalid_cursor", "error.validation") from exc


@dataclass
class Page:
    items: list[Any]
    next_cursor: str | None


def audit(
    db: Session,
    actor: Actor,
    action: str,
    object_type: str,
    object_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            details=details or {},
        )
    )


class FinanceService:
    def __init__(self, db: Session):
        self.db = db

    def user_count(self) -> int:
        return int(self.db.scalar(select(func.count(User.id))) or 0)

    def setup_admin(self, username: str, password: str) -> User:
        if self.user_count() != 0:
            raise NotFoundError()
        self._validate_credentials(username, password)
        user = User(
            username=username.strip().casefold(),
            password_hash=hash_password(password),
            is_admin=True,
            locale="de",
        )
        self.db.add(user)
        self.db.flush()
        audit(self.db, Actor.human(user), "installation.setup", "user", user.id)
        self.db.commit()
        return user

    def _validate_credentials(self, username: str, password: str) -> None:
        if not validate_username(username.strip()):
            raise ValidationError("username_invalid", "error.username_invalid")
        if len(password) < 12:
            raise ValidationError("password_short", "error.password_short")

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.db.scalar(select(User).where(User.username == username.strip().casefold()))
        if not user or not user.active or not verify_password(user.password_hash, password):
            return None
        return user

    def require_admin(self, actor: Actor) -> None:
        if actor.actor_type != "human" or not actor.is_admin:
            raise PermissionDeniedError()

    def visible_account_query(self, actor: Actor):
        query = select(Account)
        if actor.actor_type == "agent":
            return query.where(Account.id.in_(list(actor.account_ids or ())))
        return query.where(or_(Account.visibility == "shared", Account.owner_id == actor.user_id))

    def list_accounts(self, actor: Actor) -> list[Account]:
        if actor.actor_type == "agent" and "transactions:read" not in actor.capabilities:
            raise PermissionDeniedError()
        return self.db.scalars(
            self.visible_account_query(actor).order_by(
                (Account.visibility == "shared").desc(), Account.created_at, Account.display_name
            )
        ).all()

    def get_account(self, actor: Actor, account_id: str, capability: str | None = None) -> Account:
        if actor.actor_type == "agent" and capability and capability not in actor.capabilities:
            raise PermissionDeniedError()
        account = self.db.scalar(self.visible_account_query(actor).where(Account.id == account_id))
        if account is None:
            raise NotFoundError()
        return account

    def create_account(
        self,
        actor: Actor,
        *,
        display_name: str,
        iban: str,
        visibility: str,
        owner_id: str | None = None,
    ) -> Account:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        name = display_name.strip()
        normalized_iban = normalize_iban(iban)
        if not name or visibility not in {"shared", "private"}:
            raise ValidationError("account_invalid", "error.validation")
        if visibility == "private":
            owner_id = owner_id or actor.user_id
            if owner_id != actor.user_id:
                raise PermissionDeniedError()
        else:
            owner_id = None
        account = Account(
            display_name=name,
            iban=normalized_iban,
            visibility=visibility,
            owner_id=owner_id,
            created_by_id=actor.user_id,
        )
        self.db.add(account)
        self.db.flush()
        audit(
            self.db,
            actor,
            "account.create",
            "account",
            account.id,
            {"visibility": visibility},
        )
        return account

    def import_dkb(
        self,
        actor: Actor,
        data: bytes,
        *,
        max_bytes: int,
        expected_account_id: str | None = None,
        new_account_name: str | None = None,
        new_account_visibility: str | None = None,
    ) -> ImportBatch:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        parsed = parse_dkb_csv(data, max_bytes=max_bytes)
        account = self.db.scalar(select(Account).where(Account.iban == parsed.account_iban))
        if expected_account_id:
            expected = self.get_account(actor, expected_account_id)
            if expected.iban != parsed.account_iban:
                raise ValidationError("account_mismatch", "error.account_mismatch")
            account = expected
        if account is None:
            if not new_account_name or new_account_visibility not in {"shared", "private"}:
                raise ValidationError(
                    "account_unknown",
                    "error.account_unknown",
                    details={"iban_suffix": parsed.account_iban[-4:]},
                )
            account = self.create_account(
                actor,
                display_name=new_account_name,
                iban=parsed.account_iban,
                visibility=new_account_visibility,
            )
        else:
            account = self.get_account(actor, account.id)
        signatures = occurrence_signatures(account.id, parsed)
        same_file_seen = self.db.scalar(
            select(ImportBatch.id).where(
                ImportBatch.account_id == account.id,
                ImportBatch.file_sha256 == parsed.file_sha256,
            )
        )
        if same_file_seen:
            existing = set(signatures)
        else:
            existing = set(
                self.db.execute(
                    select(Transaction.signature, Transaction.occurrence_index).where(
                        Transaction.account_id == account.id,
                        Transaction.signature.in_({signature for signature, _ in signatures}),
                    )
                ).all()
            )
        inserted_count = sum(pair not in existing for pair in signatures)
        batch = ImportBatch(
            account_id=account.id,
            uploader_id=actor.user_id,
            file_sha256=parsed.file_sha256,
            export_from=parsed.export_from,
            export_to=parsed.export_to,
            reported_balance_cents=parsed.reported_balance_cents,
            reported_balance_date=parsed.reported_balance_date,
            row_count=len(parsed.transactions),
            inserted_count=inserted_count,
            duplicate_count=len(parsed.transactions) - inserted_count,
        )
        self.db.add(batch)
        self.db.flush()
        for parsed_tx, (signature, occurrence) in zip(parsed.transactions, signatures, strict=True):
            if (signature, occurrence) in existing:
                continue
            fields = parsed_tx.fields
            self.db.add(
                Transaction(
                    account_id=account.id,
                    import_batch_id=batch.id,
                    booking_date=parsed_tx.booking_date,
                    value_date=parsed_tx.value_date,
                    status=fields["Status"].strip(),
                    direction=parsed_tx.direction,
                    amount_cents=parsed_tx.amount_cents,
                    payer=fields["Zahlungspflichtige*r"],
                    payee=fields["Zahlungsempfänger*in"],
                    purpose=fields["Verwendungszweck"],
                    transaction_type=fields["Umsatztyp"],
                    counterparty_iban=normalize_iban(fields["IBAN"]),
                    creditor_id=fields["Gläubiger-ID"],
                    mandate_reference=fields["Mandatsreferenz"],
                    customer_reference=fields["Kundenreferenz"],
                    display_counterparty=display_counterparty(fields, parsed_tx.amount_cents),
                    raw_fields=audit_payload(fields),
                    signature=signature,
                    occurrence_index=occurrence,
                    category_id=None,
                    category_actor_type=None,
                )
            )
        self.db.add(
            BalanceSnapshot(
                account_id=account.id,
                import_batch_id=batch.id,
                balance_cents=parsed.reported_balance_cents,
                balance_date=parsed.reported_balance_date,
            )
        )
        audit(
            self.db,
            actor,
            "import.commit",
            "import_batch",
            batch.id,
            {
                "account_id": account.id,
                "rows": batch.row_count,
                "inserted": batch.inserted_count,
                "duplicates": batch.duplicate_count,
            },
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.match_transfers()
        return batch

    def list_imports(self, actor: Actor, account_id: str) -> list[ImportBatch]:
        self.get_account(actor, account_id)
        return self.db.scalars(
            select(ImportBatch)
            .where(ImportBatch.account_id == account_id)
            .order_by(ImportBatch.imported_at.desc())
        ).all()

    def get_transaction(
        self, actor: Actor, transaction_id: str, capability: str = "transactions:read"
    ) -> Transaction:
        tx = self.db.scalar(
            select(Transaction)
            .options(
                joinedload(Transaction.category),
                joinedload(Transaction.notes),
                joinedload(Transaction.tag_links).joinedload(TransactionTag.tag),
            )
            .where(Transaction.id == transaction_id)
        )
        if tx is None:
            raise NotFoundError()
        self.get_account(actor, tx.account_id, capability)
        return tx

    def list_transactions(
        self,
        actor: Actor,
        account_id: str,
        *,
        value_month: date | None = None,
        category_id: str | None = None,
        uncategorized: bool = False,
        direction: str | None = None,
        tag: str | None = None,
        min_amount_cents: int | None = None,
        max_amount_cents: int | None = None,
        text: str | None = None,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page:
        self.get_account(actor, account_id, "transactions:read")
        page_size = max(1, min(page_size, 200))
        offset = decode_cursor(cursor)
        query = (
            select(Transaction)
            .options(joinedload(Transaction.category))
            .where(Transaction.account_id == account_id)
        )
        if value_month:
            start = month_start(value_month)
            end = add_months(start, 1)
            query = query.where(Transaction.booking_date >= start, Transaction.booking_date < end)
        if uncategorized:
            query = query.where(Transaction.category_id.is_(None))
        elif category_id:
            query = query.where(Transaction.category_id == category_id)
        if direction:
            query = query.where(Transaction.direction == direction)
        if tag:
            query = query.join(TransactionTag).join(Tag).where(Tag.normalized_name == self.normalize_tag(tag))
        if min_amount_cents is not None:
            query = query.where(func.abs(Transaction.amount_cents) >= min_amount_cents)
        if max_amount_cents is not None:
            query = query.where(func.abs(Transaction.amount_cents) <= max_amount_cents)
        if text:
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            query = query.where(
                or_(
                    Transaction.display_counterparty.ilike(pattern, escape="\\"),
                    Transaction.purpose.ilike(pattern, escape="\\"),
                    Transaction.transaction_type.ilike(pattern, escape="\\"),
                )
            )
        rows = self.db.scalars(
            query.order_by(Transaction.booking_date.desc(), Transaction.id.desc())
            .offset(offset)
            .limit(page_size + 1)
        ).unique().all()
        more = len(rows) > page_size
        return Page(rows[:page_size], encode_cursor(offset + page_size) if more else None)

    def list_categories(self, actor: Actor, include_archived: bool = False) -> list[Category]:
        if actor.actor_type == "agent" and "transactions:read" not in actor.capabilities:
            raise PermissionDeniedError()
        query = select(Category).order_by(Category.parent_id.is_not(None), Category.sort_order, Category.label_de)
        if not include_archived:
            query = query.where(Category.active.is_(True))
        categories = self.db.scalars(query).all()
        if include_archived:
            return categories
        active_root_ids = {category.id for category in categories if category.parent_id is None}
        return [
            category
            for category in categories
            if category.parent_id is None or category.parent_id in active_root_ids
        ]

    def _category_for_assignment(self, category_id: str) -> Category:
        category = self.db.get(Category, category_id)
        parent = self.db.get(Category, category.parent_id) if category and category.parent_id else None
        if (
            not category
            or not category.active
            or not category.assignable
            or parent is None
            or not parent.active
        ):
            raise ValidationError("category_not_assignable", "error.category_leaf")
        return category

    def categorize(
        self,
        actor: Actor,
        transaction_id: str,
        category_id: str | None,
        expected_revision: int,
    ) -> dict[str, Any]:
        tx = self.get_transaction(actor, transaction_id, "transactions:categorize" if actor.actor_type == "agent" else "transactions:read")
        if tx.revision != expected_revision:
            return {"transaction_id": tx.id, "status": "conflict", "revision": tx.revision, "code": "revision_conflict"}
        if actor.actor_type == "agent" and tx.category_id is not None and tx.category_actor_type == "human":
            if category_id == tx.category_id:
                return {"transaction_id": tx.id, "status": "unchanged", "revision": tx.revision}
            return {"transaction_id": tx.id, "status": "conflict", "revision": tx.revision, "code": "human_authoritative"}
        if category_id is not None:
            self._category_for_assignment(category_id)
        if tx.category_id == category_id:
            return {"transaction_id": tx.id, "status": "unchanged", "revision": tx.revision}
        if actor.actor_type == "agent" and category_id is None and tx.category_actor_type == "human":
            return {"transaction_id": tx.id, "status": "conflict", "revision": tx.revision, "code": "human_authoritative"}
        previous = tx.category_id
        tx.category_id = category_id
        tx.category_actor_type = actor.actor_type if category_id is not None else (
            "human-cleared" if actor.actor_type == "human" else "agent"
        )
        tx.category_actor_id = actor.actor_id
        tx.revision += 1
        self.db.add(
            CategoryAssignmentEvent(
                transaction_id=tx.id,
                previous_category_id=previous,
                category_id=category_id,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                revision=tx.revision,
            )
        )
        audit(
            self.db,
            actor,
            "transaction.category.change",
            "transaction",
            tx.id,
            {"category_id": category_id, "revision": tx.revision},
        )
        return {"transaction_id": tx.id, "status": "applied", "revision": tx.revision}

    def categorize_batch(
        self,
        actor: Actor,
        assignments: list[dict[str, Any]],
        *,
        idempotency_key: str,
        uncategorize: bool = False,
    ) -> dict[str, Any]:
        if actor.actor_type != "agent" or actor.token_id is None:
            raise PermissionDeniedError()
        if "transactions:categorize" not in actor.capabilities:
            raise PermissionDeniedError()
        if len(assignments) > 100:
            raise ValidationError("batch_too_large", "error.validation")
        action = "uncategorize_transactions" if uncategorize else "categorize_transactions"
        existing = self.db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.agent_token_id == actor.token_id,
                IdempotencyRecord.action == action,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing.result
        results = []
        for item in assignments:
            try:
                results.append(
                    self.categorize(
                        actor,
                        item["transaction_id"],
                        None if uncategorize else item.get("category_id"),
                        int(item["expected_revision"]),
                    )
                )
            except AppError as error:
                results.append(
                    {
                        "transaction_id": item["transaction_id"],
                        "status": "conflict",
                        "code": error.code,
                    }
                )
        result = {"results": results}
        self.db.add(
            IdempotencyRecord(
                agent_token_id=actor.token_id,
                action=action,
                idempotency_key=idempotency_key,
                result=result,
            )
        )
        audit(
            self.db,
            actor,
            f"mcp.{action}",
            "transaction_batch",
            None,
            {"transaction_ids": [item["transaction_id"] for item in assignments]},
        )
        self.db.commit()
        return result

    def add_note(self, actor: Actor, transaction_id: str, content: str) -> TransactionNote:
        tx = self.get_transaction(actor, transaction_id, "notes:write" if actor.actor_type == "agent" else "transactions:read")
        cleaned = content.strip()
        if not 1 <= len(cleaned) <= 10_000:
            raise ValidationError("note_length", "error.note_length")
        note = TransactionNote(
            transaction_id=tx.id,
            author_type=actor.actor_type,
            author_id=actor.actor_id,
            content=cleaned,
        )
        tx.notes.append(note)
        self.db.flush()
        audit(self.db, actor, "transaction.note.add", "transaction_note", note.id, {"transaction_id": tx.id})
        self.db.commit()
        return note

    def update_human_note(self, actor: Actor, note_id: str, content: str | None) -> None:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        note = self.db.get(TransactionNote, note_id)
        if not note:
            raise NotFoundError()
        self.get_transaction(actor, note.transaction_id)
        if note.author_type != "human" or note.author_id != actor.user_id:
            raise PermissionDeniedError()
        if content is None:
            self.db.delete(note)
            action = "transaction.note.delete"
        else:
            cleaned = content.strip()
            if not 1 <= len(cleaned) <= 10_000:
                raise ValidationError("note_length", "error.note_length")
            note.content = cleaned
            action = "transaction.note.update"
        audit(self.db, actor, action, "transaction_note", note_id)
        self.db.commit()

    @staticmethod
    def normalize_tag(value: str) -> str:
        return unicodedata.normalize("NFKC", value).strip().casefold()

    def add_tags(self, actor: Actor, transaction_id: str, names: list[str]) -> list[Tag]:
        tx = self.get_transaction(actor, transaction_id, "tags:write" if actor.actor_type == "agent" else "transactions:read")
        added: list[Tag] = []
        for raw_name in names:
            name = unicodedata.normalize("NFKC", raw_name).strip()
            normalized = self.normalize_tag(name)
            if not 1 <= len(name) <= 80:
                raise ValidationError("tag_invalid", "error.tag")
            tag = self.db.scalar(
                select(Tag).where(Tag.account_id == tx.account_id, Tag.normalized_name == normalized)
            )
            if not tag:
                tag = Tag(account_id=tx.account_id, name=name, normalized_name=normalized)
                self.db.add(tag)
                self.db.flush()
            link = self.db.get(
                TransactionTag,
                {
                    "transaction_id": tx.id,
                    "tag_id": tag.id,
                    "author_type": actor.actor_type,
                    "author_id": actor.actor_id,
                },
            )
            if not link:
                tx.tag_links.append(
                    TransactionTag(
                        transaction_id=tx.id,
                        tag_id=tag.id,
                        author_type=actor.actor_type,
                        author_id=actor.actor_id,
                        tag=tag,
                    )
                )
            added.append(tag)
        audit(
            self.db,
            actor,
            "transaction.tags.add",
            "transaction",
            tx.id,
            {"tag_ids": [tag.id for tag in added]},
        )
        self.db.commit()
        return added

    def list_tags(self, actor: Actor, account_id: str) -> list[Tag]:
        self.get_account(actor, account_id, "transactions:read")
        return self.db.scalars(
            select(Tag).where(Tag.account_id == account_id).order_by(Tag.normalized_name)
        ).all()

    def get_transfer_presentation(self, actor: Actor, transaction_id: str) -> dict[str, Any] | None:
        tx = self.get_transaction(actor, transaction_id)
        link = self.db.scalar(
            select(TransferLink).where(
                or_(
                    TransferLink.transaction_a_id == tx.id,
                    TransferLink.transaction_b_id == tx.id,
                )
            )
        )
        if not link:
            return None
        other_id = link.transaction_b_id if link.transaction_a_id == tx.id else link.transaction_a_id
        other = self.db.get(Transaction, other_id)
        try:
            self.get_account(actor, other.account_id)
        except NotFoundError:
            return {"linked": True, "private_counterpart": True}
        return {
            "linked": True,
            "private_counterpart": False,
            "transaction_id": other.id,
            "booking_date": other.booking_date,
            "amount_cents": other.amount_cents,
        }

    def match_transfers(self) -> int:
        linked_ids = set()
        for row in self.db.execute(select(TransferLink.transaction_a_id, TransferLink.transaction_b_id)):
            linked_ids.update(row)
        accounts = {account.id: account for account in self.db.scalars(select(Account)).all()}
        by_iban = {account.iban: account for account in accounts.values()}
        transactions = self.db.scalars(
            select(Transaction).where(Transaction.id.not_in(linked_ids) if linked_ids else True)
        ).all()
        candidates: dict[str, list[Transaction]] = defaultdict(list)
        for tx in transactions:
            candidates[tx.account_id].append(tx)
        created = 0
        considered: set[tuple[str, str]] = set()
        for tx in transactions:
            if tx.amount_cents >= 0 or not tx.counterparty_iban:
                continue
            target = by_iban.get(tx.counterparty_iban)
            if not target or target.id == tx.account_id:
                continue
            matches = [
                other
                for other in candidates[target.id]
                if other.amount_cents == -tx.amount_cents
                and abs((other.booking_date - tx.booking_date).days) <= 3
                and (not other.counterparty_iban or other.counterparty_iban == accounts[tx.account_id].iban)
            ]
            reverse_matches = []
            if len(matches) == 1:
                chosen = matches[0]
                reverse_matches = [
                    source
                    for source in candidates[tx.account_id]
                    if source.amount_cents == -chosen.amount_cents
                    and abs((source.booking_date - chosen.booking_date).days) <= 3
                    and source.counterparty_iban == target.iban
                ]
            if len(matches) == 1 and len(reverse_matches) == 1:
                pair = tuple(sorted((tx.id, matches[0].id)))
                if pair not in considered:
                    self.db.add(
                        TransferLink(
                            transaction_a_id=pair[0],
                            transaction_b_id=pair[1],
                            evidence={"amount_exact": True, "date_window_days": 3, "iban_supported": True},
                        )
                    )
                    considered.add(pair)
                    created += 1
        if created:
            self.db.commit()
        return created

    @staticmethod
    def _normalized_counterparty(tx: Transaction) -> str:
        value = unicodedata.normalize("NFKC", tx.display_counterparty).casefold()
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9äöüß ]+", " ", value)).strip()

    def detect_recurring(self, actor: Actor, account_id: str) -> list[RecurringSeries]:
        self.get_account(actor, account_id, "analytics:read" if actor.actor_type == "agent" else "transactions:read")
        transactions = self.db.scalars(
            select(Transaction)
            .where(Transaction.account_id == account_id, Transaction.amount_cents != 0)
            .order_by(Transaction.booking_date)
        ).all()
        groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
        for tx in transactions:
            normalized = self._normalized_counterparty(tx)
            if normalized:
                groups[(normalized, tx.direction)].append(tx)
        detected = []
        cadence_ranges = {
            "weekly": (6, 8),
            "monthly": (25, 35),
            "quarterly": (80, 100),
            "yearly": (350, 380),
        }
        for (counterparty, direction), items in groups.items():
            if direction not in {"incoming", "outgoing"} or len(items) < 3:
                continue
            amounts = [tx.amount_cents for tx in items]
            typical = round(statistics.median(amounts))
            if typical == 0:
                continue
            tolerance = max(abs(typical) * 0.05, 100)
            compatible = [tx for tx in items if abs(tx.amount_cents - typical) <= tolerance]
            if len(compatible) < 3:
                continue
            intervals = [
                (right.booking_date - left.booking_date).days
                for left, right in zip(compatible, compatible[1:], strict=False)
            ]
            cadence = next(
                (
                    name
                    for name, (low, high) in cadence_ranges.items()
                    if sum(low <= interval <= high for interval in intervals) >= max(2, len(intervals) - 1)
                ),
                None,
            )
            if not cadence:
                continue
            last = compatible[-1].booking_date
            next_date = last + timedelta(days=7) if cadence == "weekly" else add_months(
                last, {"monthly": 1, "quarterly": 3, "yearly": 12}[cadence]
            )
            series = self.db.scalar(
                select(RecurringSeries).where(
                    RecurringSeries.account_id == account_id,
                    RecurringSeries.normalized_counterparty == counterparty,
                    RecurringSeries.direction == direction,
                    RecurringSeries.cadence == cadence,
                )
            )
            evidence = {
                "transaction_ids": [tx.id for tx in compatible],
                "dates": [tx.booking_date.isoformat() for tx in compatible],
                "interval_days": intervals,
                "amount_range_cents": [min(tx.amount_cents for tx in compatible), max(tx.amount_cents for tx in compatible)],
            }
            if not series:
                series = RecurringSeries(
                    account_id=account_id,
                    normalized_counterparty=counterparty,
                    direction=direction,
                    cadence=cadence,
                    typical_amount_cents=typical,
                    expected_next_date=next_date,
                    evidence=evidence,
                )
                self.db.add(series)
            elif not series.manually_overridden:
                series.typical_amount_cents = typical
                series.expected_next_date = next_date
                series.evidence = evidence
            detected.append(series)
        self.db.flush()
        audit(
            self.db,
            actor,
            "recurring.detect",
            "account",
            account_id,
            {"series_count": len(detected)},
        )
        self.db.commit()
        return detected

    def list_recurring(self, actor: Actor, account_id: str) -> list[RecurringSeries]:
        self.get_account(actor, account_id, "analytics:read" if actor.actor_type == "agent" else "transactions:read")
        return self.db.scalars(
            select(RecurringSeries)
            .where(RecurringSeries.account_id == account_id)
            .order_by(RecurringSeries.status, RecurringSeries.expected_next_date)
        ).all()

    def update_recurring(
        self,
        actor: Actor,
        series_id: str,
        *,
        status: str,
        cadence: str | None = None,
        typical_amount_cents: int | None = None,
        expected_next_date: date | None = None,
        enabled: bool | None = None,
    ) -> RecurringSeries:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        series = self.db.get(RecurringSeries, series_id)
        if not series:
            raise NotFoundError()
        self.get_account(actor, series.account_id)
        if status not in {"detected", "confirmed", "rejected"}:
            raise ValidationError("recurring_status", "error.validation")
        if cadence and cadence not in {"weekly", "monthly", "quarterly", "yearly"}:
            raise ValidationError("recurring_cadence", "error.validation")
        series.status = status
        if cadence:
            series.cadence = cadence
        if typical_amount_cents is not None:
            series.typical_amount_cents = typical_amount_cents
        if expected_next_date:
            series.expected_next_date = expected_next_date
        if enabled is not None:
            series.enabled = enabled
        series.manually_overridden = True
        audit(self.db, actor, "recurring.override", "recurring_series", series.id, {"status": status})
        self.db.commit()
        return series

    def summary(self, actor: Actor, account_id: str, value_month: date) -> dict:
        self.get_account(actor, account_id, "analytics:read" if actor.actor_type == "agent" else "transactions:read")
        return month_summary(self.db, account_id, value_month, actor.locale)

    def trend(self, actor: Actor, account_id: str, category_id: str) -> dict:
        self.get_account(actor, account_id, "analytics:read")
        category = self.db.get(Category, category_id)
        if not category or not category.assignable or category.parent_id is None:
            raise ValidationError("category_not_assignable", "error.category_leaf")
        return category_trend(self.db, account_id, category_id, actor.locale)

    def forecast(self, actor: Actor, account_id: str) -> dict:
        self.get_account(actor, account_id, "analytics:read" if actor.actor_type == "agent" else "transactions:read")
        return balance_forecast(self.db, account_id)

    def get_review(self, actor: Actor, account_id: str, value_month: date) -> MonthlyReview | None:
        self.get_account(actor, account_id, "reviews:read" if actor.actor_type == "agent" else "transactions:read")
        return self.db.scalar(
            select(MonthlyReview)
            .where(
                MonthlyReview.account_id == account_id,
                MonthlyReview.month == month_start(value_month),
            )
            .order_by(MonthlyReview.revision.desc())
            .limit(1)
        )

    def review_history(self, actor: Actor, account_id: str, value_month: date) -> list[MonthlyReview]:
        self.get_account(actor, account_id, "reviews:read" if actor.actor_type == "agent" else "transactions:read")
        return self.db.scalars(
            select(MonthlyReview)
            .where(
                MonthlyReview.account_id == account_id,
                MonthlyReview.month == month_start(value_month),
            )
            .order_by(MonthlyReview.revision.desc())
        ).all()

    def save_review(
        self,
        actor: Actor,
        account_id: str,
        value_month: date,
        content: str,
        expected_revision: int,
    ) -> MonthlyReview:
        self.get_account(actor, account_id, "reviews:write" if actor.actor_type == "agent" else "transactions:read")
        cleaned = content.strip()
        if not 1 <= len(cleaned) <= 50_000:
            raise ValidationError("review_length", "error.review_length")
        current = self.db.scalar(
            select(MonthlyReview)
            .where(
                MonthlyReview.account_id == account_id,
                MonthlyReview.month == month_start(value_month),
            )
            .order_by(MonthlyReview.revision.desc())
            .limit(1)
        )
        actual_revision = current.revision if current else 0
        if expected_revision != actual_revision:
            raise ConflictError("revision_conflict", "error.revision")
        review = MonthlyReview(
            account_id=account_id,
            month=month_start(value_month),
            revision=actual_revision + 1,
            content=cleaned,
            author_type=actor.actor_type,
            author_id=actor.actor_id,
        )
        self.db.add(review)
        self.db.flush()
        audit(
            self.db,
            actor,
            "monthly_review.revise",
            "monthly_review",
            review.id,
            {"account_id": account_id, "month": review.month.isoformat(), "revision": review.revision},
        )
        self.db.commit()
        return review

    def list_users(self, actor: Actor) -> list[User]:
        self.require_admin(actor)
        return self.db.scalars(select(User).order_by(User.username)).all()

    def create_user(self, actor: Actor, username: str, password: str, is_admin: bool, locale: str) -> User:
        self.require_admin(actor)
        self._validate_credentials(username, password)
        if locale not in {"de", "en"}:
            raise ValidationError("locale", "error.validation")
        if self.db.scalar(select(User).where(User.username == username.strip().casefold())):
            raise ValidationError("username_exists", "error.username_exists")
        user = User(
            username=username.strip().casefold(),
            password_hash=hash_password(password),
            is_admin=is_admin,
            locale=locale,
        )
        self.db.add(user)
        self.db.flush()
        audit(self.db, actor, "user.create", "user", user.id, {"is_admin": is_admin})
        self.db.commit()
        return user

    def set_user_active(self, actor: Actor, user_id: str, active: bool) -> None:
        self.require_admin(actor)
        user = self.db.get(User, user_id)
        if not user:
            raise NotFoundError()
        if user.id == actor.user_id and not active:
            raise ConflictError()
        user.active = active
        if not active:
            self.db.execute(delete(WebSession).where(WebSession.user_id == user.id))
        audit(self.db, actor, "user.status", "user", user.id, {"active": active})
        self.db.commit()

    def reset_password(self, actor: Actor, user_id: str, password: str) -> None:
        self.require_admin(actor)
        if len(password) < 12:
            raise ValidationError("password_short", "error.password_short")
        user = self.db.get(User, user_id)
        if not user:
            raise NotFoundError()
        user.password_hash = hash_password(password)
        self.db.execute(delete(WebSession).where(WebSession.user_id == user.id))
        audit(self.db, actor, "user.password.reset", "user", user.id)
        self.db.commit()

    def set_locale(self, actor: Actor, locale: str) -> None:
        if actor.actor_type != "human" or locale not in {"de", "en"}:
            raise ValidationError("locale", "error.validation")
        user = self.db.get(User, actor.user_id)
        if not user:
            raise NotFoundError()
        user.locale = locale
        audit(self.db, actor, "user.locale", "user", user.id, {"locale": locale})
        self.db.commit()

    def create_category(
        self,
        actor: Actor,
        *,
        parent_id: str | None,
        key: str,
        label_de: str,
        label_en: str | None,
        sort_order: int,
    ) -> Category:
        self.require_admin(actor)
        parent = self.db.get(Category, parent_id) if parent_id else None
        if parent and parent.parent_id is not None:
            raise ValidationError("category_depth", "error.validation")
        normalized_key = normalize_category_key(key)
        full_key = f"{parent.key}.{normalized_key}" if parent else normalized_key
        if not full_key or self.db.scalar(select(Category).where(Category.key == full_key)):
            raise ValidationError("category_key", "error.validation")
        category = Category(
            key=full_key,
            parent_id=parent.id if parent else None,
            label_de=label_de.strip(),
            label_en=label_en.strip() if label_en else None,
            builtin=False,
            assignable=parent is not None,
            sort_order=sort_order,
            created_by_id=actor.user_id,
        )
        self.db.add(category)
        self.db.flush()
        audit(self.db, actor, "category.create", "category", category.id, {"key": category.key})
        self.db.commit()
        return category

    def update_category(
        self,
        actor: Actor,
        category_id: str,
        *,
        label_de: str,
        label_en: str | None,
        sort_order: int,
        active: bool,
    ) -> Category:
        self.require_admin(actor)
        category = self.db.get(Category, category_id)
        if not category:
            raise NotFoundError()
        category.label_de = label_de.strip()
        category.label_en = label_en.strip() if label_en else None
        category.sort_order = sort_order
        category.active = active
        audit(self.db, actor, "category.update", "category", category.id, {"active": active})
        self.db.commit()
        return category

    def create_agent_token(
        self,
        actor: Actor,
        *,
        name: str,
        account_ids: list[str],
        capabilities: list[str],
        expires_at: datetime | None,
    ) -> tuple[AgentToken, str]:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        requested_caps = set(capabilities)
        if not requested_caps or not requested_caps <= CAPABILITIES:
            raise ValidationError("capabilities", "error.validation")
        for account_id in set(account_ids):
            self.get_account(actor, account_id)
        raw = "fp_" + secrets.token_urlsafe(40)
        token = AgentToken(
            user_id=actor.user_id,
            name=name.strip(),
            prefix=raw[:12],
            token_hash=digest_token(raw),
            account_ids=sorted(set(account_ids)),
            capabilities=sorted(requested_caps),
            locale=actor.locale,
            expires_at=expires_at,
        )
        self.db.add(token)
        self.db.flush()
        audit(
            self.db,
            actor,
            "agent_token.create",
            "agent_token",
            token.id,
            {"account_ids": token.account_ids, "capabilities": token.capabilities},
        )
        self.db.commit()
        return token, raw

    def list_agent_tokens(self, actor: Actor) -> list[AgentToken]:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        return self.db.scalars(
            select(AgentToken)
            .where(AgentToken.user_id == actor.user_id)
            .order_by(AgentToken.created_at.desc())
        ).all()

    def revoke_agent_token(self, actor: Actor, token_id: str) -> None:
        if actor.actor_type != "human":
            raise PermissionDeniedError()
        token = self.db.scalar(
            select(AgentToken).where(AgentToken.id == token_id, AgentToken.user_id == actor.user_id)
        )
        if not token:
            raise NotFoundError()
        token.revoked_at = utc_now()
        audit(self.db, actor, "agent_token.revoke", "agent_token", token.id)
        self.db.commit()

    def authenticate_agent(self, raw_token: str) -> Actor | None:
        token = self.db.scalar(
            select(AgentToken)
            .options(joinedload(AgentToken.user))
            .where(AgentToken.token_hash == digest_token(raw_token))
        )
        now = datetime.now(UTC)
        if (
            not token
            or token.revoked_at is not None
            or not token.user.active
            or (
                token.expires_at is not None
                and token.expires_at.replace(tzinfo=UTC) <= now
            )
        ):
            return None
        return Actor(
            actor_type="agent",
            actor_id=token.id,
            user_id=token.user_id,
            locale=token.locale,
            account_ids=frozenset(token.account_ids),
            capabilities=frozenset(token.capabilities),
            token_id=token.id,
        )
