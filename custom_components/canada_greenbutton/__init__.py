"""Canada GreenButton integration."""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_PUSH_STATS,
    CONF_WATCH_DIR,
    DOMAIN,
    IMPORT_DIR,
    PLATFORMS,
    SERVICE_CLEAR_DATA,
    SERVICE_IMPORT_XML,
    SOURCE_ALECTRA,
    SOURCE_AUTO,
    SOURCE_ENBRIDGE,
    SOURCE_GENERIC,
    WATCH_INTERVAL_S,
)
from .coordinator import GreenButtonCoordinator
from .parser import parse_xml
from .statistics import push_alectra_statistics, push_enbridge_statistics
from .store import GreenButtonStore

_LOGGER = logging.getLogger(__name__)

IMPORT_SCHEMA = vol.Schema({
    vol.Required("path"): cv.string,
    vol.Optional("source", default=SOURCE_AUTO): vol.In(
        [SOURCE_AUTO, SOURCE_ALECTRA, SOURCE_ENBRIDGE, SOURCE_GENERIC]
    ),
})

CLEAR_SCHEMA = vol.Schema({
    vol.Optional("source"): vol.In([SOURCE_ALECTRA, SOURCE_ENBRIDGE, SOURCE_GENERIC]),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    store = GreenButtonStore(hass)
    await store.async_load()

    coordinator = GreenButtonCoordinator(hass, store)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _import_one(path: str, source: str) -> dict[str, Any]:
        if not os.path.isfile(path):
            raise HomeAssistantError(f"File not found: {path}")
        resolved, dataset = await hass.async_add_executor_job(parse_xml, path, source)
        account = getattr(dataset, "account_id", "") or "default"
        store.put(resolved, account, dataset)
        if entry.options.get(CONF_PUSH_STATS, True):
            await _push_stats(resolved, account, dataset)
        await coordinator.async_notify_change()
        return {"source": resolved, "account": account}

    async def _push_stats(source: str, account: str, dataset) -> None:
        if source == SOURCE_ALECTRA:
            await push_alectra_statistics(
                hass, account, dataset.hourly_readings, display_name=dataset.customer_name or None
            )
        elif source == SOURCE_ENBRIDGE:
            readings = [r.__dict__ for r in dataset.readings]
            await push_enbridge_statistics(
                hass, account, readings, display_name=dataset.customer_name or None
            )

    async def handle_import(call: ServiceCall) -> None:
        await _import_one(call.data["path"], call.data.get("source", SOURCE_AUTO))

    async def handle_clear(call: ServiceCall) -> None:
        await store.async_clear(call.data.get("source"))
        await coordinator.async_notify_change()

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_XML, handle_import, schema=IMPORT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_DATA, handle_clear, schema=CLEAR_SCHEMA)

    # Folder watcher
    watch_dir = (entry.options.get(CONF_WATCH_DIR) or "").strip()
    if watch_dir and os.path.isdir(watch_dir):
        async def _scan(_now=None) -> None:
            try:
                for name in os.listdir(watch_dir):
                    if not name.lower().endswith(".xml"):
                        continue
                    fpath = os.path.join(watch_dir, name)
                    try:
                        await _import_one(fpath, SOURCE_AUTO)
                        os.rename(fpath, fpath + ".imported")
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.exception("Import failed for %s: %s", fpath, err)
                        try:
                            os.rename(fpath, fpath + ".failed")
                        except OSError:
                            pass
            except FileNotFoundError:
                _LOGGER.warning("Watch dir disappeared: %s", watch_dir)

        unsub = async_track_time_interval(hass, _scan, timedelta(seconds=WATCH_INTERVAL_S))
        hass.data[DOMAIN][entry.entry_id]["watch_unsub"] = unsub
        hass.async_create_task(_scan())

    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    bucket = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    unsub = bucket.get("watch_unsub")
    if unsub:
        unsub()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not hass.data[DOMAIN]:
        for svc in (SERVICE_IMPORT_XML, SERVICE_CLEAR_DATA):
            if hass.services.has_service(DOMAIN, svc):
                hass.services.async_remove(DOMAIN, svc)
    return unloaded
