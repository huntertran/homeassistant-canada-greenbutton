"""Scrape Alectra GreenButton portal, download XML, POST to HA.

Login form fields (accessible names, confirmed via `playwright codegen`):
    - "Account Name" textbox
    - "Account Number" textbox
    - phone textbox with placeholder "(000) 000-" — value must be formatted
      as "(NNN) NNN-NNNN"

After login: click the single link on the landing page, fill From/To Date
on the data page, then click the download button in the row matching the
configured meter / service-point ID.

Env vars (required):
    ALECTRA_ACCOUNT_NAME
    ALECTRA_ACCOUNT_NUMBER
    ALECTRA_PHONE          (raw 10 digits or already-formatted)
    ALECTRA_METER_ID       (the row identifier, e.g. 11025818)
    HA_BASE_URL, HA_TOKEN

Optional:
    ALECTRA_LOGIN_URL          override
    ALECTRA_LOOKBACK_DAYS=14  how far back the From Date goes; default 14
    HEADLESS=0                 run headed for local debug
    SAVE_LOCAL=/path           also write XML to this path
"""
from __future__ import annotations

import asyncio
import asyncio
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

import ha_upload
from env_local import load_env_local

load_env_local()

LOGIN_URL = os.environ.get(
    "ALECTRA_LOGIN_URL",
    "https://alectrautilitiesgbportal.savagedata.com/Connect/Authorize"
    "?returnUrl=https%3A%2F%2Falectrautilitiesgbportal.savagedata.com%2F",
)
LOOKBACK_DAYS = int(os.environ.get("ALECTRA_LOOKBACK_DAYS", "14"))
DIAG_DIR = Path(__file__).parent / "_diag"


def _format_phone(raw: str) -> str:
    """Accept '1234567890' or '(123) 456-7890' → '(123) 456-7890'."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"Phone must be 10 digits, got {len(digits)} from {raw!r}")
    return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"


def _date_range() -> tuple[str, str]:
    """Return (from_date, to_date) as M/D/YYYY strings."""
    today = datetime.now().date()
    start = today - timedelta(days=LOOKBACK_DAYS)
    fmt = lambda d: f"{d.month}/{d.day}/{d.year}"
    return fmt(start), fmt(today)


async def _human_pause() -> None:
    """Random think-time between UI interactions to look less bot-like."""
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


async def run() -> int:
    account_name = os.environ["ALECTRA_ACCOUNT_NAME"]
    account_number = os.environ["ALECTRA_ACCOUNT_NUMBER"]
    phone = _format_phone(os.environ["ALECTRA_PHONE"])
    meter_id = os.environ["ALECTRA_METER_ID"]
    headless = os.environ.get("HEADLESS", "1") != "0"
    from_date, to_date = _date_range()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(accept_downloads=True)
        page = await ctx.new_page()
        page.set_default_timeout(30_000)

        try:
            await page.goto(LOGIN_URL, wait_until="load")

            name_box = page.get_by_role("textbox", name="Account Name")
            number_box = page.get_by_role("textbox", name="Account Number")
            phone_box = page.get_by_role("textbox", name="(000) 000-")

            try:
                await name_box.wait_for(state="visible", timeout=10_000)
            except PWTimeout:
                await _save_diag(page, "login_not_loaded")
                raise RuntimeError(
                    "Account Name field never appeared. Check the screenshot in _diag/."
                )

            # Click-before-fill — Blazor form needs the focus event to wire up
            await name_box.click()
            await _human_pause()
            await name_box.fill(account_name)
            await _human_pause()
            await number_box.click()
            await _human_pause()
            await number_box.fill(account_number)
            await _human_pause()
            await phone_box.click()
            await _human_pause()
            await phone_box.fill(phone)
            await _human_pause()

            await _save_diag(page, "before_signin")
            await page.get_by_text("Sign In", exact=True).click()
            await _human_pause()

            # Landing page → single link leads to the data download page
            await page.wait_for_load_state("networkidle", timeout=45_000)
            await _save_diag(page, "after_signin")
            await page.get_by_role("link").first.click()
            await _human_pause()

            await page.wait_for_load_state("networkidle", timeout=45_000)
            await page.get_by_role("textbox", name="From Date:").fill(from_date)
            await _human_pause()
            await page.get_by_role("textbox", name="To Date:").fill(to_date)
            await _human_pause()
            # Blur date field so the row table refreshes; click body to dismiss any picker
            await page.locator("body").click(position={"x": 1, "y": 1})
            await _human_pause()

            await page.get_by_text("Electricity Usage Data").click()
            await _human_pause()
            await page.get_by_text("Billing Data").click()
            await _human_pause()
            await page.get_by_text("Account Information").click()
            await _human_pause()

            async with page.expect_download(timeout=120_000) as dl_info:
                await page.get_by_role("row", name=meter_id).get_by_role("button").click()
            download = await dl_info.value
            tmp_path = await download.path()
            if not tmp_path:
                raise RuntimeError("Playwright returned empty download path")
            xml_bytes = Path(tmp_path).read_bytes()

            local_copy = os.environ.get("SAVE_LOCAL")
            if local_copy:
                Path(local_copy).write_bytes(xml_bytes)

            result = ha_upload.post_xml(xml_bytes, source="alectra")
            print(f"Uploaded {len(xml_bytes)} bytes → {result.get('path')}")
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
