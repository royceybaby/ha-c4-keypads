"""Ambient light sensor."""

import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.control4_keypads import sensor as sensor_mod
from custom_components.control4_keypads.const import DOMAIN, QUIRKS_DIR

from .conftest import IEEE


@pytest.fixture
def quirks():
    zigpy = types.ModuleType("zigpy")
    q = types.ModuleType("zigpy.quirks")
    zigpy.quirks = q
    mod = types.ModuleType("zz_c4_local_models")
    mod.__file__ = str(QUIRKS_DIR / "zz_c4_local_models.py")
    mod.QUIRK_VERSION = 10
    with patch.dict(sys.modules, {"zigpy": zigpy, "zigpy.quirks": q, "zz_c4_local_models": mod}), patch.object(
        sensor_mod, "REPLY_WAIT", 0
    ), patch("custom_components.control4_keypads.async_register_panel", new=AsyncMock()), patch(
        "custom_components.control4_keypads.async_unregister_panel"
    ), patch("custom_components.control4_keypads.async_refresh_firmware", new=AsyncMock()):
        yield q


async def test_ambient_sensor(hass, keypad, quirks):
    calls = async_mock_service(hass, "zha", "set_zigbee_cluster_attribute")
    # a stray device left by 0.4.0, owned only by this integration
    stray_entry = MockConfigEntry(domain=DOMAIN, data={}, options={"keypads": {}})
    stray_entry.add_to_hass(hass)
    quirks._control4_keypads_info = {IEEE: {"ambient": 0x24}}
    entry = stray_entry
    stray = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "stray")}, name="Control4 Keypads"
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{IEEE}-ambient_light")
    assert entity_id
    ent = er.async_get(hass).async_get(entity_id)
    assert ent.device_id == keypad.id  # attached to the ZHA keypad device
    assert dr.async_get(hass).async_get(stray.id) is None
    state = hass.states.get(entity_id)
    assert state.state == "14.1"
    assert state.attributes["unit_of_measurement"] == "%"
    assert state.attributes["raw_level"] == 0x24
    assert state.attributes["friendly_name"].endswith("Ambient light")
    assert [c.data["value"] for c in calls] == ["g:c4.dmx.amb 06"]

    quirks._control4_keypads_info[IEEE]["ambient"] = 0xFF
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "100.0"
    assert await hass.config_entries.async_unload(entry.entry_id)
