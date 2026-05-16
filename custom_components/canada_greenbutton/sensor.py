"""Summary sensors for Canada GreenButton. Card reads raw_data attribute."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_DOLLAR, PERCENTAGE, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SOURCE_ALECTRA, SOURCE_ENBRIDGE, SOURCE_GENERIC
from .coordinator import GreenButtonCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GreenButtonCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SensorEntity] = []
    seen: set[str] = set()

    def discover():
        new: list[SensorEntity] = []
        for account in coordinator.data.get(SOURCE_ALECTRA, {}):
            for cls in (AlectraLastBillKwh, AlectraLastBillAmount, AlectraTotalKwhYtd, AlectraOnPeakShare):
                key = f"alectra:{account}:{cls.__name__}"
                if key not in seen:
                    seen.add(key)
                    new.append(cls(coordinator, account))
        for account in coordinator.data.get(SOURCE_ENBRIDGE, {}):
            for cls in (EnbridgeLastBillM3, EnbridgeLastBillAmount):
                key = f"enbridge:{account}:{cls.__name__}"
                if key not in seen:
                    seen.add(key)
                    new.append(cls(coordinator, account))
        for account in coordinator.data.get(SOURCE_GENERIC, {}):
            key = f"generic:{account}:summary"
            if key not in seen:
                seen.add(key)
                new.append(GenericSummary(coordinator, account))
        if new:
            async_add_entities(new)

    discover()

    @callback_safe
    def _on_update():
        discover()

    coordinator.async_add_listener(_on_update)


def callback_safe(fn):
    # Plain wrapper to satisfy DataUpdateCoordinator.async_add_listener (expects callable)
    return fn


class _Base(CoordinatorEntity[GreenButtonCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GreenButtonCoordinator, source: str, account: str, suffix: str) -> None:
        super().__init__(coordinator)
        self._source = source
        self._account = account or "default"
        self._attr_unique_id = f"{DOMAIN}_{source}_{self._account}_{suffix}"

    def _dataset(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._source, {}).get(self._account, {}) or {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raw_data": self._dataset()}


# ---- Alectra ---------------------------------------------------------------
class AlectraLastBillKwh(_Base):
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_ALECTRA, account, "last_bill_kwh")
        self._attr_name = "Alectra last bill kWh"

    @property
    def native_value(self):
        periods = self._dataset().get("billing_periods") or []
        return round(periods[-1]["usage_kwh"], 2) if periods else None


class AlectraLastBillAmount(_Base):
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_ALECTRA, account, "last_bill_amount")
        self._attr_name = "Alectra last bill amount"

    @property
    def native_value(self):
        periods = self._dataset().get("billing_periods") or []
        return round(periods[-1]["total_bill_cad"], 2) if periods else None


class AlectraTotalKwhYtd(_Base):
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_ALECTRA, account, "total_kwh_ytd")
        self._attr_name = "Alectra total kWh YTD"

    @property
    def native_value(self):
        year = date.today().year
        total = 0.0
        for m in self._dataset().get("monthly_tou") or []:
            if m.get("year") == year:
                total += m.get("total_kwh", 0.0)
        return round(total, 2)


class AlectraOnPeakShare(_Base):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_ALECTRA, account, "on_peak_share")
        self._attr_name = "Alectra on-peak share"

    @property
    def native_value(self):
        on = mid = off = 0.0
        for m in self._dataset().get("monthly_tou") or []:
            on += m.get("on_peak_kwh", 0.0)
            mid += m.get("mid_peak_kwh", 0.0)
            off += m.get("off_peak_kwh", 0.0)
        total = on + mid + off
        return round(on / total * 100.0, 1) if total else None


# ---- Enbridge --------------------------------------------------------------
class EnbridgeLastBillM3(_Base):
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_ENBRIDGE, account, "last_bill_m3")
        self._attr_name = "Enbridge last bill m³"

    @property
    def native_value(self):
        periods = self._dataset().get("billing_periods") or []
        return round(periods[-1]["usage_cubic_meters"], 2) if periods else None


class EnbridgeLastBillAmount(_Base):
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_ENBRIDGE, account, "last_bill_amount")
        self._attr_name = "Enbridge last bill amount"

    @property
    def native_value(self):
        periods = self._dataset().get("billing_periods") or []
        return round(periods[-1]["total_bill_cad"], 2) if periods else None


# ---- Generic ---------------------------------------------------------------
class GenericSummary(_Base):
    def __init__(self, coordinator, account):
        super().__init__(coordinator, SOURCE_GENERIC, account, "summary")
        self._attr_name = "GreenButton readings"

    @property
    def native_value(self):
        return len(self._dataset().get("readings") or [])
