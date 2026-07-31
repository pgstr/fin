from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from finanzplaner.db import Base


def test_fresh_migration_downgrade_and_reupgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database)
    commands = [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        [sys.executable, "-m", "alembic", "upgrade", "head"],
    ]
    for command in commands:
        result = subprocess.run(command, env=environment, text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert set(Base.metadata.tables) <= tables


def test_migration_repairs_stale_import_period_year(tmp_path: Path) -> None:
    database = tmp_path / "repair.db"
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database)
    initial = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260725_0001"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert initial.returncode == 0, initial.stderr

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO import_batches (
                id, account_id, uploader_id, file_sha256, imported_at,
                export_from, export_to, reported_balance_cents,
                reported_balance_date, row_count, inserted_count, duplicate_count
            ) VALUES (
                'batch', 'account', 'user', ?, '2026-07-26 12:00:00',
                '2020-01-01', '2020-07-26', 48353,
                '2026-07-26', 1, 1, 0
            )
            """,
            ("0" * 64,),
        )
        connection.execute(
            """
            INSERT INTO transactions (
                id, account_id, import_batch_id, booking_date, value_date,
                status, direction, amount_cents, currency, payer, payee,
                purpose, transaction_type, counterparty_iban, creditor_id,
                mandate_reference, customer_reference, display_counterparty,
                raw_fields, signature, occurrence_index, revision, created_at
            ) VALUES (
                'transaction', 'account', 'batch', '2026-07-24', '2026-07-24',
                'Gebucht', 'outgoing', -1000, 'EUR', '', 'Supermarkt',
                'Einkauf', 'Karte', '', '', '', '', 'Supermarkt',
                '{}', ?, 0, 1, '2026-07-26 12:00:00'
            )
            """,
            ("1" * 64,),
        )

    repaired = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repaired.returncode == 0, repaired.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT export_from, export_to FROM import_batches"
        ).fetchone() == ("2026-01-01", "2026-07-26")


def test_native_podium_stack_has_required_operational_contract() -> None:
    stack = json.loads(Path("podium/finanzplaner.stack.json").read_text())
    assert stack["name"] == "finanzplaner"
    assert stack["dns"] is True
    services = {service["id"]: service for service in stack["services"]}
    assert set(services) == {"app", "backup"}
    app = services["app"]
    assert app["restartPolicy"] == "always"
    assert app["cpus"] == 1
    assert app["memoryMB"] == 512
    assert app["rootfsGB"] == 1
    assert app["healthCheck"][-1].endswith("/health/ready")
    assert app["livenessCheck"][-1].endswith("/health/live")
    assert {volume["name"] for volume in app["volumes"]} == {"finanzdaten", "finanzbackups"}
    assert set(app["secrets"]) >= {"SESSION_SECRET", "SETUP_TOKEN"}
    assert services["backup"]["schedule"] == "15 3 * * *"
    assert services["backup"]["image"] == app["image"]
    assert stack["ingress"]["bindAddress"] == "0.0.0.0"
    assert stack["ingress"]["routes"] == [
        {"host": "finanzen.home.arpa", "service": "app", "port": 8080},
        {"host": "m1-pro.local", "service": "app", "port": 8080},
    ]


def test_container_is_locked_and_offline_at_runtime() -> None:
    dockerfile = Path("Dockerfile").read_text()
    entrypoint = Path("docker/entrypoint.sh").read_text()
    assert "python:3.13-slim-bookworm" in dockerfile
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "USER root" not in dockerfile
    assert "gosu finanzplaner" in entrypoint
    assert "if ! chown finanzplaner:finanzplaner /data /backups" in entrypoint
    assert "install -d -o finanzplaner" not in entrypoint
    assert Path("uv.lock").is_file()
