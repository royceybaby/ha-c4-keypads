"""Read each keypad's firmware version and show it on its device page.

The keypad answers `0g c4.sy.fwv` (firmware, e.g. 5.0.5) and `0g c4.sy.blv`
(bootloader). The quirk parses the replies and shares them on zigpy.quirks;
this module asks for them and copies the firmware into the device registry.
ZHA re-creates the registry entry without a version when it reloads, so the
version is re-applied after every reload and twice a day.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import SHARED_INFO_ATTR
from .devices import device_ieee, keypad_devices
from .services import send_raw

_LOGGER = logging.getLogger(__name__)

QUERIES = ("c4.sy.fwv", "c4.sy.blv")
ATTEMPTS = 4
RETRY_DELAY = 30


def shared_info() -> dict[str, dict[str, Any]]:
    try:
        import zigpy.quirks
    except ImportError:  # pragma: no cover - zigpy ships with ZHA
        return {}
    info = getattr(zigpy.quirks, SHARED_INFO_ATTR, None)
    return info if isinstance(info, dict) else {}


def keypad_info(ieee: str | None) -> dict[str, Any]:
    return dict(shared_info().get((ieee or "").lower(), {}))


@callback
def _set_firmware(hass: HomeAssistant, device: dr.DeviceEntry, ieee: str, firmware: str) -> None:
    if device.sw_version == firmware:
        return
    try:
        # Prefer telling ZHA, so its own device state agrees with the registry.
        from homeassistant.components.zha.helpers import get_zha_gateway_proxy

        proxy = get_zha_gateway_proxy(hass)
        for key, dev_proxy in proxy.device_proxies.items():
            if str(key).lower() == ieee:
                dev_proxy.device.async_update_firmware_version(firmware)
                break
    except Exception:  # noqa: BLE001 - internal ZHA API; fall back below
        pass
    current = dr.async_get(hass).async_get(device.id)
    if current is not None and current.sw_version != firmware:
        dr.async_get(hass).async_update_device(device.id, sw_version=firmware)


@callback
def async_apply_known(hass: HomeAssistant) -> list[str]:
    """Copy known versions into the registry; return keypads still unknown."""
    missing = []
    for device in keypad_devices(hass):
        ieee = device_ieee(device)
        firmware = keypad_info(ieee).get("firmware")
        if firmware:
            _set_firmware(hass, device, ieee, firmware)
        else:
            missing.append(ieee)
    return missing


async def async_refresh(hass: HomeAssistant, delay: float = 25) -> None:
    """Ask keypads that haven't told us their version yet, then apply."""
    await asyncio.sleep(delay)
    for attempt in range(ATTEMPTS):
        missing = async_apply_known(hass)
        if not missing:
            return
        for ieee in missing:
            for query in QUERIES:
                try:
                    await send_raw(hass, ieee, f"g:{query}")
                except Exception as err:  # noqa: BLE001 - keypad asleep / ZHA busy
                    _LOGGER.debug("Firmware query to %s failed: %s", ieee, err)
        await asyncio.sleep(3)
        if not async_apply_known(hass):
            return
        if attempt < ATTEMPTS - 1:
            await asyncio.sleep(RETRY_DELAY)
    _LOGGER.debug("No firmware version from %s", ", ".join(async_apply_known(hass)))
