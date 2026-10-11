"""Ambient light sensor built into each keypad.

The keypad samples its light sensor about every 5 s (it uses it to dim the
button LEDs). `0g c4.dmx.amb 06` returns the level 0-255 twice; the quirk
parses the reply into the shared info. This polls once a minute and reports
it as a percentage (it is a relative level, not calibrated lux).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, ZHA_DOMAIN
from .devices import device_ieee, keypad_devices
from .firmware import keypad_info
from .services import send_raw

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)
REPLY_WAIT = 2.0
AMBIENT_QUERY = "g:c4.dmx.amb 06"


class AmbientCoordinator(DataUpdateCoordinator[dict[str, int]]):
    """Ask every keypad for its light level, then collect the replies."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, ieees: list[str]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ambient light",
            update_interval=SCAN_INTERVAL,
        )
        self.ieees = ieees

    async def _async_update_data(self) -> dict[str, int]:
        before = {ieee: keypad_info(ieee).get("ambient") for ieee in self.ieees}
        for ieee in self.ieees:
            try:
                await send_raw(self.hass, ieee, AMBIENT_QUERY)
            except Exception as err:  # noqa: BLE001 - keypad offline / ZHA busy
                _LOGGER.debug("Light level query to %s failed: %s", ieee, err)
        await asyncio.sleep(REPLY_WAIT)
        data = {}
        for ieee in self.ieees:
            value = keypad_info(ieee).get("ambient")
            if value is not None:
                data[ieee] = value
            elif before.get(ieee) is not None:
                data[ieee] = before[ieee]
        return data


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    devices = {device_ieee(dev): dev for dev in keypad_devices(hass)}
    if not devices:
        return
    coordinator = AmbientCoordinator(hass, entry, list(devices))
    # Don't block start-up on the keypads; the first poll fills the sensors.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN} first ambient poll"
    )
    async_add_entities(
        AmbientLightSensor(coordinator, ieee) for ieee in devices
    )


class AmbientLightSensor(CoordinatorEntity[AmbientCoordinator], SensorEntity):
    """Relative ambient light level measured by the keypad."""

    _attr_has_entity_name = True
    _attr_translation_key = "ambient_light"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: AmbientCoordinator, ieee: str) -> None:
        super().__init__(coordinator)
        self._ieee = ieee
        self._attr_unique_id = f"{ieee}-ambient_light"
        # Attach to the keypad's existing ZHA device.
        self._attr_device_info = DeviceInfo(identifiers={(ZHA_DOMAIN, ieee)})

    @property
    def _raw(self) -> int | None:
        return (self.coordinator.data or {}).get(self._ieee)

    @property
    def available(self) -> bool:
        return super().available and self._raw is not None

    @property
    def native_value(self) -> float | None:
        raw = self._raw
        return None if raw is None else round(raw * 100 / 255, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raw_level": self._raw}
