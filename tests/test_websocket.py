"""Websocket API behind the keypad editor panel."""

import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.control4_keypads.const import DOMAIN

from .conftest import IEEE


@pytest.fixture
async def ws(hass: HomeAssistant, keypad, hass_ws_client):
    quirks = types.ModuleType("zigpy.quirks")
    zigpy = types.ModuleType("zigpy")
    zigpy.quirks = quirks
    with patch.dict(sys.modules, {"zigpy": zigpy, "zigpy.quirks": quirks}), patch(
        "custom_components.control4_keypads.async_register_panel", new=AsyncMock()
    ), patch("custom_components.control4_keypads.async_unregister_panel"), patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", new=AsyncMock(return_value=True)
    ) as reload:
        area = ar.async_get(hass).async_create("Front Living")
        dr.async_get(hass).async_update_device(keypad.id, area_id=area.id)
        entry = MockConfigEntry(domain=DOMAIN, data={}, options={"keypads": {}})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        reload.reset_mock()
        client = await hass_ws_client(hass)
        yield client, entry, reload, quirks


async def _call(client, **msg):
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_list(ws):
    client, *_ = ws
    res = await _call(client, type="control4_keypads/list")
    assert res["success"]
    kp = res["result"]["keypads"][0]
    assert kp["ieee"] == IEEE
    assert kp["area"] == "Front Living"
    assert kp["buttons"] is None
    assert res["result"]["configured"] is True


async def test_save_and_reset(hass, ws, hass_storage):
    client, entry, reload, quirks = ws
    buttons = [
        {"name": "Scene", "slots": [1, 2], "action": "none", "led": "ha"},
        {"name": "Lamps", "slots": [3], "action": "keep", "led": "load2", "led_on": "#FFFFFF", "led_off": "000000"},
        {"name": "Big", "slots": [4, 5]},
        {"name": "Dimmer", "slots": [6], "type": "rocker", "action": "none", "led": "ha"},
    ]
    res = await _call(client, type="control4_keypads/save", ieee=IEEE.upper(), buttons=buttons)
    assert res["success"], res
    assert res["result"]["changed"] is True
    await hass.async_block_till_done()
    kp = entry.options["keypads"][IEEE]
    assert kp["layout"] == "2-1-2-R"
    assert kp["buttons"][1] == {"name": "Lamps", "slots": [3], "led": "load2", "led_on": "ffffff", "led_off": "000000"}
    assert hass_storage["control4_keypads"]["data"]["keypads"][IEEE]["layout"] == "2-1-2-R"
    assert quirks._control4_keypads_layouts[IEEE] == kp["buttons"]
    assert reload.await_count == 1

    # saving the same again changes nothing and doesn't reload ZHA
    res = await _call(client, type="control4_keypads/save", ieee=IEEE, buttons=buttons)
    assert res["result"]["changed"] is False
    await hass.async_block_till_done()
    assert reload.await_count == 1

    res = await _call(client, type="control4_keypads/list")
    assert res["result"]["keypads"][0]["buttons"] == kp["buttons"]

    res = await _call(client, type="control4_keypads/reset", ieee=IEEE)
    assert res["result"]["removed"] is True
    await hass.async_block_till_done()
    assert entry.options["keypads"] == {}
    assert reload.await_count == 2


@pytest.mark.parametrize(
    ("buttons", "message"),
    [
        ([{"name": "A", "slots": [1, 2, 3]}, {"name": "B", "slots": [3, 4, 5]}, {"name": "C", "slots": [6]}], "overlaps"),
        ([{"name": "A", "slots": [1, 2, 3]}, {"name": "B", "slots": [4, 5]}], "Rows 6 have no cap"),
        ([{"name": "A", "slots": [1, 2, 3]}, {"name": "B", "slots": [4]}, {"name": "R", "slots": [5, 6], "type": "rocker"}], "row 6"),
        ([{"name": "A", "slots": [1, 2, 3, 4]}, {"name": "B", "slots": [5, 6]}], "too tall"),
        ([{"name": "A", "slots": [1, 2, 3]}, {"name": "a", "slots": [4, 5, 6]}], "Two caps"),
        ([{"name": "A", "slots": [1, 3]}, {"name": "B", "slots": [2]}, {"name": "C", "slots": [4, 5, 6]}], "consecutive"),
        ([{"name": " ", "slots": [1, 2, 3]}, {"name": "B", "slots": [4, 5, 6]}], "name"),
        ([{"name": "A", "slots": [1, 2, 3], "led": "load1", "led_on": "zz0000"}, {"name": "B", "slots": [4, 5, 6]}], "colour"),
    ],
)
async def test_save_invalid(ws, buttons, message):
    client, entry, reload, _ = ws
    res = await _call(client, type="control4_keypads/save", ieee=IEEE, buttons=buttons)
    assert not res["success"]
    assert res["error"]["code"] == "invalid_layout"
    assert message in res["error"]["message"]
    assert entry.options["keypads"] == {}


async def test_save_unknown_keypad(ws):
    client, *_ = ws
    res = await _call(client, type="control4_keypads/save", ieee="00:11:22:33:44:55:66:77",
                      buttons=[{"name": "A", "slots": [1, 2, 3]}, {"name": "B", "slots": [4, 5, 6]}])
    assert res["error"]["code"] == "not_found"
