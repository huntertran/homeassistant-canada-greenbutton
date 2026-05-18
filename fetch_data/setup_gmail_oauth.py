"""One-time local helper to mint a Gmail OAuth refresh token.

Run on your own machine (not in CI). Requirements:
    - A Google Cloud project with the Gmail API enabled.
    - An OAuth 2.0 Client ID of type **Desktop app**.
    - Download the client JSON and pass its path as the only argument.

Usage:
    python setup_gmail_oauth.py path/to/oauth_client.json

Prints three values to paste into GitHub Actions repo secrets:
    GMAIL_CLIENT_ID
    GMAIL_CLIENT_SECRET
    GMAIL_REFRESH_TOKEN
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    client_path = Path(sys.argv[1])
    if not client_path.is_file():
        print(f"client JSON not found: {client_path}", file=sys.stderr)
        return 2

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print(
            "No refresh_token returned. Revoke any prior consent and rerun with "
            "prompt=consent (already set).",
            file=sys.stderr,
        )
        return 1

    client = json.loads(client_path.read_text())
    installed = client.get("installed") or client.get("web") or {}
    client_id = installed.get("client_id", "")
    client_secret = installed.get("client_secret", "")

    print("\n# Paste these into GitHub repo → Settings → Secrets and variables → Actions")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
