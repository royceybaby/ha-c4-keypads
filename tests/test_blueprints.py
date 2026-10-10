"""Run the bundled blueprints end to end."""

import shutil

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.control4_keypads.const import BLUEPRINTS_DIR, DOMAIN


async def _install(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    dest = tmp_path / "blueprints/automation/control4_keypads"
    dest.mkdir(parents=True)
    for f in (BLUEPRINTS_DIR / "automation").glob("*.yaml"):
        shutil.copy(f, dest / f.name)


async def test_rocker_blueprint(hass: HomeAssistant, keypad, tmp_path):
    await _install(hass, tmp_path)
    start = async_mock_service(hass, DOMAIN, "start_dimming")
    stop = async_mock_service(hass, DOMAIN, "stop_dimming")
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("light.lamp", "off")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "control4_keypads/rocker_dimmer.yaml",
                    "input": {"keypad": keypad.id, "light": "light.lamp", "full_range": 3},
                }
            }
        },
    )
    await hass.async_block_till_done()

    def ev(command, button):
        hass.bus.async_fire(
            "zha_event",
            {"device_id": keypad.id, "command": command, "args": {"endpoint_id": 215, "button": button}},
        )

    ev("press", "Dimmer up")
    await hass.async_block_till_done()
    assert len(on) == 1
    ev("press", "Button 1")  # other buttons ignored
    ev("remote_button_long_press", "Dimmer down")
    ev("remote_button_long_press", "Dimmer down")
    ev("remote_button_long_release", "Dimmer down")
    ev("remote_button_short_press", "Dimmer down")
    await hass.async_block_till_done()
    assert [c.data for c in start] == [
        {"entity_id": "light.lamp", "direction": "down", "full_range_ms": 3000}
    ] * 2
    assert [c.data for c in stop] == [{"entity_id": "light.lamp"}]
    assert len(off) == 1
    assert len(on) == 1


async def test_led_blueprint(hass: HomeAssistant, tmp_path):
    await _install(hass, tmp_path)
    on = async_mock_service(hass, "light", "turn_on")
    off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("switch.fan", "off")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "control4_keypads/led_follows_entity.yaml",
                    "input": {"led": "light.led", "source": "switch.fan", "on_color": [255, 0, 0]},
                }
            }
        },
    )
    await hass.async_block_till_done()
    hass.states.async_set("switch.fan", "on")
    await hass.async_block_till_done()
    assert on[-1].data == {"entity_id": ["light.led"], "rgb_color": [255, 0, 0], "brightness": 255}
    hass.states.async_set("switch.fan", "off")
    await hass.async_block_till_done()
    assert len(off) == 1
