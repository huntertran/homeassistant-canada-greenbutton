"""Parse Enbridge Gas GreenButton XML → billing-periods JSON for Drive/visualizer.

Output shape:
    {
        "billingPeriods": [
            {
                "start":                  ISO-8601 UTC string,
                "end":                    ISO-8601 UTC string,
                "totalBillCAD":           float,
                "usageM3":                float,   # unadjusted m3
                "gasSupplyCAD":           float,
                "gasDeliveryVariableCAD": float,
                "gasTransportationCAD":   float,
                "gasCostAdjustmentCAD":   float,
                "customerChargeCAD":      float,
                "federalCarbonChargeCAD": float,
                "hstCAD":                 float,
            },
            ...
        ],
        "savedAt": ISO-8601 UTC string,   # added by caller
    }
"""
from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree as ET


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _iter_by_local(root: ET.Element, name: str):
    for el in root.iter():
        if _local_name(el.tag) == name:
            yield el


def _child_text(el: ET.Element, name: str) -> str | None:
    for c in list(el):
        if _local_name(c.tag) == name:
            return (c.text or "").strip() or None
    return None


def _child_int(el: ET.Element, name: str) -> int | None:
    t = _child_text(el, name)
    try:
        return int(t) if t is not None else None
    except ValueError:
        return None


def _iso_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _extract_billing(root: ET.Element) -> list[dict]:
    periods: list[dict] = []
    for s in _iter_by_local(root, "UsageSummary"):
        bp = next(_iter_by_local(s, "billingPeriod"), None)
        if bp is None:
            continue
        start_ts = _child_int(bp, "start")
        duration = _child_int(bp, "duration")
        if start_ts is None or duration is None:
            continue

        bill_last = _child_int(s, "billLastPeriod")

        usage_m3 = 0.0
        charges: dict[str, float] = {}

        for detail in _iter_by_local(s, "costAdditionalDetailLastPeriod"):
            note = (_child_text(detail, "note") or "").lower()
            amount_text = _child_text(detail, "amount")
            measurement = next(_iter_by_local(detail, "measurement"), None)

            multiplier = 0
            uom = None
            m_value = None
            if measurement is not None:
                multiplier = _child_int(measurement, "powerOfTenMultiplier") or 0
                uom = _child_int(measurement, "uom")
                m_value = _child_int(measurement, "value")

            amount_cad = (int(amount_text) * (10 ** multiplier)) if amount_text else None

            if "usage (unadjusted)" in note and uom == 167 and m_value is not None:
                usage_m3 = m_value * (10 ** multiplier)
            elif "hst" in note and amount_cad is not None:
                charges["hstCAD"] = amount_cad
            elif "gas supply charge" in note and amount_cad is not None:
                charges["gasSupplyCAD"] = amount_cad
            elif "gas delivery variable charge" in note and amount_cad is not None:
                charges["gasDeliveryVariableCAD"] = amount_cad
            elif "gas transportation charge" in note and amount_cad is not None:
                charges["gasTransportationCAD"] = amount_cad
            elif "gas cost adjustment" in note and "rate" not in note and amount_cad is not None:
                charges["gasCostAdjustmentCAD"] = amount_cad
            elif "gas federal carbon charge" in note and amount_cad is not None:
                charges["federalCarbonChargeCAD"] = amount_cad
            elif "customer charge" in note and amount_cad is not None:
                charges["customerChargeCAD"] = amount_cad
            elif "total gas charges" in note and amount_cad is not None:
                charges["totalBillCAD"] = amount_cad

        periods.append({
            "start": _iso_utc(start_ts),
            "end": _iso_utc(start_ts + duration),
            "totalBillCAD": charges.get("totalBillCAD", (bill_last or 0) * (10 ** -3)),
            "usageM3": usage_m3,
            "gasSupplyCAD": charges.get("gasSupplyCAD", 0.0),
            "gasDeliveryVariableCAD": charges.get("gasDeliveryVariableCAD", 0.0),
            "gasTransportationCAD": charges.get("gasTransportationCAD", 0.0),
            "gasCostAdjustmentCAD": charges.get("gasCostAdjustmentCAD", 0.0),
            "customerChargeCAD": charges.get("customerChargeCAD", 0.0),
            "federalCarbonChargeCAD": charges.get("federalCarbonChargeCAD", 0.0),
            "hstCAD": charges.get("hstCAD", 0.0),
        })

    periods.sort(key=lambda p: p["start"])
    return periods


def parse_xml(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    return {"billingPeriods": _extract_billing(root)}
