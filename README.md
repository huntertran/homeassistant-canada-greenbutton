# Canada GreenButton — Home Assistant Integration

Import Canadian utility GreenButton XML (Alectra Electric TOU + Enbridge Gas) into Home Assistant. Surfaces data via:
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

## Data sources & coverage

Mirrors the visualizations in [green-button-visualizer](https://github.com/huntertran/green-button-visualizer). Google Drive sync is omitted — HA owns persistence.

## License

MIT
