from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import Page, expect, sync_playwright


@pytest.fixture
def browser_server(tmp_path: Path) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_PATH": str(tmp_path / "browser.db"),
            "BACKUP_DIR": str(tmp_path / "backups"),
            "SESSION_SECRET": "browser-session-secret-with-more-than-thirty-two-characters",
            "SETUP_TOKEN": "browser-setup-token",
            "ENVIRONMENT": "test",
            "TRUSTED_HOSTS": "127.0.0.1,localhost",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "finanzplaner.web:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=Path.cwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(f"browser server exited during startup:\n{output}")
        try:
            with urlopen(f"{base_url}/health/ready", timeout=1) as response:
                if response.status == 200:
                    break
        except (OSError, URLError):
            time.sleep(0.1)
    else:
        process.terminate()
        output = process.communicate(timeout=5)[0]
        pytest.fail(f"browser server was not ready:\n{output}")

    yield base_url

    process.terminate()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
    if process.stdout:
        process.stdout.close()


def assert_no_document_overflow(page: Page) -> None:
    dimensions = page.evaluate(
        """
        () => ({
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
        })
        """
    )
    assert dimensions["documentWidth"] <= dimensions["viewportWidth"]


def test_real_browser_workflow_is_responsive_and_accessible(
    browser_server: str, tmp_path: Path
) -> None:
    source = Path("tests/fixtures/dkb-browser-demo.csv").read_text()
    long_purpose = (
        "Außergewöhnlich lange synthetische Referenz für einen vollständig "
        "umbruchfähigen Buchungstext " * 4
    ).strip()
    source = source.replace("Gehalt Januar", long_purpose, 1)
    source = source.replace("2.600,00", "123.456.789,01", 1)
    upload = tmp_path / "browser-demo.csv"
    upload.write_text(source)
    artifacts = Path("test-results")
    artifacts.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        setup_context = browser.new_context(viewport={"width": 1280, "height": 900})
        setup_page = setup_context.new_page()
        setup_page.goto(f"{browser_server}/setup")
        setup_page.locator('[name="setup_token"]').fill("browser-setup-token")
        setup_page.locator('[name="username"]').fill("browser-admin")
        setup_page.locator('[name="password"]').fill("correct horse battery")
        setup_page.get_by_role("button", name="Installation einrichten").click()
        setup_page.wait_for_url(f"{browser_server}/")
        setup_page.goto(f"{browser_server}/import")
        setup_page.locator('[name="file"]').set_input_files(upload)
        setup_page.locator('[name="new_account_name"]').fill(
            "Sehr lang bezeichnetes gemeinsames Haushaltskonto"
        )
        setup_page.locator('[name="new_account_visibility"]').select_option("shared")
        setup_page.get_by_role("button", name="Datei prüfen und importieren").click()
        setup_page.wait_for_url(f"{browser_server}/accounts/*/import?*")
        account_id = setup_page.url.split("/accounts/", 1)[1].split("/", 1)[0]
        setup_context.close()

        for width in (1280, 390, 320):
            context = browser.new_context(viewport={"width": width, "height": 900})
            page = context.new_page()
            try:
                page.goto(f"{browser_server}/login")
                username = page.locator('[name="username"]')
                password = page.locator('[name="password"]')
                submit = page.get_by_role("button", name="Anmelden")
                expect(username).to_be_focused()
                page.keyboard.press("Tab")
                expect(password).to_be_focused()
                page.keyboard.press("Tab")
                expect(submit).to_be_focused()
                username.fill("browser-admin")
                password.fill("correct horse battery")
                submit.click()
                page.wait_for_url(f"{browser_server}/accounts/{account_id}/overview")

                routes = [
                    f"/accounts/{account_id}/overview?month=2026-06",
                    f"/accounts/{account_id}/transactions?month=2026-01",
                    f"/accounts/{account_id}/report?year=2026",
                    f"/accounts/{account_id}/forecast",
                    f"/accounts/{account_id}/import",
                ]
                for route in routes:
                    response = page.goto(f"{browser_server}{route}")
                    assert response and response.ok, route
                    expect(page.locator("main")).to_be_visible()
                    assert_no_document_overflow(page)

                if width == 1280:
                    page.goto(
                        f"{browser_server}/accounts/{account_id}/report?year=2026"
                    )
                    page.emulate_media(media="print")
                    expect(page.locator(".sidebar")).to_be_hidden()
                    assert len(page.pdf(format="A4", print_background=True)) > 1_000
                    page.emulate_media(media="screen")

                page.goto(
                    f"{browser_server}/accounts/{account_id}/transactions?month=2026-01"
                )
                expect(page.get_by_text(long_purpose, exact=True)).to_be_visible()
                expect(page.get_by_text("123.456.789,01", exact=False)).to_be_visible()
                detail_link = page.locator('a[href^="/transactions/"]').first
                detail_link.click()
                page.wait_for_url(f"{browser_server}/transactions/*")
                expect(page.locator("main")).to_be_visible()
                assert_no_document_overflow(page)

                page.goto(f"{browser_server}/accounts/{account_id}/overview?month=2026-06")
                expect(page.locator("details.chart-fallback")).to_be_visible()
                expect(page.locator("details.chart-fallback table")).to_have_count(1)

                page.goto(
                    f"{browser_server}/accounts/{account_id}/transactions?month=2025-12"
                )
                expect(page.locator("td.empty-cell")).to_be_visible()
                assert_no_document_overflow(page)

                error = page.goto(
                    f"{browser_server}/accounts/00000000-0000-0000-0000-000000000000/overview"
                )
                assert error and error.status == 404
                expect(page.get_by_role("heading", level=1)).to_be_visible()
                assert_no_document_overflow(page)
            except Exception:
                page.screenshot(
                    path=artifacts / f"browser-{width}-failure.png",
                    full_page=True,
                )
                raise
            finally:
                context.close()

        english_context = browser.new_context(viewport={"width": 1280, "height": 900})
        english_page = english_context.new_page()
        english_page.goto(f"{browser_server}/login?lang=en")
        english_page.locator('[name="username"]').fill("browser-admin")
        english_page.locator('[name="password"]').fill("correct horse battery")
        english_page.get_by_role("button", name="Sign in").click()
        english_page.goto(f"{browser_server}/settings")
        english_page.locator('[name="locale"]').select_option("en")
        english_page.locator('section.section form button[type="submit"]').click()
        english_page.goto(
            f"{browser_server}/accounts/{account_id}/overview?month=2026-06"
        )
        expect(
            english_page.locator("main").get_by_text("Monthly overview", exact=True)
        ).to_be_visible()
        assert_no_document_overflow(english_page)
        english_context.close()
        browser.close()
