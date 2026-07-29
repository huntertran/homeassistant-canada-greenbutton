"""Scrape Enbridge Gas MyAccount portal, download Green Button XML, POST to HA.

Login flow (recorded via `playwright codegen`):
    1. Sign in with email + password
    2. Skip MFA (if prompt appears)
    3. Dismiss notification banner (if present)
    4. Navigate to Share My Data
    5. Select service address from dropdown
    6. Select Billing + Gas usage data types
    7. Set From/To date range, agree to terms, download

Env vars (required):
    ENBRIDGE_EMAIL
    ENBRIDGE_PASSWORD
    ENBRIDGE_SERVICE_ADDRESS   partial match for dropdown item (e.g. "123 MAIN ST TORONTO")
    HA_BASE_URL, HA_TOKEN

Optional:
    ENBRIDGE_LOGIN_URL         override sign-in URL
    ENBRIDGE_LOOKBACK_DAYS=14  how far back From Date goes; default 14
    HEADLESS=0                 run headed for local debug
    SAVE_LOCAL=/path           also write downloaded file to this path
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

import enbridge_drive_upload
import enbridge_parser
import ha_upload
from env_local import load_env_local

load_env_local()

LOGIN_URL = os.environ.get(
    "ENBRIDGE_LOGIN_URL",
    "https://myaccount.enbridgegas.com/sign-in?returnUrl=%2FMy-Account%2FShare-my-Data",
)
LOOKBACK_DAYS = int(os.environ.get("ENBRIDGE_LOOKBACK_DAYS", "14"))
DIAG_DIR = Path(__file__).parent / "_diag"


def _date_range() -> tuple[str, str]:
    """Return (from_date, to_date) as MM/DD/YYYY strings."""
    today = datetime.now().date()
    start = today - timedelta(days=LOOKBACK_DAYS)
    fmt = lambda d: f"{d.month:02d}/{d.day:02d}/{d.year}"
    return fmt(start), fmt(today)


async def _human_pause() -> None:
    await asyncio.sleep(random.uniform(0.5, 2.0))


async def _save_diag(page: Page, label: str) -> None:
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        await page.screenshot(path=str(DIAG_DIR / f"{ts}_{label}.png"), full_page=True)
    except Exception:
        pass
    try:
        html = await page.content()
        (DIAG_DIR / f"{ts}_{label}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


async def _fill_date_field(page: Page, field_id: str, date_str: str) -> None:
    """Set a jQuery UI datepicker field via JS (direct fill fights the picker)."""
    await page.evaluate(
        """([id, val]) => {
            const el = document.getElementById(id);
            // jQuery UI datepicker
            if (typeof $ !== 'undefined' && $(el).data('datepicker')) {
                $(el).datepicker('setDate', val);
            } else {
                // Fallback: native value setter so React/Vue detect the change
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, val);
            }
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        [field_id, date_str],
    )
    await _human_pause()


async def run() -> int:
    email = os.environ["ENBRIDGE_EMAIL"]
    password = os.environ["ENBRIDGE_PASSWORD"]
    service_address = os.environ["ENBRIDGE_SERVICE_ADDRESS"]
    headless = os.environ.get("HEADLESS", "1") != "0"
    from_date, to_date = _date_range()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(accept_downloads=True)
        page = await ctx.new_page()
        page.set_default_timeout(30_000)

        try:
            await page.goto(LOGIN_URL, wait_until="load")

            # Accept cookies banner if present
            try:
                cookie_btn = page.get_by_role("button", name="Accept all cookies")
                await cookie_btn.wait_for(state="visible", timeout=5_000)
                await cookie_btn.click()
                await _human_pause()
            except PWTimeout:
                pass

            # Login
            email_box = page.get_by_role("textbox", name="Email address:")
            try:
                await email_box.wait_for(state="visible", timeout=15_000)
            except PWTimeout:
                await _save_diag(page, "login_not_loaded")
                raise RuntimeError("Email field never appeared. Check screenshot in _diag/.")

            await email_box.click()
            await _human_pause()
            await email_box.fill(email)
            await _human_pause()
            pw_box = page.get_by_role("textbox", name="Password:")
            await pw_box.click()
            await _human_pause()
            await pw_box.fill(password)
            await _human_pause()

            await _save_diag(page, "before_signin")
            await page.get_by_role("button", name="Sign in", exact=True).click()
            # Wait for post-login page element rather than networkidle (SPA never settles)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except PWTimeout:
                pass
            await _human_pause()

            # Skip MFA if prompted
            try:
                skip_mfa = page.get_by_role("link", name="Skip MFA")
                await skip_mfa.wait_for(state="visible", timeout=8_000)
                await skip_mfa.click()
                await page.wait_for_load_state("domcontentloaded", timeout=20_000)
                await _human_pause()
            except PWTimeout:
                pass

            await _save_diag(page, "after_signin")

            # Dismiss "Get ready for big rewards" promo modal if present
            try:
                rewards_ok = page.get_by_role("button", name="Ok")
                await rewards_ok.wait_for(state="visible", timeout=5_000)
                await rewards_ok.click()
                await _human_pause()
            except PWTimeout:
                pass

            # Dismiss notification banner if present
            try:
                dismiss = page.locator("#notificationDiv").get_by_text("X")
                await dismiss.wait_for(state="visible", timeout=5_000)
                await dismiss.click()
                await _human_pause()
            except PWTimeout:
                pass

            # Navigate to Share My Data (may already be there via returnUrl)
            if "/Share-my-Data" not in page.url and "/share-my-data" not in page.url.lower():
                share_link = page.get_by_role("link", name="sharemydata Share My Data")
                await share_link.wait_for(state="visible", timeout=15_000)
                await share_link.click()
                await page.wait_for_load_state("domcontentloaded", timeout=30_000)
                await _human_pause()

            # Wait for the service address dropdown to be ready
            await page.locator(".overSelect").wait_for(state="visible", timeout=30_000)
            await _human_pause()

            await _save_diag(page, "share_my_data")

            # Select service address from dropdown
            await page.locator(".overSelect").click()
            await _human_pause()
            await page.get_by_text(service_address).click()
            await _human_pause()

            # Select data types
            await page.get_by_role("button", name="Select one or more").click()
            await _human_pause()
            billing_cb = page.get_by_role("checkbox", name="Billing")
            gas_cb = page.get_by_role("checkbox", name="Gas usage")
            if not await billing_cb.is_checked():
                await billing_cb.check()
                await _human_pause()
            if not await gas_cb.is_checked():
                await gas_cb.check()
                await _human_pause()

            # Set date range
            await _fill_date_field(page, "fromDate", from_date)
            await _fill_date_field(page, "toDate", to_date)
            # Click body to close any open date picker
            await page.locator("body").click(position={"x": 1, "y": 1})
            await _human_pause()

            await _save_diag(page, "before_download")

            # Agree to terms
            terms_cb = page.get_by_role("checkbox", name="I agree to the Terms and")
            if not await terms_cb.is_checked():
                await terms_cb.check()
                await _human_pause()

            # Trigger download preparation
            await page.get_by_role("button", name="Download my data").click()
            # Wait for the "Download" link/button to appear (SPA never reaches networkidle)
            download_trigger = page.get_by_text("Download", exact=True)
            await download_trigger.wait_for(state="visible", timeout=60_000)
            await _human_pause()

            await _save_diag(page, "download_ready")

            # Download the file
            async with page.expect_download(timeout=120_000) as dl_info:
                await download_trigger.click()
            download = await dl_info.value
            tmp_path = await download.path()
            if not tmp_path:
                raise RuntimeError("Playwright returned empty download path")

            raw_bytes = Path(tmp_path).read_bytes()
            suggested_name = download.suggested_filename
            print(f"Downloaded: {suggested_name} ({len(raw_bytes)} bytes)")

            local_copy = os.environ.get("SAVE_LOCAL")
            if local_copy:
                Path(local_copy).write_bytes(raw_bytes)
                print(f"Saved locally: {local_copy}")

            result = ha_upload.post_xml(raw_bytes, source="enbridge")
            print(f"Uploaded {len(raw_bytes)} bytes -> {result.get('path')}")

            if os.environ.get("GDRIVE_REFRESH_TOKEN"):
                try:
                    from datetime import timezone as _tz
                    payload = enbridge_parser.parse_xml(raw_bytes)
                    payload["savedAt"] = datetime.now(_tz.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S.000Z"
                    )
                    drive_result = enbridge_drive_upload.upload_json(payload)
                    print(
                        f"Drive sync: {drive_result.get('name')} "
                        f"id={drive_result.get('id')} "
                        f"modified={drive_result.get('modifiedTime')}"
                    )
                except Exception as drive_err:  # noqa: BLE001
                    print(f"Drive upload failed (non-fatal): {drive_err}", file=sys.stderr)

            return 0

        except (PWTimeout, Exception) as err:  # noqa: BLE001
            traceback.print_exc()
            try:
                await _save_diag(page, "failure")
            except Exception:
                pass
            print(f"FAILED: {err}", file=sys.stderr)
            return 1
        finally:
            await ctx.close()
            await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
