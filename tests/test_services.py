"""Service tests."""

import asyncio

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.control4_keypads import services as svc
from custom_components.control4_keypads.const import DOMAIN

from .conftest import IEEE


@pytest.fixture
async def setup(hass: HomeAssistant, keypad, zha_entry):
    ents = er.async_get(hass)
    load2 = ents.async_get_or_create(
        "light", "zha", f"{IEEE}-11", device_id=keypad.id, config_entry=zha_entry, suggested_object_id="load2"
    )
    led = ents.async_get_or_create(
        "light", "zha", f"{IEEE}-223", device_id=keypad.id, config_entry=zha_entry, suggested_object_id="led"
    )
    assert await async_setup_component(hass, DOMAIN, {})
    zha_calls = async_mock_service(hass, "zha", "set_zigbee_cluster_attribute")
    light_calls = async_mock_service(hass, "light", "turn_on")
    return load2.entity_id, led.entity_id, zha_calls, light_calls


async def test_keypad_load(hass, setup):
    load2, led, *_ = setup
    assert svc.keypad_load(hass, load2) == svc.KeypadLoad(IEEE, 2)
    assert svc.keypad_load(hass, led) is None
    assert svc.keypad_load(hass, "light.other") is None


async def test_hardware_ramp(hass, setup):
    load2, _, zha_calls, light_calls = setup
    await hass.services.async_call(DOMAIN, "start_dimming", {"entity_id": load2, "direction": "up"}, blocking=True)
    await hass.services.async_call(DOMAIN, "stop_dimming", {"entity_id": load2}, blocking=True)
    assert [c.data["value"] for c in zha_calls] == ["ramp 2 up 4000", "ramp 2 stop"]
    assert zha_calls[0].data["endpoint_id"] == 240
    assert zha_calls[0].data["cluster_id"] == 0xFC9A
    assert not light_calls


async def test_software_dimming(hass, setup):
    *_, zha_calls, light_calls = setup
    hass.states.async_set("light.lamp", "on", {"brightness": 128})
    await hass.services.async_call(
        DOMAIN, "start_dimming", {"entity_id": "light.lamp", "direction": "down", "full_range_ms": 1000}, blocking=True
    )
    # repeated hold events don't start a second loop
    await hass.services.async_call(DOMAIN, "start_dimming", {"entity_id": "light.lamp", "direction": "down"}, blocking=True)
    await asyncio.sleep(0.6)
    await hass.services.async_call(DOMAIN, "stop_dimming", {"entity_id": "light.lamp"}, blocking=True)
    await hass.async_block_till_done()
    n = len(light_calls)
    assert 2 <= n <= 4
    pcts = [c.data["brightness_pct"] for c in light_calls]
    assert pcts == sorted(pcts, reverse=True)
    assert pcts[0] == pytest.approx(50.2 - 25, abs=0.2)
    await asyncio.sleep(0.4)
    assert len(light_calls) == n  # stopped
    assert not zha_calls


async def test_software_dimming_stops_at_min(hass, setup):
    *_, light_calls = setup
    hass.states.async_set("light.lamp", "on", {"brightness": 10})
    await hass.services.async_call(
        DOMAIN, "start_dimming", {"entity_id": "light.lamp", "direction": "down", "full_range_ms": 500}, blocking=True
    )
    await asyncio.sleep(0.8)
    await hass.async_block_till_done()
    assert [c.data["brightness_pct"] for c in light_calls] == [1]


async def test_send_command(hass, setup, keypad):
    *_, zha_calls, _ = setup
    await hass.services.async_call(
        DOMAIN, "send_command", {"device_id": keypad.id, "command": "c4.dmx.led 00 05 ff0000"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "send_command", {"device_id": keypad.id, "command": "c4.dmx.bmc 00", "kind": "g"}, blocking=True
    )
    assert [c.data["value"] for c in zha_calls] == ["c4.dmx.led 00 05 ff0000", "g:c4.dmx.bmc 00"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "send_command", {"device_id": "nope", "command": "x"}, blocking=True)
