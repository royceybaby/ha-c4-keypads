"""Websocket API used by the keypad editor panel."""

from __future__ import annotations

import copy
import sys
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar

from .const import (
    ACTIONS,
    CONF_BUTTONS,
    CONF_KEYPADS,
    CONF_LAYOUT,
    DOMAIN,
    LED_MODES,
    QUIRK_MODULE,
)
from .devices import device_ieee, keypad_devices
from .layout import LayoutError, preset_from_buttons, validate_buttons


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list)
    websocket_api.async_register_command(hass, ws_save)
    websocket_api.async_register_command(hass, ws_reset)


def _entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list"})
@websocket_api.require_admin
@callback
def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entry = _entry(hass)
    saved = entry.options.get(CONF_KEYPADS, {}) if entry else {}
    areas = ar.async_get(hass)
    keypads = []
    for dev in keypad_devices(hass):
        ieee = device_ieee(dev)
        area = areas.async_get_area(dev.area_id) if dev.area_id else None
        cfg = saved.get(ieee)
        keypads.append(
            {
                "device_id": dev.id,
                "ieee": ieee,
                "name": dev.name_by_user or dev.name or ieee,
                "area": area.name if area else None,
                "model": dev.model,
                "buttons": cfg.get(CONF_BUTTONS) if cfg else None,
            }
        )
    keypads.sort(key=lambda k: ((k["area"] or "").lower(), k["name"].lower()))
    module = sys.modules.get(QUIRK_MODULE)
    connection.send_result(
        msg["id"],
        {
            "keypads": keypads,
            "actions": ACTIONS,
            "led_modes": LED_MODES,
            "quirk_loaded": module is not None,
            "configured": entry is not None,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save",
        vol.Required("ieee"): str,
        vol.Required("buttons"): list,
    }
)
@websocket_api.require_admin
@callback
def ws_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_set_up", "Control4 Keypads is not set up")
        return
    ieee = msg["ieee"].lower()
    device = next((d for d in keypad_devices(hass) if device_ieee(d) == ieee), None)
    if device is None:
        connection.send_error(msg["id"], "not_found", "That keypad isn't in ZHA")
        return
    try:
        buttons = validate_buttons(msg["buttons"])
    except LayoutError as err:
        connection.send_error(msg["id"], "invalid_layout", str(err))
        return
    options: dict[str, Any] = copy.deepcopy(dict(entry.options))
    current = options.setdefault(CONF_KEYPADS, {}).get(ieee, {})
    changed = current.get(CONF_BUTTONS) != buttons
    options[CONF_KEYPADS][ieee] = {
        "name": device.name_by_user or device.name,
        CONF_LAYOUT: preset_from_buttons(buttons),
        CONF_BUTTONS: buttons,
    }
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"changed": changed, "buttons": buttons})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/reset", vol.Required("ieee"): str}
)
@websocket_api.require_admin
@callback
def ws_reset(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_set_up", "Control4 Keypads is not set up")
        return
    options: dict[str, Any] = copy.deepcopy(dict(entry.options))
    removed = options.get(CONF_KEYPADS, {}).pop(msg["ieee"].lower(), None)
    if removed is not None:
        hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"removed": removed is not None})
