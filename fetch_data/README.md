# fetch_data — auto-fetch GreenButton XML

Headless scraper that runs in **GitHub Actions** once a week, logs into the Alectra GreenButton portal, downloads the XML, and POSTs it to the Home Assistant integration's upload endpoint. The integration writes it into the watch folder; the existing watcher imports it.

Alectra's GreenButton portal does **not** require 2FA today — login = account name + account number + phone number. Gmail-OTP helpers (`gmail_2fa.py`, `setup_gmail_oauth.py`) are kept in this directory for the Enbridge fetcher (v2), which uses email-delivered codes.

Nothing in this directory ships to HA — HACS only reads `custom_components/canada_greenbutton/`. These scripts are repo-only.

## What runs where

| Piece | Where | When |
|---|---|---|
| `fetch_alectra.py` | GitHub Actions runner (Ubuntu) | Weekly cron + manual dispatch |
| `ha_upload.py` | Same runner | After XML download |
| `env_local.py` | Local debug only | Loads `.env.local` if present |
| `gmail_2fa.py`, `setup_gmail_oauth.py` | Reserved for Enbridge (v2) | Not wired today |
| `http_view.py` (in `custom_components/`) | Home Assistant | Always |

## Schedule

`0 11 * * 1` — Monday 11:00 UTC = 06:00 EST / 07:00 EDT. Adjust in `.github/workflows/fetch.yml`.

## One-time setup

### 1. Home Assistant long-lived access token

HA → profile (bottom-left avatar) → **Security** tab → **Long-Lived Access Tokens** → **Create Token**. Copy once.

> Token grants **full** HA API access. Keep in GitHub secrets only; rotate if leaked.

### 2. Public HA URL

GitHub Action needs to reach HA over HTTPS:
- Nabu Casa: `https://<your-id>.ui.nabu.casa`
- Or self-hosted reverse proxy (Caddy / Nginx / Cloudflare Tunnel) → HA `:8123`

### 3. Repo secrets

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `ALECTRA_ACCOUNT_NAME` | Account name shown on your Alectra bill (e.g. `JOHN DOE & JANE DOE`) |
| `ALECTRA_ACCOUNT_NUMBER` | Account number from the bill |
| `ALECTRA_PHONE` | Phone number on file with Alectra (10 digits, any format) |
| `ALECTRA_METER_ID` | Row identifier on the data page (e.g. `11025818`) — visible after login as the leftmost value in the data table row |
| `ALECTRA_LOGIN_URL` | *(optional)* override of the login URL |
| `ALECTRA_LOOKBACK_DAYS` | *(optional)* how far back From Date goes; default `400` |
| `HA_BASE_URL` | e.g. `https://abc123.ui.nabu.casa` |
| `HA_TOKEN` | Long-lived token from step 1 |

### 4. Trigger the first run

GitHub → **Actions → fetch → Run workflow**. Watch the log. On failure, the run page has a `diagnostics-<run_id>` artifact with screenshots and HTML — open the screenshot to see what broke (most often a selector drift on Alectra's login page).

## Local debug

```bash
cd fetch_data
cp .env.example .env.local        # then fill in the values; .env.local is gitignored
pip install -r requirements.txt
python -m playwright install chromium
python fetch_alectra.py
```

`.env.local` is loaded automatically. GitHub Actions secrets always win — env from the runner overrides anything in `.env.local`. Useful flags inside `.env.local`:

```
HEADLESS=0          # show the browser
SAVE_LOCAL=./out.xml
```

Re-record selectors when Alectra ships a UI change:
```bash
python -m playwright codegen https://alectrautilitiesgbportal.savagedata.com/
```
Paste new selectors into `fetch_alectra.py`.

## 60-day inactivity

GitHub auto-disables scheduled workflows after 60 days of zero repo commits. You'll get an email — click **Actions → fetch → Enable workflow**. Any normal commit in this repo also resets the timer.

## File map

```
fetch_data/
├── fetch_alectra.py      # main scraper (no 2FA)
├── ha_upload.py          # POST XML to HA with retries
├── env_local.py          # tiny .env loader, local debug only
├── .env.example          # copy to .env.local
├── .gitignore
├── gmail_2fa.py          # reserved for Enbridge (v2)
├── setup_gmail_oauth.py  # reserved for Enbridge (v2)
├── requirements.txt
└── README.md             # this file
.github/workflows/fetch.yml
```
