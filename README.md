# Canada GreenButton — Home Assistant Integration

Import Canadian utility GreenButton XML (Alectra Electric + Enbridge Gas) into Home Assistant. Surfaces data via:
- Long-term statistics → built-in Energy dashboard
- Summary sensors with raw parsed data as attributes
- Custom Lovelace card with TOU stacked bars, hourly heatmap, year-over-year table, gas billing, and CSV export

Supports a generic ESPI fallback parser for other utilities.

---

## Install (HACS)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/huntertran/homeassistant-canada-greenbutton` as Integration
3. Install **Canada GreenButton**, restart Home Assistant
4. Settings → Devices & Services → Add Integration → **Canada GreenButton**

Optional during setup:
- **Watch folder** — XML files dropped here are auto-imported every 60s, then renamed to `.imported`
- **Push to long-term statistics** — enables Energy dashboard integration

## Install Lovelace card

Copy `custom_cards/canada-greenbutton-card/canada-greenbutton-card.js` to `config/www/`, then:

```yaml
# Settings → Dashboards → Resources
url: /local/canada-greenbutton-card.js
type: module
```

## Importing XML

Three options:

**A) Service call**
```yaml
service: canada_greenbutton.import_xml
data:
  path: /config/canada_greenbutton/alectra.xml
  source: auto  # or alectra / enbridge / generic
```

**B) Watch folder** — set in integration options; drop XML in that folder.

**C) UI** — re-run the config flow's options to update settings (file upload step can be wired through a service in subsequent versions).

## Clearing data

```yaml
service: canada_greenbutton.clear_data
data:
  source: alectra  # omit to clear all
```

## Energy dashboard wiring

After importing, go to **Settings → Dashboards → Energy**:
- *Electricity grid* → add `canada_greenbutton:alectra_<account>_energy`
- *Gas consumption* → add `canada_greenbutton:enbridge_<account>_gas`

Separate per-TOU streams are also published:
`canada_greenbutton:alectra_<account>_on_peak`, `_mid_peak`, `_off_peak`.

## Lovelace card

```yaml
type: custom:canada-greenbutton-card
entity: sensor.alectra_default_total_kwh_ytd
view: monthly_tou   # daily_tou | heatmap | yoy | billing | gas_usage | gas_billing
title: Electric usage
```

Views:
| view | source | description |
|---|---|---|
| `monthly_tou` | Alectra | Stacked bar of off/mid/on-peak kWh per month + CSV export |
| `daily_tou` | Alectra | Stacked bar of TOU per day, month-tab selector + CSV export |
| `heatmap` | Alectra | 7×24 mean kWh heatmap (day-of-week × hour) |
| `yoy` | Alectra | Year-over-year usage table with Δ |
| `billing` | Alectra | Per-period billing breakdown table |
| `gas_usage` | Enbridge | Seasonal bars (m³) + bill line |
| `gas_billing` | Enbridge | Billing breakdown table |

## Development: deploy script

For iterating against a live HA instance over SSH/SCP, use `scripts/deploy.ps1` (PowerShell, Windows). Requires OpenSSH client (built into Windows 10+).

### One-time SSH key setup

```powershell
ssh-keygen -t ed25519
# Paste contents of %USERPROFILE%\.ssh\id_ed25519.pub into the HA host's /root/.ssh/authorized_keys
# (or use ssh-copy-id from WSL / Git Bash)
```

### Avoid retyping passphrase — ssh-agent setup

Without this, each `scp` / `ssh` call in `deploy.ps1` prompts for the key passphrase (5+ times per run).

**1. Install OpenSSH client (if missing):**

```powershell
# Admin PowerShell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

Verify: `Get-Service ssh-agent` should list the service.

**2. Enable + start the agent service:**

```powershell
# Admin PowerShell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
```

Verify:
```powershell
Get-Service ssh-agent     # Status should be Running
```

**3. Auto-load key on shell startup** — append to PowerShell profile:

```powershell
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Path $PROFILE -Force }

@'

# Auto-load SSH key into ssh-agent (prompts once per reboot)
if (Get-Service ssh-agent -ErrorAction SilentlyContinue) {
    if (-not (ssh-add -l 2>$null | Select-String "id_ed25519")) {
        ssh-add $env:USERPROFILE\.ssh\id_ed25519
    }
}
'@ | Add-Content -Path $PROFILE
```

**4. Test:**

```powershell
ssh-add -D                # clear cached keys
# Open a NEW PowerShell window — should prompt passphrase ONCE
ssh-add -l                # confirms key loaded
```

Subsequent `deploy.ps1` runs proceed without prompts until reboot. If you rotate to a different key file, update both `id_ed25519` references in the profile block.

**Troubleshooting:**
- `ssh-add -D` → "Error connecting to agent: No such file or directory" → agent service not running. Re-run step 2.
- VS Code terminal still prompts → run `ssh-add $env:USERPROFILE\.ssh\id_ed25519` once inside it; same agent service, just needs handshake.

### Usage

```powershell
cd D:\Projects\homeassistant-canada-greenbutton
.\scripts\deploy.ps1
```

The script is interactive — it prompts for each option with a sensible default in brackets. Press Enter to accept the default, or type a new value.

```
=== Canada GreenButton — Deploy ===
HA host or IP [192.168.x.x]:
SSH user [root]:
SSH port [22]:
Remote config dir [/config]:
Restart HA after deploy? (y/n) [y]:
Copy sample XMLs from green-button-visualizer? (y/n) [n]:
```

A summary is shown before any remote action; confirm with `y` to proceed.

**Common flows:**
- **Python change** → accept all defaults (restart = y).
- **Card-only edit** → answer `n` to "Restart HA" (just hard-refresh browser).
- **First deploy on a fresh HA** → answer `y` to "Copy sample XMLs" to ship Alectra + Enbridge test data.

### What the script does

1. `mkdir -p` remote `/config/custom_components/`, `/config/www/`, `/config/canada_greenbutton/`
2. `rm -rf` old `custom_components/canada_greenbutton/` (avoids stale `.py` after renames/deletes)
3. `scp -r` integration → `/config/custom_components/canada_greenbutton/`
4. `scp` card → `/config/www/canada-greenbutton-card.js`
5. Optional: `scp` sample XMLs into `/config/canada_greenbutton/`
6. `ha core restart` (HAOS / Supervised) — falls back to `systemctl` or prints manual instruction

### Iteration workflow

- **Python change** → `.\scripts\deploy.ps1` → wait ~30s for restart.
- **JS card change** → `.\scripts\deploy.ps1 -SkipRestart` → Ctrl+Shift+R in browser.

### Manual one-liner alternative

If you don't want the script:

```powershell
scp -r .\homeassistant-canada-greenbutton\custom_components\canada_greenbutton root@192.168.x.x:/config/custom_components/
scp .\homeassistant-canada-greenbutton\custom_cards\canada-greenbutton-card\canada-greenbutton-card.js root@192.168.x.x:/config/www/
scp .\data_folder\*.xml root@192.168.x.x:/config/canada_greenbutton/
ssh root@192.168.x.x "ha core restart"
```

---

## Data sources & coverage

Mirrors the visualizations in [canada-greenbutton](https://github.com/huntertran/canada-greenbutton). Google Drive sync is omitted — HA owns persistence.

## License

MIT
