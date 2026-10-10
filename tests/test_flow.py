"""Config flow, options flow, setup and store tests."""

import sys
import types
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
)

from custom_components.control4_keypads.const import DOMAIN, QUIRKS_DIR

from .conftest import IEEE


@pytest.fixture
def fake_quirk():
    mod = types.ModuleType("zz_c4_local_models")
    mod.__file__ = str(QUIRKS_DIR / "zz_c4_local_models.py")
    mod.QUIRK_VERSION = 8
    with patch.dict(sys.modules, {"zz_c4_local_models": mod}):
        yield mod


@pytest.fixture(autouse=True)
def fake_zigpy():
    zigpy = types.ModuleType("zigpy")
    quirks = types.ModuleType("zigpy.quirks")
    zigpy.quirks = quirks
    with patch.dict(sys.modules, {"zigpy": zigpy, "zigpy.quirks": quirks}):
        yield quirks


@pytest.fixture(autouse=True)
def no_panel():
    with patch("custom_components.control4_keypads.async_register_panel", new=AsyncMock()), patch(
        "custom_components.control4_keypads.async_unregister_panel"
    ):
        yield


@pytest.fixture
def no_reload():
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", new=AsyncMock(return_value=True)
    ) as m:
        yield m


async def test_user_flow_needs_zha(hass: HomeAssistant):
    mock_integration(hass, MockModule("zha"))
    hass.config.components.update({"zha", "frontend", "panel_custom"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "zha_not_set_up"


async def test_user_flow(hass: HomeAssistant, keypad, fake_quirk, no_reload):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["count"] == "1"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options == {"keypads": {}}
    assert hass.services.has_service(DOMAIN, "start_dimming")


async def test_import_yaml_and_store(hass: HomeAssistant, keypad, fake_quirk, no_reload, tmp_path):
    (tmp_path / "c4_keypads.yaml").write_text(
        f'"{IEEE}":\n  buttons:\n    - {{name: "Button 1", slots: [1], action: none, led: ha}}\n'
        '    - {name: "Big", slots: [2, 3, 4]}\n    - {name: "Button 5", slots: [5]}\n    - {name: "Dimmer", slots: [6], type: rocker}\n'
    )
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    kp = entry.options["keypads"][IEEE]
    assert kp["layout"] == "1-3-1-R"
    assert kp["buttons"][0] == {"name": "Button 1", "slots": [1], "action": "none", "led": "ha"}
    # store written, ZHA reloaded once
    await hass.async_block_till_done()
    store = hass.data[DOMAIN]["store"]
    assert (await store.async_load())["keypads"][IEEE]["layout"] == "1-3-1-R"
    assert no_reload.await_count == 1
    # blueprints installed
    assert (tmp_path / "blueprints/automation/control4_keypads/rocker_dimmer.yaml").is_file()
    assert (tmp_path / "blueprints/automation/control4_keypads/led_follows_entity.yaml").is_file()
    # no repair issue
    assert not ir.async_get(hass).async_get_issue(DOMAIN, "quirks_not_loaded")


async def test_repair_when_quirk_missing(hass: HomeAssistant, keypad, no_reload):
    with patch.dict(sys.modules):
        sys.modules.pop("zz_c4_local_models", None)
        entry = MockConfigEntry(domain=DOMAIN, data={}, options={"keypads": {}})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "quirks_not_loaded")
    assert issue is not None
    assert issue.translation_placeholders["path"].endswith("custom_components/control4_keypads/quirks")


async def test_repair_other_path(hass: HomeAssistant, keypad, no_reload):
    mod = types.ModuleType("zz_c4_local_models")
    mod.__file__ = "/config/custom_zha_quirks/zz_c4_local_models.py"
    mod.QUIRK_VERSION = 7
    with patch.dict(sys.modules, {"zz_c4_local_models": mod}):
        entry = MockConfigEntry(domain=DOMAIN, data={}, options={"keypads": {}})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "quirks_other_path")
    assert issue is not None
    assert issue.translation_placeholders["current"] == "/config/custom_zha_quirks"
