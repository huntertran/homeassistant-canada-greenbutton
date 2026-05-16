"""Push parsed datasets to HA long-term statistics for Energy dashboard."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.core import HomeAssistant
from homeassistant.const import UnitOfEnergy, UnitOfVolume

from .const import STAT_PREFIX, TOU_MID, TOU_OFF, TOU_ON

_LOGGER = logging.getLogger(__name__)


def _stat_id(source: str, account: str, suffix: str) -> str:
    safe_acct = (account or "default").replace(":", "_")
    return f"{STAT_PREFIX}:{source}_{safe_acct}_{suffix}"


async def push_alectra_statistics(
    hass: HomeAssistant, account: str, hourly_readings: Iterable[list], display_name: str | None = None
) -> None:
    """Push hourly kWh as long-term stats.

    hourly_readings: iterable of (epoch_ts, kwh, tou).
    Emits one total + three TOU statistic series.
    """
    readings = sorted(hourly_readings, key=lambda r: r[0])
    if not readings:
        return

    # Series accumulators per stream
    streams: dict[str, list[StatisticData]] = {
        "energy": [],
        "on_peak": [],
        "mid_peak": [],
        "off_peak": [],
    }
    sums = {k: 0.0 for k in streams}

    last_hour_key: int | None = None
    bucket = {"energy": 0.0, "on_peak": 0.0, "mid_peak": 0.0, "off_peak": 0.0}

    def flush(hour_ts: int) -> None:
        dt = datetime.fromtimestamp(hour_ts, tz=timezone.utc)
        for stream in streams:
            sums[stream] += bucket[stream]
            streams[stream].append(StatisticData(start=dt, state=bucket[stream], sum=sums[stream]))
        for k in bucket:
            bucket[k] = 0.0

    for ts, kwh, tou in readings:
        hour_key = ts - (ts % 3600)
        if last_hour_key is None:
            last_hour_key = hour_key
        if hour_key != last_hour_key:
            flush(last_hour_key)
            last_hour_key = hour_key
        bucket["energy"] += kwh
        if tou == TOU_ON:
            bucket["on_peak"] += kwh
        elif tou == TOU_MID:
            bucket["mid_peak"] += kwh
        elif tou == TOU_OFF:
            bucket["off_peak"] += kwh

    if last_hour_key is not None:
        flush(last_hour_key)

    base_name = display_name or f"Alectra {account}"
    metas = {
        "energy": (f"{base_name} energy", _stat_id("alectra", account, "energy")),
        "on_peak": (f"{base_name} on-peak", _stat_id("alectra", account, "on_peak")),
        "mid_peak": (f"{base_name} mid-peak", _stat_id("alectra", account, "mid_peak")),
        "off_peak": (f"{base_name} off-peak", _stat_id("alectra", account, "off_peak")),
    }

    for stream, points in streams.items():
        if not points:
            continue
        name, sid = metas[stream]
        meta = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=name,
            source=STAT_PREFIX,
            statistic_id=sid,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_add_external_statistics(hass, meta, points)


async def push_enbridge_statistics(
    hass: HomeAssistant, account: str, readings: Iterable[dict], display_name: str | None = None
) -> None:
    """Push gas readings as long-term stats. readings: list of GasReading dicts."""
    sorted_readings = sorted(readings, key=lambda r: r["start"])
    if not sorted_readings:
        return

    points: list[StatisticData] = []
    total = 0.0
    for r in sorted_readings:
        try:
            start_dt = datetime.fromisoformat(r["start"])
        except ValueError:
            continue
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        # Snap to hour boundary (recorder requires hour alignment)
        start_dt = start_dt.replace(minute=0, second=0, microsecond=0)
        cubic = float(r.get("cubic_meters", 0.0))
        total += cubic
        points.append(StatisticData(start=start_dt, state=cubic, sum=total))

    name = display_name or f"Enbridge {account}"
    sid = _stat_id("enbridge", account, "gas")
    meta = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=f"{name} gas",
        source=STAT_PREFIX,
        statistic_id=sid,
        unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    )
    async_add_external_statistics(hass, meta, points)


async def clear_statistics(hass: HomeAssistant, source: str | None = None) -> None:
    """No-op placeholder. Use HA's recorder UI/dev tools to drop stats by id."""
    _LOGGER.info(
        "clear_statistics called (source=%s). Stats deletion not yet implemented; "
        "use Developer Tools → Statistics in HA UI.",
        source,
    )
