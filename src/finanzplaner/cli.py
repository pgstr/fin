from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from .backup import create_backup, list_backups, verify_backup
from .config import get_settings
from .csv_import import parse_dkb_csv


def backup_command(args: argparse.Namespace) -> int:
    if args.backup_action == "create":
        path = create_backup()
        print(path)
        return 0
    if args.backup_action == "list":
        invalid = False
        for item in list_backups():
            status = "ok" if item.valid else "FAILED"
            print(f"{status}\t{item.size}\t{item.path}")
            invalid = invalid or not item.valid
        return 1 if invalid else 0
    path = Path(args.path)
    valid = verify_backup(path)
    print(json.dumps({"path": str(path), "integrity_check": "ok" if valid else "failed"}))
    return 0 if valid else 1


def validate_sample(path: str) -> int:
    parsed = parse_dkb_csv(Path(path).read_bytes())
    result = {
        "rows": len(parsed.transactions),
        "balance_cents": parsed.reported_balance_cents,
        "outgoing": sum(transaction.direction == "outgoing" for transaction in parsed.transactions),
        "incoming": sum(transaction.direction == "incoming" for transaction in parsed.transactions),
        "zero": sum(transaction.amount_cents == 0 for transaction in parsed.transactions),
    }
    expected = {
        "rows": 342,
        "balance_cents": 57_226,
        "outgoing": 325,
        "incoming": 17,
        "zero": 1,
    }
    print(json.dumps({"valid": result == expected, "aggregates": result}, sort_keys=True))
    return 0 if result == expected else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finanzplaner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the web and MCP server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    backup = subparsers.add_parser("backup", help="Create, list, or verify backups")
    backup_subparsers = backup.add_subparsers(dest="backup_action", required=True)
    backup_subparsers.add_parser("create")
    backup_subparsers.add_parser("list")
    verify = backup_subparsers.add_parser("verify")
    verify.add_argument("path")
    sample = subparsers.add_parser("validate-private-sample", help="Validate only documented aggregates")
    sample.add_argument("path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "serve":
        config = get_settings()
        uvicorn.run(
            "finanzplaner.web:app",
            host=args.host,
            port=args.port,
            log_level=config.log_level.casefold(),
            access_log=False,
            proxy_headers=False,
            server_header=False,
        )
        code = 0
    elif args.command == "backup":
        code = backup_command(args)
    else:
        code = validate_sample(args.path)
    sys.exit(code)


if __name__ == "__main__":
    main()

