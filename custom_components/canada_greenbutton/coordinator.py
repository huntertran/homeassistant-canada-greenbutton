"""Coordinator that exposes parsed datasets to platforms."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .store import GreenButtonStore

_LOGGER = logging.getLogger(__name__)


class GreenButtonCoordinator(DataUpdateCoordinator[dict]):
    """Holds the parsed dataset map. Refresh triggered after imports."""

    def __init__(self, hass: HomeAssistant, store: GreenButtonStore) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # event-driven via async_request_refresh
        )
        self.store = store
        self.data = store.data

    async def _async_update_data(self) -> dict:
        return self.store.data

    async def async_notify_change(self) -> None:
        """Call after store mutations to push update to sensors."""
        self.data = self.store.data
        await self.store.async_save()
        self.async_set_updated_data(self.store.data)
