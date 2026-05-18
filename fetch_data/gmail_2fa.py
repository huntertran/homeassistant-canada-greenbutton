"""Poll Gmail for an Alectra 2FA email and extract the 6-digit code.

Auth uses an OAuth refresh token only — never interactive. Three env vars:
    GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
Scope: gmail.readonly.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_CODE_RE = re.compile(r"\b(\d{6})\b")


def _service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=GMAIL_SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_b64url(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _extract_text(msg: dict) -> str:
    """Walk the MIME tree, collect all text/plain and text/html bodies."""
    out: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data and mime.startswith("text/"):
            try:
                out.append(_decode_b64url(data).decode("utf-8", errors="replace"))
            except Exception:
                pass
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(msg.get("payload", {}))
    return "\n".join(out)


async def wait_for_code(
    *,
    after: float,
    sender: str,
    timeout_s: int = 180,
    poll_interval_s: float = 5.0,
) -> str:
    """Block until a matching message arrives or timeout. Returns the 6-digit code."""
    svc = _service()
    deadline = time.time() + timeout_s
    after_epoch = int(after)
    query = f"from:{sender} after:{after_epoch}"

    while time.time() < deadline:
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=5
        ).execute()
        for ref in resp.get("messages", []) or []:
            msg = svc.users().messages().get(
                userId="me", id=ref["id"], format="full"
            ).execute()
            body = _extract_text(msg)
            m = _CODE_RE.search(body)
            if m:
                return m.group(1)
        await asyncio.sleep(poll_interval_s)

    raise TimeoutError(f"No 2FA code from {sender} within {timeout_s}s")


async def _cli() -> None:
    sender = os.environ.get("ALECTRA_2FA_SENDER", "noreply@alectrautilities.com")
    code = await wait_for_code(after=time.time() - 600, sender=sender, timeout_s=60)
    print(code)


if __name__ == "__main__":
    asyncio.run(_cli())
