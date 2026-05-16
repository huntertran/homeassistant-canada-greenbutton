"""Alectra Electric (ESPI + TOU) parser. Port of alectra-parser.service.ts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

from ..const import (
    CHARGE_DELIVERY,
    CHARGE_HST,
    CHARGE_ONTARIO_REBATE,
    CHARGE_REGULATORY,
    HOUR_S,
    NOTE_USAGE_UNADJUSTED,
    TOU_MID,
    TOU_OFF,
    TOU_ON,
    UOM_KWH,
)
from .common import (
    all_by_local_name,
    by_local_name,
    child_int,
    child_text,
    direct_children,
    iter_local,
)


@dataclass
class ElectricBillingPeriod:
    start: str  # ISO datetime
    end: str
    total_bill_cad: float
    usage_kwh: float
    delivery_cad: float
    regulatory_cad: float
    hst_cad: float
    ontario_rebate_cad: float


@dataclass
class MonthlyTouSummary:
    label: str  # YYYY-MM
    year: int
    month: int  # 1-12
    off_peak_kwh: float
    mid_peak_kwh: float
    on_peak_kwh: float
    total_kwh: float


@dataclass
class DailySummary:
    date_key: str  # YYYY-MM-DD
    kwh: float
    on_peak_kwh: float
    mid_peak_kwh: float
    off_peak_kwh: float


@dataclass
class HeatmapGrid:
    cells: list[list[float]]  # [dow 0=Mon..6=Sun][hour 0..23]
    max: float


@dataclass
class AlectraData:
    account_id: str = ""
    customer_name: str = ""
    address: str = ""
    billing_periods: list[ElectricBillingPeriod] = field(default_factory=list)
    monthly_tou: list[MonthlyTouSummary] = field(default_factory=list)
    daily_summaries: list[DailySummary] = field(default_factory=list)
    heatmap: HeatmapGrid = field(default_factory=lambda: HeatmapGrid(cells=[], max=0.0))
    hourly_readings: list[tuple[int, float, int]] = field(default_factory=list)
    """List of (epoch_seconds, kwh, tou). Kept for statistics push."""

    def to_dict(self) -> dict:
        return asdict(self)


class AlectraParser:
    def parse(self, path: str) -> AlectraData:
        tree = ET.parse(path)
        return self.parse_root(tree.getroot())

    def parse_string(self, xml: str) -> AlectraData:
        return self.parse_root(ET.fromstring(xml))

    def parse_root(self, root: ET.Element) -> AlectraData:
        data = AlectraData()
        self._extract_customer(root, data)
        self._extract_hourly(root, data)
        self._extract_billing(root, data)
        return data

    # --- customer ------------------------------------------------------------
    def _extract_customer(self, root: ET.Element, data: AlectraData) -> None:
        cust = by_local_name(root, "Customer")
        if cust is not None:
            data.customer_name = child_text(cust, "customerName") or ""
            data.address = child_text(cust, "addressGeneral") or ""
        acct = by_local_name(root, "CustomerAccount")
        if acct is not None:
            data.account_id = child_text(acct, "accountId") or ""

    # --- hourly --------------------------------------------------------------
    def _extract_hourly(self, root: ET.Element, data: AlectraData) -> None:
        # Discover multiplier from hourly ReadingType
        multiplier = 0
        for rt in iter_local(root, "ReadingType"):
            interval = child_int(rt, "intervalLength")
            if interval == HOUR_S:
                m = child_int(rt, "powerOfTenMultiplier")
                if m is not None:
                    multiplier = m
                break
        to_kwh = (10 ** multiplier) / 1000.0

        monthly: dict[str, MonthlyTouSummary] = {}
        daily: dict[str, DailySummary] = {}
        heat_sum = [[0.0] * 24 for _ in range(7)]
        heat_cnt = [[0] * 24 for _ in range(7)]

        for reading in iter_local(root, "IntervalReading"):
            tp = by_local_name(reading, "timePeriod")
            duration = child_int(tp, "duration") if tp is not None else None
            if duration != HOUR_S:
                continue
            start_ts = child_int(tp, "start") if tp is not None else None
            value = child_int(reading, "value")
            tou: Optional[int] = None
            quality = by_local_name(reading, "ReadingQuality")
            # TOU comes from sibling <tou> child of IntervalReading per Alectra format
            tou_text = child_text(reading, "tou")
            if tou_text is not None:
                try:
                    tou = int(tou_text)
                except ValueError:
                    tou = None
            if start_ts is None or value is None or tou is None:
                continue

            kwh = value * to_kwh
            dt = datetime.fromtimestamp(start_ts, tz=timezone.utc).astimezone()
            data.hourly_readings.append((start_ts, kwh, tou))

            # Monthly
            mkey = f"{dt.year:04d}-{dt.month:02d}"
            m = monthly.get(mkey)
            if m is None:
                m = MonthlyTouSummary(
                    label=mkey, year=dt.year, month=dt.month,
                    off_peak_kwh=0.0, mid_peak_kwh=0.0, on_peak_kwh=0.0, total_kwh=0.0,
                )
                monthly[mkey] = m
            self._add_tou(m, tou, kwh)
            m.total_kwh += kwh

            # Daily
            dkey = dt.strftime("%Y-%m-%d")
            d = daily.get(dkey)
            if d is None:
                d = DailySummary(date_key=dkey, kwh=0.0,
                                 on_peak_kwh=0.0, mid_peak_kwh=0.0, off_peak_kwh=0.0)
                daily[dkey] = d
            self._add_tou(d, tou, kwh)
            d.kwh += kwh

            # Heatmap (Python weekday: Mon=0..Sun=6)
            heat_sum[dt.weekday()][dt.hour] += kwh
            heat_cnt[dt.weekday()][dt.hour] += 1

        # finalize
        data.monthly_tou = sorted(monthly.values(), key=lambda x: (x.year, x.month))
        data.daily_summaries = sorted(daily.values(), key=lambda x: x.date_key)
        cells = [
            [heat_sum[d][h] / heat_cnt[d][h] if heat_cnt[d][h] else 0.0
             for h in range(24)] for d in range(7)
        ]
        mx = max((c for row in cells for c in row), default=0.0)
        data.heatmap = HeatmapGrid(cells=cells, max=mx)

    @staticmethod
    def _add_tou(target, tou: int, kwh: float) -> None:
        if tou == TOU_ON:
            target.on_peak_kwh += kwh
        elif tou == TOU_MID:
            target.mid_peak_kwh += kwh
        elif tou == TOU_OFF:
            target.off_peak_kwh += kwh

    # --- billing -------------------------------------------------------------
    def _extract_billing(self, root: ET.Element, data: AlectraData) -> None:
        periods: list[ElectricBillingPeriod] = []
        for summary in iter_local(root, "UsageSummary"):
            bp = by_local_name(summary, "billingPeriod")
            if bp is None:
                continue
            start_ts = child_int(bp, "start")
            duration = child_int(bp, "duration") or 0
            if start_ts is None:
                continue
            bill_cents = child_int(summary, "billLastPeriod") or 0

            delivery = regulatory = hst = rebate = 0.0
            usage_kwh = 0.0
            for detail in direct_children(summary, "costAdditionalDetailLastPeriod"):
                note = (child_text(detail, "note") or "").lower()
                amount_text = child_text(detail, "amount")
                measurement = by_local_name(detail, "measurement")
                uom = child_int(measurement, "uom") if measurement is not None else None
                m_value = child_int(measurement, "value") if measurement is not None else None
                m_mult = child_int(measurement, "powerOfTenMultiplier") if measurement is not None else 0
                m_mult = m_mult or 0

                amount_cad = 0.0
                if amount_text is not None:
                    try:
                        amount_cad = int(amount_text) * (10 ** m_mult)
                    except ValueError:
                        amount_cad = 0.0

                if CHARGE_DELIVERY in note:
                    delivery = amount_cad
                elif CHARGE_REGULATORY in note:
                    regulatory = amount_cad
                elif CHARGE_ONTARIO_REBATE in note:
                    rebate = amount_cad
                elif CHARGE_HST in note:
                    hst = amount_cad

                if NOTE_USAGE_UNADJUSTED in note and uom == UOM_KWH and m_value is not None:
                    usage_kwh = m_value * (10 ** m_mult)

            end_ts = start_ts + duration
            periods.append(ElectricBillingPeriod(
                start=datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
                end=datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(),
                total_bill_cad=bill_cents / 1000.0,
                usage_kwh=usage_kwh,
                delivery_cad=delivery,
                regulatory_cad=regulatory,
                hst_cad=hst,
                ontario_rebate_cad=rebate,
            ))

        data.billing_periods = sorted(periods, key=lambda p: p.start)
