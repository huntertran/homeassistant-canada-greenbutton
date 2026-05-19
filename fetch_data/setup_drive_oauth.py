"""One-time helper to obtain a Google Drive refresh_token.

Run this **once on your local machine** to get a long-lived
refresh_token for the visualizer's OAuth client. Store the printed
refresh_token (and your client_secret) as GitHub Actions secrets so the
weekly fetch workflow can write to the appDataFolder on your behalf.

Usage:
    cd fetch_data
    pip install -r requirements.txt
    GDRIVE_CLIENT_ID=...apps.googleusercontent.com \
    GDRIVE_CLIENT_SECRET=GOCSPX-... \
    python setup_drive_oauth.py

What happens:
    1. A small local HTTP server starts on http://localhost:8765/.
    2. Your default browser opens to Google's consent screen.
    3. You sign in with the SAME Google account you use in the
       visualizer (appDataFolder is per-user-per-client).
    4. Google redirects back to localhost; this script captures the
       auth code, exchanges it for tokens, and prints the refresh_token.

Prerequisites (one-time GCP Console work):
    - In the visualizer's OAuth client (Credentials → OAuth 2.0 Client
      IDs → the "Web application" client), add an Authorized redirect
      URI:  http://localhost:8765/
    - Make sure the OAuth consent screen has scope
      ``https://www.googleapis.com/auth/drive.appdata`` enabled and
      your Google account is listed as a Test user (or the app is
      Published).
"""
from __future__ import annotations

import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

REDIRECT = "http://localhost:8765/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.appdata"


class _Handler(BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):  # noqa: N802
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _Handler.captured.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>OK \xe2\x80\x94 you can close this tab.</h2></body></html>"
        )

    def log_message(self, *_a, **_kw):  # silence access log
        pass


def main() -> int:
    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET first.", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(16)
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print(f"Opening browser:\n  {url}\n")
    webbrowser.open(url)

    server = HTTPServer(("localhost", 8765), _Handler)
    while "code" not in _Handler.captured and "error" not in _Handler.captured:
        server.handle_request()
    server.server_close()

    if "error" in _Handler.captured:
        print(f"OAuth error: {_Handler.captured['error']}", file=sys.stderr)
        return 1
    if _Handler.captured.get("state") != state:
        print("State mismatch — aborting.", file=sys.stderr)
        return 1

    code = _Handler.captured["code"]
    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        print(
            "No refresh_token returned. Revoke prior consent at "
            "https://myaccount.google.com/permissions and rerun.",
            file=sys.stderr,
        )
        print(tokens, file=sys.stderr)
        return 1

    print("\n=== SAVE THESE AS GITHUB SECRETS ===")
    print(f"GDRIVE_CLIENT_ID     = {client_id}")
    print(f"GDRIVE_CLIENT_SECRET = {client_secret}")
    print(f"GDRIVE_REFRESH_TOKEN = {refresh}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
