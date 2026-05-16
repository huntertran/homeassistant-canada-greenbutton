# Canada GreenButton Card

Lovelace card for the Canada GreenButton integration. Reads parsed datasets from sensor `raw_data` attributes.

## Install

Copy `canada-greenbutton-card.js` to `<config>/www/`, then add a Lovelace resource:
- URL: `/local/canada-greenbutton-card.js`
- Type: `module`

## Usage

```yaml
type: custom:canada-greenbutton-card
entity: sensor.alectra_default_total_kwh_ytd
view: monthly_tou
title: Electric usage
```

Available views:

| view | description |
|---|---|
| `monthly_tou` | Stacked bar of off/mid/on-peak kWh per month + CSV export |
| `daily_tou` | Stacked bar per day, month-tab selector + CSV export |
| `heatmap` | 7×24 mean kWh heatmap (DoW × hour) |
| `yoy` | Year-over-year monthly usage table with Δ |
| `billing` | Per-period billing breakdown |
| `gas_usage` | Seasonal m³ bars + bill line |
| `gas_billing` | Gas billing breakdown table |

Chart.js is loaded from `cdn.jsdelivr.net` on first render.
