"""Firmware version → device registry."""

import sys
import types
from unittest.mock import patch

import pytest

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.control4_keypads import firmware

from .conftest import IEEE


@pytest.fixture
def quirks():
    zigpy = types.ModuleType("zigpy")
    q = types.ModuleType("zigpy.quirks")
    zigpy.quirks = q
    with patch.dict(sys.modules, {"zigpy": zigpy, "zigpy.quirks": q}), patch.object(firmware, "RETRY_DELAY", 0):
        yield q


async def test_applies_known_version(hass, keypad, quirks):
    quirks._control4_keypads_info = {IEEE: {"firmware": "5.0.5", "bootloader": "AT25DF041A-G3iDL-1.0.3"}}
    calls = async_mock_service(hass, "zha", "set_zigbee_cluster_attribute")
    await firmware.async_refresh(hass, delay=0)
    assert dr.async_get(hass).async_get(keypad.id).sw_version == "5.0.5"
    assert calls == []  # already known: nothing asked
    assert firmware.keypad_info(IEEE.upper())["bootloader"] == "AT25DF041A-G3iDL-1.0.3"


async def test_asks_keypad_then_applies(hass, keypad, quirks):
    calls = async_mock_service(hass, "zha", "set_zigbee_cluster_attribute")

    async def fake_sleep(seconds):
        if seconds == 3:  # the keypad's reply arrives while we wait for it
            quirks._control4_keypads_info = {IEEE: {"firmware": "5.0.5"}}

    with patch.object(firmware.asyncio, "sleep", fake_sleep):
        await firmware.async_refresh(hass, delay=0)
    assert [c.data["value"] for c in calls] == ["g:c4.sy.fwv", "g:c4.sy.blv"]
    assert dr.async_get(hass).async_get(keypad.id).sw_version == "5.0.5"


async def test_gives_up_quietly(hass, keypad, quirks):
    calls = async_mock_service(hass, "zha", "set_zigbee_cluster_attribute")

    async def no_sleep(_):
        return None

    with patch.object(firmware.asyncio, "sleep", no_sleep):
        await firmware.async_refresh(hass, delay=0)
    assert len(calls) == 2 * firmware.ATTEMPTS
    assert dr.async_get(hass).async_get(keypad.id).sw_version is None
