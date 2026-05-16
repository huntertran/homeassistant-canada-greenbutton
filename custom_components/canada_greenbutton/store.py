"""Persistent storage for parsed GreenButton datasets."""
from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import SOURCE_ALECTRA, SOURCE_ENBRIDGE, SOURCE_GENERIC, STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class GreenButtonStore:
    """Wrap HA Store to hold a {source: {account_id: data_dict}} map."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, dict[str, dict[str, Any]]] = {
            SOURCE_ALECTRA: {},
            SOURCE_ENBRIDGE: {},
            SOURCE_GENERIC: {},
        }

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if isinstance(loaded, dict):
            for src in (SOURCE_ALECTRA, SOURCE_ENBRIDGE, SOURCE_GENERIC):
                if isinstance(loaded.get(src), dict):
                    self.data[src] = loaded[src]

    async def async_save(self) -> None:
        await self._store.async_save(self.data)

    def put(self, source: str, account_id: str, dataset: Any) -> None:
        """Insert/replace a dataset; merge if existing entries can be augmented."""
        if is_dataclass(dataset):
            payload = asdict(dataset)
        elif isinstance(dataset, dict):
            payload = dataset
        else:
            raise TypeError(f"Unsupported dataset type: {type(dataset)}")

        bucket = self.data.setdefault(source, {})
        key = account_id or "default"
        existing = bucket.get(key)
        if existing:
            bucket[key] = _merge(existing, payload, source)
        else:
            bucket[key] = payload

    async def async_clear(self, source: str | None = None) -> None:
        if source is None:
            for k in self.data:
                self.data[k] = {}
        else:
            self.data[source] = {}
        await self.async_save()


def _merge(old: dict, new: dict, source: str) -> dict:
    """Merge new dataset into old. New billing/readings replace by key; metadata wins from new."""
    merged = dict(old)
    # Scalar metadata: prefer new if non-empty
    for k in ("account_id", "customer_name", "address", "uom", "unit"):
        v = new.get(k)
        if v:
            merged[k] = v

    if source == "alectra":
        merged["billing_periods"] = _merge_list(old.get("billing_periods"), new.get("billing_periods"), key="start")
        merged["monthly_tou"] = _merge_list(old.get("monthly_tou"), new.get("monthly_tou"), key="label")
        merged["daily_summaries"] = _merge_list(old.get("daily_summaries"), new.get("daily_summaries"), key="date_key")
        merged["hourly_readings"] = _merge_pairs(old.get("hourly_readings"), new.get("hourly_readings"))
        merged["heatmap"] = new.get("heatmap") or old.get("heatmap")
    elif source == "enbridge":
        merged["readings"] = _merge_list(old.get("readings"), new.get("readings"), key="start")
        merged["billing_periods"] = _merge_list(old.get("billing_periods"), new.get("billing_periods"), key="start")
    else:
        merged["readings"] = _merge_list(old.get("readings"), new.get("readings"), key="start")
        merged["summaries"] = _merge_list(old.get("summaries"), new.get("summaries"), key="start")

    return merged


def _merge_list(old, new, key: str) -> list:
    out = {}
    for item in (old or []):
        if isinstance(item, dict) and key in item:
            out[item[key]] = item
    for item in (new or []):
        if isinstance(item, dict) and key in item:
            out[item[key]] = item
    return sorted(out.values(), key=lambda x: x.get(key, ""))


def _merge_pairs(old, new) -> list:
    """Hourly readings stored as [ts, kwh, tou] tuples — dedupe by ts."""
    out = {}
    for triple in (old or []):
        if isinstance(triple, (list, tuple)) and len(triple) >= 3:
            out[triple[0]] = list(triple)
    for triple in (new or []):
        if isinstance(triple, (list, tuple)) and len(triple) >= 3:
            out[triple[0]] = list(triple)
    return [out[k] for k in sorted(out.keys())]
