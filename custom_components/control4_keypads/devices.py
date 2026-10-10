"""Finding Control4 keypads in ZHA's device registry."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import SUPPORTED_MODELS, ZHA_DOMAIN


def keypad_devices(hass: HomeAssistant) -> list[dr.DeviceEntry]:
    """ZHA devices that are supported Control4 keypads."""
    reg = dr.async_get(hass)
    seen: dict[str, dr.DeviceEntry] = {}
    for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        for dev in dr.async_entries_for_config_entry(reg, zha_entry.entry_id):
            if dev.model in SUPPORTED_MODELS and device_ieee(dev):
                seen[dev.id] = dev
    return list(seen.values())


def device_ieee(device: dr.DeviceEntry) -> str | None:
    for domain, value in device.identifiers:
        if domain == ZHA_DOMAIN:
            return str(value).lower()
    for kind, value in device.connections:
        if kind == dr.CONNECTION_ZIGBEE:
            return str(value).lower()
    return None
