# Google Drive Sync Setup

The weekly Alectra fetch can additionally write a parsed JSON payload
into the [canada-greenbutton](https://huntertran.github.io/canada-greenbutton/) app's per-user
`appDataFolder` on Google Drive. The visualizer auto-loads this on
sign-in.

## Why these constraints

- `appDataFolder` is a Drive special space, **scoped per user per
  OAuth client_id**. A different client_id sees a different folder.
- Service accounts cannot access a user's `appDataFolder`. Only user
  OAuth credentials work.
- Therefore the workflow must use the **same OAuth client_id** the
  visualizer ships with, plus a long-lived **refresh token** obtained
  by you once via local browser consent.

## Prerequisites

1. Google Cloud Console → APIs & Services → **Credentials**.
2. Open the visualizer's existing OAuth 2.0 Client ID (Web
   application). Its client_id is the one in
   `google-drive.config.ts`.
3. **Authorized redirect URIs** → add: `http://localhost:8765/`.
4. Copy the **Client secret** (`GOCSPX-...`).
5. **OAuth consent screen** → make sure
   `https://www.googleapis.com/auth/drive.appdata` is in the list of
   scopes. If the app is in "Testing" mode, add your Google account as
   a **Test user**.

## One-time: obtain refresh_token locally

```powershell
cd fetch_data
pip install -r requirements.txt
$env:GDRIVE_CLIENT_ID = "<client_id from visualizer config>"
$env:GDRIVE_CLIENT_SECRET = "<client_secret from GCP>"
python setup_drive_oauth.py
```

A browser tab opens → sign in with the same Google account you use
in the visualizer → grant consent. The script prints three values.

If no `refresh_token` is returned: visit
<https://myaccount.google.com/permissions>, remove the prior grant
for this app, then rerun.

## GitHub Secrets to set

Repo → Settings → Secrets and variables → Actions → **New repository
secret** for each:

| Secret name           | Source                                     |
| --------------------- | ------------------------------------------ |
| `GDRIVE_CLIENT_ID`    | from visualizer's `google-drive.config.ts` |
| `GDRIVE_CLIENT_SECRET`| from GCP Console (OAuth client)            |
| `GDRIVE_REFRESH_TOKEN`| printed by `setup_drive_oauth.py`          |

Optional **variable** (not a secret), only if you want to override the
default filename `alectra-data.json`:

| Variable name      | Default              |
| ------------------ | -------------------- |
| `GDRIVE_FILE_NAME` | `alectra-data.json`  |

## How the fetch wires it together

`fetch_data/fetch_alectra.py`:

1. Downloads the GreenButton XML from Alectra's portal.
2. Posts XML to Home Assistant (unchanged).
3. If `GDRIVE_REFRESH_TOKEN` is set:
   - Parses XML in-process via `alectra_parser.parse_xml`
     (Python port of the visualizer's `AlectraParserService`).
   - Stamps `savedAt` (ISO-8601 UTC).
   - Calls `drive_upload.upload_json` → trades refresh_token for an
     access token → overwrites (or creates) the rolling
     `alectra-data.json` inside `appDataFolder` on Drive.
4. Drive failures are logged but **non-fatal** (HA upload already
   succeeded).

## Local testing (optional)

You can dry-run the Drive upload locally without invoking the full
Playwright scrape: open a Python REPL inside `fetch_data/`, load some
XML bytes, then:

```python
import os, alectra_parser, drive_upload
from datetime import datetime, timezone

os.environ.update({
    "GDRIVE_CLIENT_ID": "...",
    "GDRIVE_CLIENT_SECRET": "...",
    "GDRIVE_REFRESH_TOKEN": "...",
})
xml = open("sample.xml", "rb").read()
payload = alectra_parser.parse_xml(xml)
payload["savedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
print(drive_upload.upload_json(payload))
```

## Visualizer behavior on load

`green-button-visualizer/src/app/features/alectra-utilities/alectra-utilities.component.ts`:

- On sign-in, `tryLoadFromDrive()` fetches `alectra-data.json` from
  `appDataFolder`, compares `savedAt` with localStorage, and uses the
  newer copy. CI-pushed data therefore wins over stale local data on
  the next browser session.

## Two-year rollover (future work)

Alectra retains ~2 years of usage data. When the rolling window
approaches that limit, write a second JSON file (e.g.,
`alectra-data-2027.json`) and have the visualizer concatenate. This
logic lives in the visualizer repo, not here.
