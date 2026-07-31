from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from finanzplaner.db import Base

from .conftest import dkb_csv


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
    with closing(sqlite3.connect(database)) as connection:
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

    with closing(sqlite3.connect(database)) as connection, connection:
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
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT export_from, export_to FROM import_batches"
        ).fetchone() == ("2026-01-01", "2026-07-26")


def test_migration_infers_existing_recurring_series_direction(tmp_path: Path) -> None:
    database = tmp_path / "recurring-direction.db"
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database)
    initial = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260726_0002"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert initial.returncode == 0, initial.stderr

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """
            INSERT INTO users (
                id, username, password_hash, is_admin, active, locale,
                created_at, updated_at
            ) VALUES (
                'user', 'operator', 'hash', 1, 1, 'de',
                '2026-07-31 12:00:00', '2026-07-31 12:00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO accounts (
                id, display_name, iban, account_type, visibility, owner_id,
                created_by_id, created_at, updated_at
            ) VALUES (
                'account', 'Girokonto', 'DE02120300000000202051',
                'girokonto', 'shared', NULL, 'user',
                '2026-07-31 12:00:00', '2026-07-31 12:00:00'
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO recurring_series (
                id, account_id, normalized_counterparty, cadence,
                typical_amount_cents, expected_next_date, status, enabled,
                evidence, manually_overridden, created_at, updated_at
            ) VALUES (
                ?, 'account', ?, 'monthly', ?, '2026-08-01', 'confirmed', 1,
                '{}', 0, '2026-07-31 12:00:00', '2026-07-31 12:00:00'
            )
            """,
            [
                ("incoming", "employer", 200_000),
                ("outgoing", "landlord", -80_000),
            ],
        )

    upgraded = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT id, direction FROM recurring_series ORDER BY id"
        ).fetchall() == [("incoming", "incoming"), ("outgoing", "outgoing")]


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
    assert {service["image"] for service in services.values()} == {
        "localhost/finanzplaner:1.2.0-rc.2"
    }


def test_podium_acceptance_stack_is_host_only_and_isolated() -> None:
    stack = json.loads(
        Path("podium/finanzplaner.acceptance.stack.json").read_text()
    )
    assert stack["name"] == "finanzplaner-acceptance"
    assert stack["dns"] is True
    assert stack["ingress"] == {
        "hostPort": 18081,
        "bindAddress": "127.0.0.1",
        "routes": [
            {
                "host": "finanzplaner-acceptance.home.arpa",
                "service": "app",
                "port": 8080,
            }
        ],
    }
    services = {service["id"]: service for service in stack["services"]}
    assert set(services) == {"app", "backup"}
    assert {service["image"] for service in services.values()} == {
        "localhost/finanzplaner:1.2.0-rc.2"
    }
    assert services["backup"]["schedule"] == "15 3 * * *"
    assert {
        volume["name"]
        for service in services.values()
        for volume in service["volumes"]
    } == {"finanzdaten-acceptance", "finanzbackups-acceptance"}


def test_podium_demo_stack_is_private_synthetic_and_egress_blocked() -> None:
    stack = json.loads(Path("podium/finanzplaner.demo.stack.json").read_text())
    assert stack["name"] == "finanzplaner-demo"
    assert stack["dns"] is False
    assert stack["ingress"] == {
        "hostPort": 18082,
        "bindAddress": "127.0.0.1",
        "routes": [
            {
                "host": "demo-node.example.ts.net",
                "service": "app",
                "port": 8080,
            }
        ],
    }
    assert len(stack["services"]) == 1
    app = stack["services"][0]
    assert app["id"] == "app"
    assert app["image"] == "localhost/finanzplaner-demo:1.2.0-rc.2"
    assert app["entrypoint"] == ["/usr/local/bin/finanzplaner-demo-entrypoint"]
    assert app["env"]["COOKIE_SECURE"] == "true"
    assert app["env"]["TRUSTED_HOSTS"] == (
        "demo-node.example.ts.net,localhost,127.0.0.1"
    )
    assert set(app["secrets"]) == {"SESSION_SECRET", "SETUP_TOKEN"}
    assert app["volumes"] == [
        {"name": "finanzdaten-demo", "destination": "/data"}
    ]
    assert app["restartPolicy"] == "always"
    assert app["healthCheck"][-1].endswith("/health/ready")
    assert app["livenessCheck"][-1].endswith("/health/live")

    dockerfile = Path("Dockerfile.demo").read_text()
    entrypoint = Path("docker/demo-entrypoint.sh").read_text()
    assert "ARG FIN_IMAGE=localhost/finanzplaner:1.2.0-rc.2" in dockerfile
    assert "apt-get install --no-install-recommends -y iptables" in dockerfile
    assert "iptables -P OUTPUT DROP" in entrypoint
    assert "ip6tables -P OUTPUT DROP" in entrypoint
    assert "--ctstate ESTABLISHED,RELATED" in entrypoint
    assert 'exec /usr/local/bin/finanzplaner-entrypoint "$@"' in entrypoint


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


def test_backup_cli_create_list_and_verify(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    backups = tmp_path / "backups"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE example (value TEXT NOT NULL)")
        connection.execute("INSERT INTO example VALUES ('kept')")
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database)
    environment["BACKUP_DIR"] = str(backups)

    created = subprocess.run(
        [sys.executable, "-m", "finanzplaner", "backup", "create"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    backup = Path(created.stdout.strip())
    assert backup.is_file()

    listed = subprocess.run(
        [sys.executable, "-m", "finanzplaner", "backup", "list"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    assert f"ok\t{backup.stat().st_size}\t{backup}" in listed.stdout

    verified = subprocess.run(
        [sys.executable, "-m", "finanzplaner", "backup", "verify", str(backup)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout) == {
        "path": str(backup),
        "integrity_check": "ok",
    }


def test_private_sample_validation_cli_reports_aggregates_only(tmp_path: Path) -> None:
    rows = [
        [
            "01.01.26",
            "01.01.26",
            "Gebucht",
            "",
            f"Ausgabe {index}",
            "",
            "Karte",
            "",
            "-1,00",
            "",
            "",
            "",
        ]
        for index in range(325)
    ]
    rows.extend(
        [
            [
                "01.01.26",
                "01.01.26",
                "Gebucht",
                f"Eingang {index}",
                "",
                "",
                "Überweisung",
                "",
                "0,00" if index == 0 else "1,00",
                "",
                "",
                "",
            ]
            for index in range(17)
        ]
    )
    sample = tmp_path / "private.csv"
    sample.write_bytes(dkb_csv(rows, balance="572,26"))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "finanzplaner",
            "validate-private-sample",
            str(sample),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "aggregates": {
            "balance_cents": 57_226,
            "incoming": 17,
            "outgoing": 325,
            "rows": 342,
            "zero": 1,
        },
        "valid": True,
    }
    assert "Ausgabe" not in result.stdout
    assert "Eingang" not in result.stdout
