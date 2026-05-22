"""Python port of AlectraParserService from green-button-visualizer.

Produces the JSON shape the visualizer's loadAppData expects:
    {
        "billingPeriods": [...],
        "monthlyTou":     [...],
        "dailySummaries": [...],
        "heatmapGrid":    {cells: number[7][24], max: number},
        "hourlyReadings": [{ts, kwh, tou}],   # raw, used for cross-run merge
        "savedAt":        ISO-8601 timestamp,
    }

``hourlyReadings`` is the source of truth across runs.  ``drive_upload``
merges that array by ``ts``, then re-runs :func:`aggregate_hourly` so the
aggregate fields stay consistent.

Dates are emitted as ISO-8601 UTC strings — the visualizer rehydrates
with ``new Date(...)`` which accepts that format.

Local-time fields (month, hour, day-of-week) are computed in the
``America/Toronto`` timezone so the output matches what the visualizer
produces when a Toronto user loads the same XML in the browser.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Iterator
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Toronto")

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _iter_by_local(root: ET.Element, name: str) -> Iterator[ET.Element]:
    for el in root.iter():
        if _local_name(el.tag) == name:
            yield el


def _first_by_local(root: ET.Element, name: str) -> ET.Element | None:
    return next(_iter_by_local(root, name), None)


def _direct_children_by_local(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in list(el) if _local_name(c.tag) == name]


def _child_text(el: ET.Element, name: str) -> str | None:
    for c in list(el):
        if _local_name(c.tag) == name:
            return (c.text or "").strip() or None
    return None


def _child_int(el: ET.Element, name: str) -> int | None:
    t = _child_text(el, name)
    if t is None:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def _ts_to_local(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(LOCAL_TZ)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _label_short(dt: datetime) -> str:
    return f"{MONTH_ABBR[dt.month - 1]} {dt.strftime('%y')}"


def _extract_hourly_readings(root: ET.Element) -> list[dict]:
    """Return list of {ts, kwh, tou} for every 3600s IntervalReading.

    ``ts`` is the UNIX epoch second of the reading's start time. Acts as
    the merge key across runs.
    """
    reading_multiplier = 0
    for entry in _iter_by_local(root, "entry"):
        rt = _first_by_local(entry, "ReadingType")
        if rt is None:
            continue
        if _child_int(rt, "intervalLength") != 3600:
            continue
        m = _child_int(rt, "powerOfTenMultiplier")
        if m is not None:
            reading_multiplier = m
            break
    to_kwh = (10 ** reading_multiplier) / 1000

    readings: list[dict] = []
    for entry in _iter_by_local(root, "entry"):
        block = _first_by_local(entry, "IntervalBlock")
        if block is None:
            continue
        for r in _iter_by_local(block, "IntervalReading"):
            tp = _first_by_local(r, "timePeriod")
            if tp is None or _child_int(tp, "duration") != 3600:
                continue
            start_ts = _child_int(tp, "start")
            value = _child_int(r, "value")
            tou = _child_int(r, "tou")
            if start_ts is None or value is None or tou is None:
                continue
            readings.append({
                "ts": start_ts,
                "kwh": value * to_kwh,
                "tou": tou,
            })
    return readings


def aggregate_hourly(
    readings: Iterable[dict],
) -> tuple[list[dict], list[dict], dict]:
    """Recompute monthlyTou + dailySummaries + heatmapGrid from raw hourly.

    Pure function: same inputs → same outputs. Called by parser on the
    fresh XML payload and by the uploader on the merged hourly list.
    """
    month_map: dict[str, dict] = {}
    day_map: dict[str, dict] = {}
    heat_raw = [[{"total": 0.0, "count": 0} for _ in range(24)] for _ in range(7)]

    for r in readings:
        start_ts = r["ts"]
        kwh = r["kwh"]
        tou = r["tou"]
        dt = _ts_to_local(start_ts)
        year = dt.year
        month0 = dt.month - 1
        hour = dt.hour
        dow = (dt.weekday() + 1) % 7  # JS getDay(): Sun=0..Sat=6

        month_key = f"{year}-{month0:02d}"
        me = month_map.get(month_key)
        if me is None:
            me = {
                "label": _label_short(dt),
                "year": year,
                "month": month0,
                "offPeakKwh": 0.0,
                "midPeakKwh": 0.0,
                "onPeakKwh": 0.0,
                "totalKwh": 0.0,
            }
            month_map[month_key] = me
        if tou == 3:
            me["offPeakKwh"] += kwh
        elif tou == 2:
            me["midPeakKwh"] += kwh
        elif tou == 1:
            me["onPeakKwh"] += kwh
        me["totalKwh"] += kwh

        day_key = f"{year}-{dt.month:02d}-{dt.day:02d}"
        de = day_map.get(day_key)
        if de is None:
            midnight = datetime(year, dt.month, dt.day, tzinfo=LOCAL_TZ)
            de = {
                "date": _iso_utc(midnight),
                "dateKey": day_key,
                "kwh": 0.0,
                "onPeakKwh": 0.0,
                "midPeakKwh": 0.0,
                "offPeakKwh": 0.0,
            }
            day_map[day_key] = de
        de["kwh"] += kwh
        if tou == 1:
            de["onPeakKwh"] += kwh
        elif tou == 2:
            de["midPeakKwh"] += kwh
        elif tou == 3:
            de["offPeakKwh"] += kwh

        cell = heat_raw[dow][hour]
        cell["total"] += kwh
        cell["count"] += 1

    cells = [
        [
            (heat_raw[d][h]["total"] / heat_raw[d][h]["count"])
            if heat_raw[d][h]["count"] > 0 else 0.0
            for h in range(24)
        ]
        for d in range(7)
    ]
    heat_max = max((v for row in cells for v in row), default=0.0)

    monthly_tou = sorted(
        month_map.values(),
        key=lambda m: (m["year"], m["month"]),
    )
    daily = sorted(day_map.values(), key=lambda d: d["dateKey"])

    return monthly_tou, daily, {"cells": cells, "max": heat_max}


def _extract_billing(root: ET.Element) -> list[dict]:
    periods: list[dict] = []
    for s in _iter_by_local(root, "UsageSummary"):
        bp = _first_by_local(s, "billingPeriod")
        if bp is None:
            continue
        start_ts = _child_int(bp, "start")
        duration = _child_int(bp, "duration")
        bill_last = _child_int(s, "billLastPeriod")
        if start_ts is None or duration is None:
            continue

        delivery = regulatory = hst = rebate = 0.0
        usage_kwh = 0.0

        for charge in _direct_children_by_local(s, "costAdditionalDetailLastPeriod"):
            note = (_child_text(charge, "note") or "")
            amount_text = _child_text(charge, "amount")
            measurement = _first_by_local(charge, "measurement")
            multiplier = (
                _child_int(measurement, "powerOfTenMultiplier") or 0
                if measurement is not None else 0
            )
            uom = _child_int(measurement, "uom") if measurement is not None else None
            measurement_value = (
                _child_int(measurement, "value") if measurement is not None else None
            )
            amount_cad = (int(amount_text) * (10 ** multiplier)) if amount_text else 0.0
            nl = note.lower()
            if "delivery charge" in nl:
                delivery = amount_cad
            elif "regulatory charge" in nl:
                regulatory = amount_cad
            elif "hst" in nl:
                hst = amount_cad
            elif "ontario electricity rebate" in nl:
                rebate = amount_cad
            if "usage (unadjusted)" in nl and uom == 72 and measurement_value is not None:
                usage_kwh = measurement_value * (10 ** multiplier)

        periods.append({
            "start": _iso_utc(_ts_to_local(start_ts)),
            "end": _iso_utc(_ts_to_local(start_ts + duration)),
            "totalBillCAD": (bill_last or 0) / 1000,
            "usageKwh": usage_kwh,
            "deliveryCAD": delivery,
            "regulatoryCAD": regulatory,
            "hstCAD": hst,
            "ontarioRebateCAD": rebate,
        })

    periods.sort(key=lambda p: p["start"])
    return periods


def parse_xml(xml_bytes: bytes) -> dict:
    """Parse Alectra GreenButton XML → visualizer-ready dict.

    Includes raw ``hourlyReadings`` so the uploader can merge across runs.
    Caller appends ``savedAt`` before uploading to Drive.
    """
    root = ET.fromstring(xml_bytes)
    hourly = _extract_hourly_readings(root)
    monthly_tou, daily, heatmap = aggregate_hourly(hourly)
    return {
        "billingPeriods": _extract_billing(root),
        "monthlyTou": monthly_tou,
        "dailySummaries": daily,
        "heatmapGrid": heatmap,
        "hourlyReadings": hourly,
    }
