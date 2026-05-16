"""Generic ESPI fallback parser. Emits interval readings + usage summaries."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from ..const import UOM_LABELS
from .common import by_local_name, child_int, child_text, direct_children, iter_local


@dataclass
class GenericReading:
    start: str
    end: str
    value: float
    unit: str


@dataclass
class GenericUsageSummary:
    start: str
    end: str
    bill_cad: float
    notes: list[str]


@dataclass
class GenericData:
    account_id: str = ""
    customer_name: str = ""
    uom: int = 0
    unit: str = ""
    readings: list[GenericReading] = field(default_factory=list)
    summaries: list[GenericUsageSummary] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class GenericParser:
    def parse(self, path: str) -> GenericData:
        return self.parse_root(ET.parse(path).getroot())

    def parse_string(self, xml: str) -> GenericData:
        return self.parse_root(ET.fromstring(xml))

    def parse_root(self, root: ET.Element) -> GenericData:
        data = GenericData()
        cust = by_local_name(root, "Customer")
        if cust is not None:
            data.customer_name = child_text(cust, "customerName") or ""
        acct = by_local_name(root, "CustomerAccount")
        if acct is not None:
            data.account_id = child_text(acct, "accountId") or ""

        rt = by_local_name(root, "ReadingType")
        multiplier = 0
        if rt is not None:
            data.uom = child_int(rt, "uom") or 0
            multiplier = child_int(rt, "powerOfTenMultiplier") or 0
        data.unit = UOM_LABELS.get(data.uom, "")

        scale = 10 ** multiplier
        for reading in iter_local(root, "IntervalReading"):
            tp = by_local_name(reading, "timePeriod")
            if tp is None:
                continue
            start_ts = child_int(tp, "start")
            duration = child_int(tp, "duration") or 0
            value = child_int(reading, "value")
            if start_ts is None or value is None:
                continue
            data.readings.append(GenericReading(
                start=datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
                end=datetime.fromtimestamp(start_ts + duration, tz=timezone.utc).isoformat(),
                value=value * scale,
                unit=data.unit,
            ))

        for summary in iter_local(root, "UsageSummary"):
            bp = by_local_name(summary, "billingPeriod")
            if bp is None:
                continue
            start_ts = child_int(bp, "start")
            duration = child_int(bp, "duration") or 0
            if start_ts is None:
                continue
            bill = (child_int(summary, "billLastPeriod") or 0) / 1000.0
            notes = []
            for detail in direct_children(summary, "costAdditionalDetailLastPeriod"):
                n = child_text(detail, "note")
                if n:
                    notes.append(n)
            data.summaries.append(GenericUsageSummary(
                start=datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
                end=datetime.fromtimestamp(start_ts + duration, tz=timezone.utc).isoformat(),
                bill_cad=bill,
                notes=notes,
            ))
        return data
