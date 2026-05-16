"""Detect source utility from XML and dispatch to parser."""
from __future__ import annotations

from typing import Union
from xml.etree import ElementTree as ET

from ..const import (
    HOUR_S,
    SOURCE_ALECTRA,
    SOURCE_AUTO,
    SOURCE_ENBRIDGE,
    SOURCE_GENERIC,
    UOM_KWH,
    UOM_M3,
)
from .alectra import AlectraData, AlectraParser
from .common import by_local_name, child_int, child_text, iter_local
from .enbridge import EnbridgeData, EnbridgeParser
from .generic import GenericData, GenericParser

ParsedData = Union[AlectraData, EnbridgeData, GenericData]


def detect_source(root: ET.Element) -> str:
    """Inspect XML root, return one of SOURCE_ALECTRA/SOURCE_ENBRIDGE/SOURCE_GENERIC."""
    has_hourly_tou = False
    has_m3 = False

    # Alectra signature: hourly IntervalReading with <tou> child
    for reading in iter_local(root, "IntervalReading"):
        tp = by_local_name(reading, "timePeriod")
        if tp is None:
            continue
        if child_int(tp, "duration") != HOUR_S:
            continue
        if child_text(reading, "tou") is not None:
            has_hourly_tou = True
        break
    if has_hourly_tou:
        return SOURCE_ALECTRA

    # Enbridge signature: UOM 167 (m³) anywhere in measurements
    for measurement in iter_local(root, "measurement"):
        if child_int(measurement, "uom") == UOM_M3:
            has_m3 = True
            break
    if has_m3:
        return SOURCE_ENBRIDGE

    return SOURCE_GENERIC


def parse_xml(path: str, source: str = SOURCE_AUTO) -> tuple[str, ParsedData]:
    """Parse XML file, returning (resolved_source, data)."""
    tree = ET.parse(path)
    root = tree.getroot()
    resolved = source if source != SOURCE_AUTO else detect_source(root)

    if resolved == SOURCE_ALECTRA:
        return resolved, AlectraParser().parse_root(root)
    if resolved == SOURCE_ENBRIDGE:
        return resolved, EnbridgeParser().parse_root(root)
    return SOURCE_GENERIC, GenericParser().parse_root(root)
