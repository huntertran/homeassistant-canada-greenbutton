"""POST a GreenButton XML blob to the HA integration's upload endpoint."""
from __future__ import annotations

import os
import time

import requests


def post_xml(xml: bytes, *, source: str, base_url: str | None = None, token: str | None = None) -> dict:
    base = (base_url or os.environ["HA_BASE_URL"]).rstrip("/")
    auth = token or os.environ["HA_TOKEN"]
    url = f"{base}/api/canada_greenbutton/upload"
    headers = {
        "Authorization": f"Bearer {auth}",
        "Content-Type": "application/xml",
        "X-Source": source,
    }
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            # (connect, read): fail fast when the host is unroutable, but give
            # HA time to chew through a large XML payload.
            r = requests.post(url, data=xml, headers=headers, timeout=(10, 120))
            r.raise_for_status()
            return r.json()
        except requests.RequestException as err:
            last_err = err
            if attempt == 3:
                break
            time.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
    raise RuntimeError(f"HA upload failed after retries: {last_err}")
