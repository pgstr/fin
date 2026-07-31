from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from finanzplaner.categories import stable_category_id
from finanzplaner.db import SessionLocal
from finanzplaner.models import Account, RecurringSeries, Transaction
from finanzplaner.security import Actor
from finanzplaner.services import CAPABILITIES, FinanceService

from .conftest import TEST_DB_PATH, dkb_csv

REQUIRED_TOOLS = {
    "list_accounts",
    "list_categories",
    "list_transactions",
    "list_uncategorized_transactions",
    "get_transaction",
    "categorize_transactions",
    "uncategorize_transactions",
    "add_transaction_note",
    "add_transaction_tags",
    "get_month_summary",
    "get_year_summary",
    "get_category_trend",
    "get_balance_forecast",
    "list_recurring_series",
    "get_monthly_review",
    "save_monthly_review",
}


def initialize_request() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "fin-test", "version": "1"},
        },
    }


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def running_mcp_server():
    port = free_port()
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(TEST_DB_PATH)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "finanzplaner.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"MCP server exited early: {stdout}\n{stderr}")
        try:
            if httpx.get(f"{url}/health/live", timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        process.terminate()
        raise RuntimeError("MCP server did not become live")
    yield f"{url}/mcp", process
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    stdout, stderr = process.communicate()
    # Uvicorn 0.51 deliberately re-raises a captured SIGTERM after its graceful
    # shutdown block, so the OS status can be -SIGTERM even though lifespan
    # teardown completed.
    assert process.returncode in {0, -signal.SIGTERM}, (stdout, stderr)
    assert "session manager shutting down" in stderr.casefold()


@pytest.mark.asyncio
async def test_mcp_accepts_configured_ingress_host(admin, shared_account, running_mcp_server) -> None:
    with SessionLocal() as db:
        _record, raw_token = FinanceService(db).create_agent_token(
            Actor.human(admin),
            name="Ingress MCP",
            account_ids=[shared_account.id],
            capabilities=["transactions:read"],
            expires_at=None,
        )

    endpoint, _process = running_mcp_server
    async with httpx.AsyncClient() as client:
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {raw_token}",
                "Accept": "application/json, text/event-stream",
                "Host": "finanzen.home.arpa:8080",
                "Origin": "http://finanzen.home.arpa:8080",
            },
            json=initialize_request(),
        )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "Fin"


@pytest.mark.asyncio
async def test_official_client_enumerates_and_exercises_mcp_tools(
    admin, shared_account, running_mcp_server
) -> None:
    with SessionLocal() as db:
        service = FinanceService(db)
        service.import_dkb(
            Actor.human(admin),
            dkb_csv(),
            max_bytes=10_000_000,
            expected_account_id=shared_account.id,
        )
        private_account = Account(
            display_name="Private MCP boundary",
            iban="DE44500105175407324931",
            visibility="private",
            owner_id=admin.id,
            created_by_id=admin.id,
        )
        db.add(private_account)
        db.flush()
        service.import_dkb(
            Actor.human(admin),
            dkb_csv(iban=private_account.iban),
            max_bytes=10_000_000,
            expected_account_id=private_account.id,
        )
        transaction = db.scalar(
            select(Transaction).where(
                Transaction.account_id == shared_account.id,
                Transaction.amount_cents < 0,
            )
        )
        private_transaction = db.scalar(
            select(Transaction).where(Transaction.account_id == private_account.id)
        )
        recurring = RecurringSeries(
            account_id=shared_account.id,
            normalized_counterparty="test recurring",
            direction="outgoing",
            cadence="monthly",
            typical_amount_cents=-4_567,
            expected_next_date=date(2026, 2, 3),
            evidence={"transaction_ids": [transaction.id]},
        )
        db.add(recurring)
        db.commit()
        _record, raw_token = service.create_agent_token(
            Actor.human(admin),
            name="MCP integration",
            account_ids=[shared_account.id],
            capabilities=sorted(CAPABILITIES),
            expires_at=None,
        )
        _limited_record, limited_token = service.create_agent_token(
            Actor.human(admin),
            name="MCP read-only",
            account_ids=[shared_account.id],
            capabilities=["transactions:read"],
            expires_at=None,
        )
        _review_record, review_token = service.create_agent_token(
            Actor.human(admin),
            name="MCP review-only",
            account_ids=[shared_account.id],
            capabilities=["reviews:read"],
            expires_at=None,
        )
        transaction_id = transaction.id
        revision = transaction.revision
        private_account_id = private_account.id
        private_transaction_id = private_transaction.id

    endpoint, _process = running_mcp_server
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {raw_token}"}, follow_redirects=True
    ) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as (
            read_stream,
            write_stream,
            _session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == REQUIRED_TOOLS

                accounts = await session.call_tool("list_accounts", {})
                assert accounts.structuredContent["ok"]
                assert accounts.structuredContent["data"][0]["id"] == shared_account.id

                categories = await session.call_tool("list_categories", {})
                assert categories.structuredContent["ok"]
                assert any(
                    category["id"] == stable_category_id("groceries.general")
                    for category in categories.structuredContent["data"]
                )

                transactions = await session.call_tool(
                    "list_transactions",
                    {"account_id": shared_account.id, "month": "2026-01", "page_size": 1},
                )
                assert transactions.structuredContent["ok"]
                transaction_page = transactions.structuredContent["data"]
                assert len(transaction_page["items"]) == 1
                assert transaction_page["next_cursor"]
                next_page = await session.call_tool(
                    "list_transactions",
                    {
                        "account_id": shared_account.id,
                        "month": "2026-01",
                        "cursor": transaction_page["next_cursor"],
                        "page_size": 1,
                    },
                )
                assert len(next_page.structuredContent["data"]["items"]) == 1
                invalid_cursor = await session.call_tool(
                    "list_transactions",
                    {"account_id": shared_account.id, "cursor": "not-a-cursor"},
                )
                assert invalid_cursor.structuredContent["error"]["code"] == "invalid_cursor"

                page = await session.call_tool(
                    "list_uncategorized_transactions",
                    {"account_id": shared_account.id, "month": "2026-01", "page_size": 1},
                )
                assert page.structuredContent["ok"]
                assert len(page.structuredContent["data"]["items"]) == 1
                assert page.structuredContent["data"]["next_cursor"]

                detail = await session.call_tool(
                    "get_transaction", {"transaction_id": transaction_id}
                )
                assert detail.structuredContent["data"]["id"] == transaction_id

                categorized = await session.call_tool(
                    "categorize_transactions",
                    {
                        "assignments": [
                            {
                                "transaction_id": transaction_id,
                                "category_id": stable_category_id("groceries.general"),
                                "expected_revision": revision,
                            }
                        ],
                        "idempotency_key": "mcp-integration-categorize",
                    },
                )
                category_result = categorized.structuredContent["data"]["results"][0]
                assert category_result["status"] == "applied"
                uncategorized = await session.call_tool(
                    "uncategorize_transactions",
                    {
                        "assignments": [
                            {
                                "transaction_id": transaction_id,
                                "expected_revision": category_result["revision"],
                            }
                        ],
                        "idempotency_key": "mcp-integration-uncategorize",
                    },
                )
                assert (
                    uncategorized.structuredContent["data"]["results"][0]["status"]
                    == "applied"
                )

                note = await session.call_tool(
                    "add_transaction_note",
                    {"transaction_id": transaction_id, "content": "Agentenprüfung abgeschlossen."},
                )
                assert note.structuredContent["ok"]
                tags = await session.call_tool(
                    "add_transaction_tags",
                    {"transaction_id": transaction_id, "tags": ["geprüft"]},
                )
                assert tags.structuredContent["data"]["tags"] == ["geprüft"]

                trend = await session.call_tool(
                    "get_category_trend",
                    {
                        "account_id": shared_account.id,
                        "category_id": stable_category_id("groceries.general"),
                    },
                )
                assert trend.structuredContent["data"]["category_id"] == stable_category_id(
                    "groceries.general"
                )
                forecast = await session.call_tool(
                    "get_balance_forecast", {"account_id": shared_account.id}
                )
                assert forecast.structuredContent["data"]["available"]
                recurring_result = await session.call_tool(
                    "list_recurring_series", {"account_id": shared_account.id}
                )
                assert recurring_result.structuredContent["data"][0]["direction"] == "outgoing"

                review = await session.call_tool(
                    "save_monthly_review",
                    {
                        "account_id": shared_account.id,
                        "month": "2026-01",
                        "content": "## Monatsbild\n\nStabile Ausgaben.",
                        "expected_revision": 0,
                    },
                )
                assert review.structuredContent["data"]["revision"] == 1
                current_review = await session.call_tool(
                    "get_monthly_review",
                    {"account_id": shared_account.id, "month": "2026-01"},
                )
                assert current_review.structuredContent["data"]["revision"] == 1
                review_conflict = await session.call_tool(
                    "save_monthly_review",
                    {
                        "account_id": shared_account.id,
                        "month": "2026-01",
                        "content": "Stale revision",
                        "expected_revision": 0,
                    },
                )
                assert review_conflict.structuredContent["error"]["code"] == "revision_conflict"
                summary = await session.call_tool(
                    "get_month_summary",
                    {"account_id": shared_account.id, "month": "2026-01"},
                )
                assert summary.structuredContent["data"]["transaction_count"] == 2
                annual = await session.call_tool(
                    "get_year_summary",
                    {"account_id": shared_account.id, "year": 2026},
                )
                annual_data = annual.structuredContent["data"]
                assert annual_data["year"] == 2026
                assert len(annual_data["months"]) == 12
                assert annual_data["transaction_count"] == sum(
                    month["transaction_count"] for month in annual_data["months"]
                )
                assert "review_count" not in annual_data
                assert all("review" not in month for month in annual_data["months"])
                hidden = await session.call_tool(
                    "get_month_summary",
                    {"account_id": private_account_id, "month": "2026-01"},
                )
                assert hidden.structuredContent["error"]["code"] == "not_found"
                hidden_annual = await session.call_tool(
                    "get_year_summary",
                    {"account_id": private_account_id, "year": 2026},
                )
                assert hidden_annual.structuredContent["error"]["code"] == "not_found"
                hidden_transaction = await session.call_tool(
                    "get_transaction", {"transaction_id": private_transaction_id}
                )
                assert hidden_transaction.structuredContent["error"]["code"] == "not_found"
                invalid_month = await session.call_tool(
                    "get_month_summary",
                    {"account_id": shared_account.id, "month": "not-a-month"},
                )
                assert invalid_month.structuredContent["error"]["code"] == "month"
                invalid_year = await session.call_tool(
                    "get_year_summary",
                    {"account_id": shared_account.id, "year": 10_000},
                )
                assert invalid_year.structuredContent["error"]["code"] == "year"

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {limited_token}"}, follow_redirects=True
    ) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as (
            read_stream,
            write_stream,
            _session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                denied = await session.call_tool(
                    "get_month_summary",
                    {"account_id": shared_account.id, "month": "2026-01"},
                )
                assert denied.structuredContent["error"]["code"] == "permission_denied"
                denied_annual = await session.call_tool(
                    "get_year_summary",
                    {"account_id": shared_account.id, "year": 2026},
                )
                assert denied_annual.structuredContent["error"]["code"] == "permission_denied"

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {review_token}"}, follow_redirects=True
    ) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as (
            read_stream,
            write_stream,
            _session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                denied_discovery = await session.call_tool("list_accounts", {})
                assert denied_discovery.structuredContent["error"]["code"] == "permission_denied"
                denied_taxonomy = await session.call_tool("list_categories", {})
                assert denied_taxonomy.structuredContent["error"]["code"] == "permission_denied"
                allowed_review = await session.call_tool(
                    "get_monthly_review",
                    {"account_id": shared_account.id, "month": "2026-01"},
                )
                assert allowed_review.structuredContent["data"]["revision"] == 1


@pytest.mark.asyncio
async def test_mcp_rejects_invalid_and_revoked_tokens(admin, shared_account, running_mcp_server) -> None:
    endpoint, _process = running_mcp_server
    async with httpx.AsyncClient() as client:
        response = await client.post(
            endpoint,
            headers={"Authorization": "Bearer invalid", "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_token"

    with SessionLocal() as db:
        service = FinanceService(db)
        token, raw = service.create_agent_token(
            Actor.human(admin),
            name="Revoked",
            account_ids=[shared_account.id],
            capabilities=["transactions:read"],
            expires_at=None,
        )
        service.revoke_agent_token(Actor.human(admin), token.id)
        _expired, expired_raw = service.create_agent_token(
            Actor.human(admin),
            name="Expired",
            account_ids=[shared_account.id],
            capabilities=["transactions:read"],
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {raw}", "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert response.status_code == 401
        expired = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {expired_raw}",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert expired.status_code == 401
