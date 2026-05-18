# Plan: Auto-fetch Alectra GreenButton XML — GitHub Action + Playwright, drops to HA

## Context

The Canada GreenButton HA integration imports GreenButton XML files dropped into a user-configured watch folder. Today the user manually downloads XML from Alectra MyAccount each billing cycle. Goal: unattended ingestion with no separate always-on machine and no Docker add-on.

Earlier iterations explored two dead ends:
- **Cron on the Pi.** Rejected: the Alectra portal is a Blazor Server app (`alectrautilitiesgbportal.savagedata.com`); the Download action travels over a SignalR WebSocket, not a clean form POST. Reverse-engineering hub frames inside HA Core is brittle and breaks on every Blazor redeploy.
- **Playwright inside HA Core.** Rejected: Chromium on HA OS / Raspberry Pi is unsupported and fragile.

New decision: **the scraper lives in a GitHub Actions workflow**, runs Playwright in a real Chromium on Ubuntu, fetches the 2FA code from Gmail using a refresh-token-only OAuth flow, downloads the XML, and POSTs it to a small HTTP endpoint registered by the HA integration. The integration's job collapses to "accept an authenticated upload, write it to the watch dir." The existing watcher / parser / store / statistics pipeline is unchanged.

Public repo → unlimited free Actions minutes. Private repo → 2000 min/month, more than enough for a daily 5-minute run. Default to **public** since the code has no embedded secrets (all secrets are in GitHub Actions encrypted secrets).

**60-day inactivity policy.** GitHub disables `schedule:` workflows after 60 days of zero repo activity. We do **not** ship a `keepalive.yml` (gray-area vs. GitHub Actions TOS clause about unrelated workflows). Instead: GitHub emails the repo owner when the workflow is disabled; user clicks **Actions → fetch → Enable workflow** to resume. Any normal commit (selector fix, README tweak) also resets the 60-day timer.

## Decisions established with the user

- HA is HA OS on a Raspberry Pi. No Docker add-on.
- **Scraper runs in GitHub Actions** (cron + Playwright + Gmail API). Public repo (free minutes; keep-alive needed to dodge 60-day inactivity disable).
- HA receives the XML via a new authenticated HTTP endpoint exposed by the integration: `POST /api/canada_greenbutton/upload` with the XML as the raw request body and a long-lived access token. Endpoint atomically writes to the configured `watch_dir`; the existing watcher does the rest.
- Gmail OAuth: one-time refresh-token issuance done locally by the user via `fetch_data/setup_gmail_oauth.py`. The refresh token + client ID + client secret then go into **GitHub Actions secrets**. The HA integration does **not** touch Gmail.
- Alectra first; Enbridge later (same shape — another script, same workflow).
- 2FA: email-based 6-digit code; no captcha today.
- Scheduling: GitHub Actions `schedule` cron in the workflow, not HA automations.

## How the pieces fit

```mermaid
flowchart LR
  CRON[GitHub Actions cron<br/>0 11 * * *  - 06:00 ET] --> WF[fetch.yml workflow]
  subgraph Runner["ubuntu-latest runner (ephemeral)"]
    WF --> PW[fetch_data/fetch_alectra.py<br/>Playwright + Chromium]
    PW -- "wait for 2FA mail" --> GM[Gmail API<br/>refresh-token auth]
    GM -- "6-digit code" --> PW
    PW -- "downloaded XML" --> POST[POST /api/canada_greenbutton/upload<br/>Bearer + raw XML body]
  end
  POST -- "over Nabu Casa /<br/>reverse-proxy URL" --> HA
  subgraph HA["Home Assistant (HA OS on Pi)"]
    HA --> VIEW[http_view.py<br/>HomeAssistantView]
    VIEW -- "atomic write" --> WD[(watch_dir)]
    WATCH[existing folder watcher<br/>__init__.py:103-122] -- "60s tick" --> WD
    WATCH --> PARSE[parser/detect.py] --> STORE[store.py _merge dedup] --> STATS[statistics.py]
  end
```

The watcher, parser, store, and statistics pipeline are **unchanged**. The integration gains exactly one new file (`http_view.py`) and a couple of lines in `__init__.py` to register the view.

## Approach

### 1. Repo layout (single repo, HACS-compatible)

```
repo-root/
├── custom_components/canada_greenbutton/
│   ├── ... (existing files, mostly unchanged)
│   ├── http_view.py        # NEW — HomeAssistantView for /api/canada_greenbutton/upload
│   ├── __init__.py         # MODIFIED — register the view in async_setup_entry
│   └── manifest.json       # unchanged
├── fetch_data/
│   ├── fetch_alectra.py
│   ├── setup_gmail_oauth.py    # one-time, user runs locally
│   ├── ha_upload.py            # shared helper: POST XML to HA with retries
│   ├── gmail_2fa.py            # shared helper: poll Gmail for 6-digit code
│   ├── requirements.txt
│   └── README.md
└── .github/workflows/
    └── fetch.yml               # cron + manual dispatch
```

HACS reads `custom_components/canada_greenbutton/`; everything outside that path is ignored by HACS but used by GitHub Actions. The integration's `manifest.json` is unchanged — no new Python deps inside HA.

### 2. `fetch_data/fetch_alectra.py` (the actual scraper)

Headed-mode-during-debug, headless-in-CI Playwright script. Pseudocode:

```python
async def run() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(accept_downloads=True)
        page = await ctx.new_page()

        await page.goto(LOGIN_URL)                       # alectrautilities.com login
        await page.fill('input[name="email"]', USER)
        await page.fill('input[name="password"]', PW)
        login_started = time.time()
        await page.click('button[type="submit"]')

        # 2FA branch — only if challenge page renders
        if await page.locator('input[name="otp"]').count():
            code = await gmail_2fa.wait_for_code(after=login_started, sender=ALECTRA_2FA_SENDER, timeout_s=180)
            await page.fill('input[name="otp"]', code)
            await page.click('button[type="submit"]')

        # Navigate to portal — SSO redirect chain to savagedata.com handled by browser
        await page.goto(DOWNLOAD_URL)                    # /DownloadMyData

        async with page.expect_download() as dl_info:
            await page.click('button:has-text("Download")')
        download = await dl_info.value
        path = await download.path()
        xml_bytes = Path(path).read_bytes()

        await ha_upload.post_xml(xml_bytes, source="alectra")
        return 0
```

Playwright handles Blazor/SignalR transparently — it's a real browser, so the file download (Pattern A or B) doesn't matter. `expect_download()` blocks until the browser commits a file, regardless of whether the URL was a real GET or a Blob-from-WebSocket.

Selectors (`button:has-text("Download")`, etc.) are placeholders — the user runs `playwright codegen https://alectrautilities.com/login` once and pastes the recorded selectors. No HAR capture needed.

### 3. `fetch_data/gmail_2fa.py` (refresh-token-only Gmail polling)

```python
def _service() -> Resource:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

async def wait_for_code(*, after: float, sender: str, timeout_s: int) -> str:
    svc = _service()
    deadline = time.time() + timeout_s
    after_epoch = int(after)
    while time.time() < deadline:
        resp = svc.users().messages().list(
            userId="me",
            q=f"from:{sender} after:{after_epoch}",
            maxResults=5,
        ).execute()
        for m in resp.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            body = _extract_text(msg)
            match = re.search(r"\b(\d{6})\b", body)
            if match:
                return match.group(1)
        await asyncio.sleep(5)
    raise TimeoutError("No 2FA code received in window")
```

`gmail.readonly` scope only — no mark-as-read, no inbox mutation. De-dupe by `after:<login_started_unix>` so old codes can't be picked up.

### 4. `fetch_data/setup_gmail_oauth.py` (one-time, runs on user's laptop)

Standard `InstalledAppFlow.from_client_secrets_file(...).run_local_server(port=0)` flow. Outputs:

```
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
```

User pastes those three values into **GitHub repo → Settings → Secrets and variables → Actions**. README walks through the GCP console steps (create project, enable Gmail API, create OAuth 2.0 **Desktop** app client — Desktop is correct here because the consent flow runs locally on the user's machine, not in HA).

### 5. `fetch_data/ha_upload.py` (POST XML to HA)

```python
def post_xml(xml: bytes, *, source: str) -> None:
    url = f"{os.environ['HA_BASE_URL'].rstrip('/')}/api/canada_greenbutton/upload"
    headers = {
        "Authorization": f"Bearer {os.environ['HA_TOKEN']}",
        "Content-Type": "application/xml",
        "X-Source": source,
    }
    for attempt in range(4):
        try:
            r = requests.post(url, data=xml, headers=headers, timeout=30)
            r.raise_for_status()
            return
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))   # 2, 4, 8s
```

`HA_BASE_URL` is either a Nabu Casa URL (`https://<id>.ui.nabu.casa`) or the user's reverse-proxy URL. `HA_TOKEN` is a long-lived access token from HA's profile page.

### 6. `.github/workflows/fetch.yml`

```yaml
name: fetch
on:
  schedule:
    - cron: "0 11 * * *"   # 06:00 America/Toronto in winter, 07:00 in DST — close enough
  workflow_dispatch:        # manual run button
jobs:
  alectra:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r fetch_data/requirements.txt
      - run: playwright install --with-deps chromium
      - run: python fetch_data/fetch_alectra.py
        env:
          ALECTRA_USERNAME: ${{ secrets.ALECTRA_USERNAME }}
          ALECTRA_PASSWORD: ${{ secrets.ALECTRA_PASSWORD }}
          ALECTRA_2FA_SENDER: ${{ secrets.ALECTRA_2FA_SENDER }}
          GMAIL_CLIENT_ID: ${{ secrets.GMAIL_CLIENT_ID }}
          GMAIL_CLIENT_SECRET: ${{ secrets.GMAIL_CLIENT_SECRET }}
          GMAIL_REFRESH_TOKEN: ${{ secrets.GMAIL_REFRESH_TOKEN }}
          HA_BASE_URL: ${{ secrets.HA_BASE_URL }}
          HA_TOKEN: ${{ secrets.HA_TOKEN }}
      - name: upload diagnostics on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: diagnostics-${{ github.run_id }}
          path: fetch_data/_diag/
```

On failure the script dumps screenshots + page HTML to `fetch_data/_diag/` so the workflow artifact lets the user see what broke without re-running.

### 7. HA-side: `custom_components/canada_greenbutton/http_view.py`

```python
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

class GreenButtonUploadView(HomeAssistantView):
    url = "/api/canada_greenbutton/upload"
    name = "api:canada_greenbutton:upload"
    requires_auth = True            # HA's standard bearer-token auth

    def __init__(self, hass: HomeAssistant, watch_dir: Path) -> None:
        self.hass = hass
        self.watch_dir = watch_dir

    async def post(self, request):
        source = request.headers.get("X-Source", "unknown")
        xml_bytes = await request.read()
        if not xml_bytes.lstrip().startswith(b"<"):
            return self.json_message("not XML", status_code=400)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = self.watch_dir / f"{source}_{ts}.xml"
        tmp = target.with_suffix(".xml.part")
        await self.hass.async_add_executor_job(tmp.write_bytes, xml_bytes)
        await self.hass.async_add_executor_job(tmp.rename, target)
        return self.json({"ok": True, "path": str(target)})
```

Registered once in `async_setup_entry`:

```python
from .http_view import GreenButtonUploadView
hass.http.register_view(GreenButtonUploadView(hass, Path(entry.options[CONF_WATCH_DIR])))
```

Auth: HA's `requires_auth = True` accepts the same long-lived access tokens used everywhere else in HA's REST API. No new auth scheme.

### Out of scope for v1
- Enbridge fetcher (v2: `fetch_data/fetch_enbridge.py` + extra job in `fetch.yml`).
- HA persistent notification on workflow failure (v2: GitHub Action can call `notify.persistent_notification` via REST when `if: failure()`).
- Captcha handling — none today.
- Self-hosted runner — public-repo cloud runner is free and sufficient.

## Files

**Create (in the repo, but outside `custom_components/`):**
- `fetch_data/fetch_alectra.py`
- `fetch_data/gmail_2fa.py`
- `fetch_data/ha_upload.py`
- `fetch_data/setup_gmail_oauth.py`
- `fetch_data/requirements.txt` — `playwright>=1.45`, `google-api-python-client>=2.100`, `google-auth-oauthlib>=1.2`, `requests>=2.31`
- `fetch_data/README.md` — secrets, GCP setup, local debug instructions
- `.github/workflows/fetch.yml`

**Create (inside the integration):**
- `custom_components/canada_greenbutton/http_view.py`

**Modify:**
- `custom_components/canada_greenbutton/__init__.py` — register `GreenButtonUploadView` in `async_setup_entry` (~line 97); no service teardown change needed (HA cleans up views on entry unload).
- `README.md` (repo root) — new "Auto-fetch via GitHub Actions" section linking to `fetch_data/README.md`.

**Do not touch:**
- `custom_components/canada_greenbutton/store.py` — `_merge` already handles overlap (lines 63-108).
- `custom_components/canada_greenbutton/parser/` — XML detection + parsing unchanged.
- `custom_components/canada_greenbutton/statistics.py` — unchanged.
- The folder watcher block in `__init__.py:100-123` — unchanged.
- `manifest.json` — no new HA-side Python deps.
- `config_flow.py` — no new options. (User configures auto-fetch via GitHub secrets, not HA UI.)

## Reused, do not duplicate

- Watcher: `__init__.py:103-122` already imports any XML the upload view drops. No code added on the import side.
- Source autodetect: `parser/detect.py:24` (`detect_source`) tags `alectra`.
- Dedup-merge: `store.py:63` (`_merge`) → repeat uploads of overlapping windows are safe.
- Auth: HA's built-in long-lived access tokens + `HomeAssistantView(requires_auth=True)`. No custom auth.

## Verification

1. **Local dry run** (no GH Action, no HA):
   - `python fetch_data/setup_gmail_oauth.py` → completes consent, prints three env vars.
   - Export creds + `HA_BASE_URL=http://localhost:8123` + token from a dev HA.
   - `playwright install chromium && python fetch_data/fetch_alectra.py` → XML lands in dev HA's watch dir.
   - Parser sees `~11 billing periods, ~6372 kWh total` (user's reference dataset).

2. **GitHub Action smoke test:**
   - Push branch, set all repo secrets (`ALECTRA_*`, `GMAIL_*`, `HA_*`).
   - **Actions → fetch → Run workflow** (manual dispatch).
   - Watch the run; on success, HA's watch dir shows `alectra_<ts>.xml` within ~5 min total.
   - Energy dashboard `canada_greenbutton:alectra_<account>_energy` shows new readings.

3. **Cron:**
   - Confirm `fetch.yml` cron line.
   - Day 2: scheduled run fires unattended.
   - After ~50 days of zero repo commits, watch for GitHub's "workflow disabled" email — click Enable to resume.

4. **Failure-mode checks:**
   - Bad Alectra password → workflow fails, diagnostics artifact contains screenshot of error page.
   - Revoked Gmail refresh token → script raises clearly; user re-runs `setup_gmail_oauth.py`.
   - HA unreachable → `ha_upload.py` retries 4× then fails the run.
   - Same-day re-run → `store._merge` produces no double-counted kWh.

## Risks / open items

- **HA must be reachable from the public internet.** Nabu Casa (`*.ui.nabu.casa`) works out of the box; self-hosted reverse proxy works if it terminates TLS and forwards to HA on 8123. If the user has neither, this approach doesn't work — but they almost certainly have one or the other if they're using HA seriously.
- **Long-lived access token blast radius.** A leaked HA token grants **full** HA API access, not just the upload endpoint. Mitigations to consider in v2: add a per-token allow-list / scope guard, or use a shared-secret header on the view instead of HA's bearer auth.
- **Public repo exposes selectors and the workflow logic, not secrets.** This is normal for open-source scrapers but worth naming. If Alectra adds anti-automation later, we adapt selectors; nothing in the repo lets a third party access *this* user's account.
- **GitHub cron lag.** Scheduled workflows can drift up to ~15 min under load. Acceptable for utility-bill scraping; not for real-time.
- **DST.** Cron is UTC. A single fixed UTC cron will run at 06:00 ET in winter and 07:00 ET in summer. Two crons (`0 11 * * *` for EST, `0 10 * * *` for EDT) would be tighter; not worth it.
- **Selector drift.** Alectra's login form HTML can change. `fetch.yml` runs daily, so the first failure surfaces within 24h; diagnostic screenshots in the artifact pinpoint the broken selector. Re-record with `playwright codegen`.
