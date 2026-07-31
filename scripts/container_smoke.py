from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import httpx


def hidden_value(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', html)
    if not match:
        raise RuntimeError(f"missing hidden field: {name}")
    return match.group(1)


def setup_token(token_file: Path | None) -> str:
    value = os.environ.get("SETUP_TOKEN")
    if value:
        return value
    if token_file is not None:
        return token_file.read_text().strip()
    raise RuntimeError("SETUP_TOKEN or --setup-token-file is required")


def initialize(
    base_url: str, fixture: Path, token_file: Path | None
) -> dict[str, str]:
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=15) as client:
        setup = client.get("/setup")
        setup.raise_for_status()
        created = client.post(
            "/setup",
            data={
                "form_token": hidden_value(setup.text, "form_token"),
                "setup_token": setup_token(token_file),
                "username": "container-admin",
                "password": "correct horse battery",
            },
        )
        if created.status_code != 303 or not client.cookies.get("fp_session"):
            raise RuntimeError(f"setup failed with status {created.status_code}")

        import_page = client.get("/import")
        import_page.raise_for_status()
        imported = client.post(
            "/import",
            data={
                "csrf_token": hidden_value(import_page.text, "csrf_token"),
                "expected_account_id": "",
                "new_account_name": "Container smoke account",
                "new_account_visibility": "shared",
            },
            files={"file": ("dkb-browser-demo.csv", fixture.read_bytes(), "text/csv")},
        )
        if imported.status_code != 303:
            raise RuntimeError(f"import failed with status {imported.status_code}")
        location = imported.headers["location"]
        account_match = re.search(r"/accounts/([^/]+)/", location)
        if not account_match:
            raise RuntimeError(f"unexpected import location: {location}")
        account_id = account_match.group(1)
        overview = client.get(f"/accounts/{account_id}/overview?month=2026-06")
        overview.raise_for_status()
        if "3.482,17" not in overview.text:
            raise RuntimeError("latest balance was not rendered after import")
        return {"account_id": account_id, "status": "initialized"}


def login(client: httpx.Client) -> None:
    if client.get("/setup").status_code != 404:
        raise RuntimeError("setup unexpectedly became available after restart")
    login_page = client.get("/login")
    login_page.raise_for_status()
    authenticated = client.post(
        "/login",
        data={
            "form_token": hidden_value(login_page.text, "form_token"),
            "username": "container-admin",
            "password": "correct horse battery",
            "next_url": "/",
        },
    )
    if authenticated.status_code != 303 or not client.cookies.get("fp_session"):
        raise RuntimeError(f"login failed with status {authenticated.status_code}")


def prepare_recovery(base_url: str) -> dict[str, str]:
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=15) as client:
        login(client)
        dashboard = client.get("/", follow_redirects=True)
        account_id = dashboard.url.path.split("/accounts/", 1)[1].split("/", 1)[0]
        review_page = client.get(f"/accounts/{account_id}/review?month=2026-06")
        review_page.raise_for_status()
        if "Container recovery review" not in review_page.text:
            saved = client.post(
                f"/accounts/{account_id}/review",
                data={
                    "csrf_token": hidden_value(review_page.text, "csrf_token"),
                    "month": "2026-06",
                    "expected_revision": hidden_value(
                        review_page.text, "expected_revision"
                    ),
                    "content": "## Container recovery review\n\nSynthetic recovery marker.",
                },
            )
            if saved.status_code != 303:
                raise RuntimeError(f"review save failed with status {saved.status_code}")
        return {"account_id": account_id, "status": "prepared"}


def verify(base_url: str) -> dict[str, str]:
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=15) as client:
        login(client)
        dashboard = client.get("/", follow_redirects=True)
        dashboard.raise_for_status()
        if "Container smoke account" not in dashboard.text or "3.482,17" not in dashboard.text:
            raise RuntimeError("persisted account or latest balance was not rendered")
        account_path = dashboard.url.path.rsplit("/", 1)[0]
        import_history = client.get(f"{account_path}/import")
        import_history.raise_for_status()
        if "Importverlauf" not in import_history.text or ">24</td>" not in import_history.text:
            raise RuntimeError("persisted import history was not rendered")
        transactions = client.get(f"{account_path}/transactions?month=2026-06")
        transactions.raise_for_status()
        if "Beispiel Supermarkt" not in transactions.text:
            raise RuntimeError("persisted transactions were not rendered")
        review = client.get(f"{account_path}/review?month=2026-06")
        review.raise_for_status()
        if "Container recovery review" not in review.text:
            raise RuntimeError("persisted review was not rendered")
        return {"status": "recovered"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("initialize", "prepare-recovery", "verify"))
    parser.add_argument("base_url")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--setup-token-file", type=Path)
    args = parser.parse_args()
    if args.mode == "initialize":
        if args.fixture is None:
            parser.error("--fixture is required for initialize")
        result = initialize(args.base_url, args.fixture, args.setup_token_file)
    elif args.mode == "prepare-recovery":
        result = prepare_recovery(args.base_url)
    else:
        result = verify(args.base_url)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
