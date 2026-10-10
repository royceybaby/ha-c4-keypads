"""Diagnostics for Control4 Keypads."""

from __future__ import annotations

import sys
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_KEYPADS, QUIRK_MODULE


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    module = sys.modules.get(QUIRK_MODULE)
    return {
        "keypads": entry.options.get(CONF_KEYPADS, {}),
        "quirk": {
            "loaded": module is not None,
            "version": getattr(module, "QUIRK_VERSION", None),
            "file": getattr(module, "__file__", None),
            "store_file": getattr(module, "STORE_FILE", None),
        },
    }
