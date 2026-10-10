"""Fixtures for Control4 Keypads tests."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
)

IEEE = "00:0f:ff:00:00:b4:ba:7f"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def zha_entry(hass):
    """A (fake) loaded ZHA config entry, and ZHA marked as set up."""
    mock_integration(
        hass,
        MockModule(
            "zha",
            async_setup_entry=AsyncMock(return_value=True),
            async_unload_entry=AsyncMock(return_value=True),
        ),
    )
    entry = MockConfigEntry(domain="zha", data={}, state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    hass.config.components.add("zha")
    # The panel needs the real frontend package; tests patch the panel out.
    hass.config.components.update({"frontend", "panel_custom"})
    return entry


@pytest.fixture
def keypad(hass, zha_entry):
    reg = dr.async_get(hass)
    return reg.async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", IEEE)},
        connections={(dr.CONNECTION_ZIGBEE, IEEE)},
        manufacturer="Control4",
        model="C4-SDAPD240",
        name="Control4 C4-SDAPD240",
    )
