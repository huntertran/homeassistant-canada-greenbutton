"""Enbridge Gas (ESPI) parser. Port of green-button-parser.service.ts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from ..const import (
    CHARGE_CARBON,
    CHARGE_GAS_DELIVERY,
    CHARGE_GAS_SUPPLY,
    CHARGE_HST,
    MIN_GAS_DURATION_S,
    NOTE_USAGE_UNADJUSTED,
    UOM_CAD,
    UOM_M3,
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
class GasReading:
    start: str
    end: str
    duration_days: float
    cubic_meters: float
    label: str


@dataclass
class ChargeItem:
    note: str
    amount_cad: float


@dataclass
class GasBillingPeriod:
    start: str
    end: str
    total_bill_cad: float
    usage_cubic_meters: float
    gas_supply_cad: float
    gas_delivery_cad: float
    carbon_cad: float
    hst_cad: float
    charges: list[ChargeItem] = field(default_factory=list)


@dataclass
class EnbridgeData:
    account_id: str = ""
    customer_name: str = ""
    address: str = ""
    readings: list[GasReading] = field(default_factory=list)
    billing_periods: list[GasBillingPeriod] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class EnbridgeParser:
    def parse(self, path: str) -> EnbridgeData:
        return self.parse_root(ET.parse(path).getroot())

    def parse_string(self, xml: str) -> EnbridgeData:
        return self.parse_root(ET.fromstring(xml))

    def parse_root(self, root: ET.Element) -> EnbridgeData:
        data = EnbridgeData()
        self._extract_customer(root, data)
        data.readings = self._extract_readings(root)
        data.billing_periods = self._extract_billing(root)
        return data

    def _extract_customer(self, root: ET.Element, data: EnbridgeData) -> None:
        cust = by_local_name(root, "Customer")
        if cust is not None:
            data.customer_name = child_text(cust, "customerName") or ""
            data.address = child_text(cust, "addressGeneral") or ""
        acct = by_local_name(root, "CustomerAccount")
        if acct is not None:
            data.account_id = child_text(acct, "accountId") or ""

    def _extract_readings(self, root: ET.Element) -> list[GasReading]:
        out: list[GasReading] = []
        for reading in iter_local(root, "IntervalReading"):
            tp = by_local_name(reading, "timePeriod")
            if tp is None:
                continue
            duration = child_int(tp, "duration") or 0
            if duration < MIN_GAS_DURATION_S:
                continue
            start_ts = child_int(tp, "start")
            value = child_int(reading, "value")
            if start_ts is None or value is None:
                continue
            cubic = value / 1000.0
            start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(start_ts + duration, tz=timezone.utc)
            out.append(GasReading(
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
                duration_days=duration / 86400.0,
                cubic_meters=cubic,
                label=start_dt.strftime("%Y-%m"),
            ))
        out.sort(key=lambda r: r.start)
        return out

    def _extract_billing(self, root: ET.Element) -> list[GasBillingPeriod]:
        out: list[GasBillingPeriod] = []
        for summary in iter_local(root, "UsageSummary"):
            bp = by_local_name(summary, "billingPeriod")
            if bp is None:
                continue
            start_ts = child_int(bp, "start")
            duration = child_int(bp, "duration") or 0
            if start_ts is None:
                continue
            bill_cents = child_int(summary, "billLastPeriod") or 0

            charges: list[ChargeItem] = []
            usage_m3 = 0.0
            gas_supply = gas_delivery = carbon = hst = 0.0

            for detail in direct_children(summary, "costAdditionalDetailLastPeriod"):
                note = (child_text(detail, "note") or "")
                note_lc = note.lower()
                amount_text = child_text(detail, "amount")
                measurement = by_local_name(detail, "measurement")
                uom = child_int(measurement, "uom") if measurement is not None else None
                m_value = child_int(measurement, "value") if measurement is not None else None
                m_mult = (child_int(measurement, "powerOfTenMultiplier") if measurement is not None else 0) or 0

                amount_cad = 0.0
                if amount_text is not None:
                    try:
                        amount_cad = int(amount_text) / 1000.0
                    except ValueError:
                        amount_cad = 0.0

                if uom == UOM_CAD:
                    charges.append(ChargeItem(note=note, amount_cad=amount_cad))
                    if CHARGE_GAS_SUPPLY in note_lc:
                        gas_supply = amount_cad
                    elif CHARGE_GAS_DELIVERY in note_lc:
                        gas_delivery = amount_cad
                    elif CHARGE_CARBON in note_lc:
                        carbon = amount_cad
                    elif CHARGE_HST in note_lc:
                        hst = amount_cad

                if NOTE_USAGE_UNADJUSTED in note_lc and uom == UOM_M3 and m_value is not None:
                    usage_m3 = m_value * (10 ** m_mult)

            end_ts = start_ts + duration
            out.append(GasBillingPeriod(
                start=datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
                end=datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(),
                total_bill_cad=bill_cents / 1000.0,
                usage_cubic_meters=usage_m3,
                gas_supply_cad=gas_supply,
                gas_delivery_cad=gas_delivery,
                carbon_cad=carbon,
                hst_cad=hst,
                charges=charges,
            ))
        out.sort(key=lambda p: p.start)
        return out
