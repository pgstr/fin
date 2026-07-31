from __future__ import annotations

import contextvars
from datetime import date
from typing import Annotated, Any, Literal

from fastapi.encoders import jsonable_encoder
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from .categories import category_label
from .config import get_settings
from .db import SessionLocal
from .errors import AppError, PermissionDeniedError, ValidationError
from .models import Category, Transaction
from .security import Actor
from .services import FinanceService

current_agent: contextvars.ContextVar[Actor | None] = contextvars.ContextVar(
    "current_finanzplaner_agent", default=None
)
settings = get_settings()

mcp = FastMCP(
    "Fin",
    instructions=(
        "Read and annotate household financial data only within the token's explicit account "
        "and capability scopes. Categories chosen by humans are authoritative."
    ),
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=settings.mcp_allowed_origins,
    ),
)


class CategoryAssignment(BaseModel):
    transaction_id: str
    category_id: str
    expected_revision: int = Field(ge=1)


class UncategorizedAssignment(BaseModel):
    transaction_id: str
    expected_revision: int = Field(ge=1)


def actor() -> Actor:
    value = current_agent.get()
    if value is None:
        raise PermissionDeniedError()
    return value


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": jsonable_encoder(data)}


def failure(error: AppError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message_key": error.message_key,
            "details": error.details,
        },
    }


def parse_month(value: str) -> date:
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValidationError("month", "error.validation") from exc


def tool_call(callback):
    try:
        with SessionLocal() as db:
            return ok(callback(FinanceService(db), actor()))
    except AppError as error:
        return failure(error)


def serialize_account(account) -> dict[str, Any]:
    return {
        "id": account.id,
        "display_name": account.display_name,
        "type": account.account_type,
        "visibility": account.visibility,
        "currency": "EUR",
    }


def serialize_category(category: Category, locale: str) -> dict[str, Any]:
    return {
        "id": category.id,
        "key": category.key,
        "parent_id": category.parent_id,
        "label": category_label(category, locale),
        "assignable": category.assignable,
        "active": category.active,
        "order": category.sort_order,
    }


def serialize_transaction(transaction: Transaction, locale: str, full: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "booking_date": transaction.booking_date.isoformat(),
        "value_date": transaction.value_date.isoformat(),
        "direction": transaction.direction,
        "amount_minor": transaction.amount_cents,
        "currency": "EUR",
        "display_counterparty": transaction.display_counterparty,
        "purpose": transaction.purpose,
        "transaction_type": transaction.transaction_type,
        "category": (
            {
                "id": transaction.category.id,
                "key": transaction.category.key,
                "label": category_label(transaction.category, locale),
            }
            if transaction.category
            else None
        ),
        "revision": transaction.revision,
    }
    if full:
        data.update(
            {
                "status": transaction.status,
                "payer": transaction.payer,
                "payee": transaction.payee,
                "counterparty_iban": transaction.counterparty_iban,
                "creditor_id": transaction.creditor_id,
                "mandate_reference": transaction.mandate_reference,
                "customer_reference": transaction.customer_reference,
                "import_batch_id": transaction.import_batch_id,
                "notes": [
                    {
                        "id": note.id,
                        "author_type": note.author_type,
                        "content": note.content,
                        "created_at": note.created_at.isoformat(),
                    }
                    for note in transaction.notes
                ],
                "tags": sorted({link.tag.name for link in transaction.tag_links}),
            }
        )
    return data


def serialize_year_summary(summary: dict[str, Any]) -> dict[str, Any]:
    data = {key: value for key, value in summary.items() if key != "review_count"}
    data["months"] = [
        {
            key: value
            for key, value in month.items()
            if key not in {"recent_transactions", "review"}
        }
        for month in summary["months"]
    ]
    return data


@mcp.tool(description="List accounts visible to this agent token.")
def list_accounts() -> dict[str, Any]:
    return tool_call(lambda service, principal: [serialize_account(a) for a in service.list_accounts(principal)])


@mcp.tool(description="List the shared category taxonomy using the token locale.")
def list_categories(include_archived: bool = False) -> dict[str, Any]:
    return tool_call(
        lambda service, principal: [
            serialize_category(category, principal.locale)
            for category in service.list_categories(principal, include_archived)
        ]
    )


@mcp.tool(description="List accessible transactions with opaque cursor pagination.")
def list_transactions(
    account_id: str,
    month: str | None = None,
    category_id: str | None = None,
    uncategorized: bool = False,
    direction: Literal["incoming", "outgoing"] | None = None,
    tag: str | None = None,
    min_amount_minor: int | None = None,
    max_amount_minor: int | None = None,
    text: str | None = None,
    cursor: str | None = None,
    page_size: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        value_month = parse_month(month) if month else None
        page = service.list_transactions(
            principal,
            account_id,
            value_month=value_month,
            category_id=category_id,
            uncategorized=uncategorized,
            direction=direction,
            tag=tag,
            min_amount_cents=min_amount_minor,
            max_amount_cents=max_amount_minor,
            text=text,
            cursor=cursor,
            page_size=page_size,
        )
        return {
            "items": [serialize_transaction(tx, principal.locale) for tx in page.items],
            "next_cursor": page.next_cursor,
        }

    return tool_call(run)


@mcp.tool(description="List only uncategorized transactions for an accessible account.")
def list_uncategorized_transactions(
    account_id: str,
    month: str | None = None,
    cursor: str | None = None,
    page_size: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        value_month = parse_month(month) if month else None
        page = service.list_transactions(
            principal,
            account_id,
            value_month=value_month,
            uncategorized=True,
            cursor=cursor,
            page_size=page_size,
        )
        return {
            "items": [serialize_transaction(tx, principal.locale) for tx in page.items],
            "next_cursor": page.next_cursor,
        }

    return tool_call(run)


@mcp.tool(description="Get complete imported facts and annotations for one accessible transaction.")
def get_transaction(transaction_id: str) -> dict[str, Any]:
    return tool_call(
        lambda service, principal: serialize_transaction(
            service.get_transaction(principal, transaction_id), principal.locale, full=True
        )
    )


@mcp.tool(description="Assign leaf categories to at most 100 transactions with optimistic concurrency.")
def categorize_transactions(
    assignments: Annotated[list[CategoryAssignment], Field(max_length=100)],
    idempotency_key: Annotated[str, Field(min_length=1, max_length=120)],
) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        return service.categorize_batch(
            principal,
            [assignment.model_dump() for assignment in assignments],
            idempotency_key=idempotency_key,
        )

    return tool_call(run)


@mcp.tool(description="Remove agent-authored categories without overriding human assignments.")
def uncategorize_transactions(
    assignments: Annotated[list[UncategorizedAssignment], Field(max_length=100)],
    idempotency_key: Annotated[str, Field(min_length=1, max_length=120)],
) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        return service.categorize_batch(
            principal,
            [assignment.model_dump() for assignment in assignments],
            idempotency_key=idempotency_key,
            uncategorize=True,
        )

    return tool_call(run)


@mcp.tool(description="Append an agent-authored note; existing notes are never replaced.")
def add_transaction_note(
    transaction_id: str,
    content: Annotated[str, Field(min_length=1, max_length=10_000)],
) -> dict[str, Any]:
    return tool_call(
        lambda service, principal: {
            "note_id": service.add_note(principal, transaction_id, content).id,
            "transaction_id": transaction_id,
        }
    )


@mcp.tool(description="Add free-form tags while preserving human-authored tag links.")
def add_transaction_tags(
    transaction_id: str,
    tags: Annotated[list[str], Field(min_length=1, max_length=50)],
) -> dict[str, Any]:
    return tool_call(
        lambda service, principal: {
            "transaction_id": transaction_id,
            "tags": [tag.name for tag in service.add_tags(principal, transaction_id, tags)],
        }
    )


@mcp.tool(description="Get calculated totals for one account and calendar month.")
def get_month_summary(account_id: str, month: str) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        summary = service.summary(principal, account_id, parse_month(month))
        return {
            key: value
            for key, value in summary.items()
            if key not in {"recent_transactions", "review"}
        }

    return tool_call(run)


@mcp.tool(description="Get 12 reconciled calendar-month summaries and annual totals for one account.")
def get_year_summary(account_id: str, year: int) -> dict[str, Any]:
    return tool_call(
        lambda service, principal: serialize_year_summary(
            service.year_summary(principal, account_id, year)
        )
    )


@mcp.tool(description="Get up to 12 complete months and the simple linear category trend.")
def get_category_trend(account_id: str, category_id: str) -> dict[str, Any]:
    return tool_call(lambda service, principal: service.trend(principal, account_id, category_id))


@mcp.tool(description="Get the deterministic annual account balance forecast through December.")
def get_balance_forecast(account_id: str) -> dict[str, Any]:
    return tool_call(lambda service, principal: service.forecast(principal, account_id))


@mcp.tool(description="List detected, confirmed, and rejected recurring series for an account.")
def list_recurring_series(account_id: str) -> dict[str, Any]:
    return tool_call(
        lambda service, principal: [
            {
                "id": series.id,
                "account_id": series.account_id,
                "counterparty": series.normalized_counterparty,
                "direction": series.direction,
                "cadence": series.cadence,
                "typical_amount_minor": series.typical_amount_cents,
                "currency": "EUR",
                "expected_next_date": series.expected_next_date.isoformat(),
                "status": series.status,
                "enabled": series.enabled,
                "evidence": series.evidence,
            }
            for series in service.list_recurring(principal, account_id)
        ]
    )


@mcp.tool(description="Get the current authored monthly review and revision.")
def get_monthly_review(account_id: str, month: str) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        review = service.get_review(principal, account_id, parse_month(month))
        return (
            {
                "account_id": account_id,
                "month": month,
                "revision": review.revision,
                "content": review.content,
                "author_type": review.author_type,
                "created_at": review.created_at.isoformat(),
            }
            if review
            else {"account_id": account_id, "month": month, "revision": 0, "content": None}
        )

    return tool_call(run)


@mcp.tool(description="Save a new immutable monthly-review revision with optimistic concurrency.")
def save_monthly_review(
    account_id: str,
    month: str,
    content: Annotated[str, Field(min_length=1, max_length=50_000)],
    expected_revision: Annotated[int, Field(ge=0)],
) -> dict[str, Any]:
    def run(service: FinanceService, principal: Actor):
        review = service.save_review(
            principal,
            account_id,
            parse_month(month),
            content,
            expected_revision,
        )
        return {
            "account_id": account_id,
            "month": month,
            "revision": review.revision,
            "created_at": review.created_at.isoformat(),
        }

    return tool_call(run)


class AgentBearerMiddleware:
    """Authenticate bearer tokens before the official MCP ASGI transport."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        raw_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        principal = None
        if raw_token:
            with SessionLocal() as db:
                principal = FinanceService(db).authenticate_agent(raw_token)
        if principal is None:
            body = b'{"error":{"code":"invalid_token","message":"Invalid, revoked, or expired bearer token"}}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        token = current_agent.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_agent.reset(token)


mcp_asgi_app = AgentBearerMiddleware(mcp.streamable_http_app())
