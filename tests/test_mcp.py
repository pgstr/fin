from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from finanzplaner.categories import stable_category_id
from finanzplaner.db import SessionLocal
from finanzplaner.models import Account, Transaction
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
        transaction = db.scalar(select(Transaction).where(Transaction.amount_cents < 0))
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
        transaction_id = transaction.id
        revision = transaction.revision
        private_account_id = private_account.id

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

                page = await session.call_tool(
                    "list_uncategorized_transactions",
                    {"account_id": shared_account.id, "month": "2026-01", "page_size": 1},
                )
                assert page.structuredContent["ok"]
                assert len(page.structuredContent["data"]["items"]) == 1
                assert page.structuredContent["data"]["next_cursor"]

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
                assert categorized.structuredContent["data"]["results"][0]["status"] == "applied"

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
                summary = await session.call_tool(
                    "get_month_summary",
                    {"account_id": shared_account.id, "month": "2026-01"},
                )
                assert summary.structuredContent["data"]["transaction_count"] == 2
                hidden = await session.call_tool(
                    "get_month_summary",
                    {"account_id": private_account_id, "month": "2026-01"},
                )
                assert hidden.structuredContent["error"]["code"] == "not_found"
                invalid_month = await session.call_tool(
                    "get_month_summary",
                    {"account_id": shared_account.id, "month": "not-a-month"},
                )
                assert invalid_month.structuredContent["error"]["code"] == "month"

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
