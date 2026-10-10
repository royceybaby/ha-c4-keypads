"""Services: smooth hold-to-dim for any light, and raw keypad commands.

start_dimming / stop_dimming
  * A load on a Control4 keypad (ZHA light on EP1 = load 1, EP11 = load 2):
    the keypad's own hardware fade (c4.dm.rtl) — perfectly smooth; stop
    freezes it where it got to.
  * Any other light: small brightness steps with matching transitions until
    stop_dimming, the end of the range, or a safety timeout.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_COMMAND,
    ATTR_DIRECTION,
    ATTR_FULL_RANGE_MS,
    ATTR_KIND,
    DEFAULT_FULL_RANGE_MS,
    DOMAIN,
    LOAD_BY_ENDPOINT,
    RAW_CLUSTER,
    RAW_ENDPOINT,
    SERVICE_SEND_COMMAND,
    SERVICE_START_DIMMING,
    SERVICE_STOP_DIMMING,
    SUPPORTED_MODELS,
    ZHA_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_INTERVAL = 0.25  # s, software dimming
MIN_PCT = 1

START_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_DIRECTION): vol.In(["up", "down"]),
        vol.Optional(ATTR_FULL_RANGE_MS, default=DEFAULT_FULL_RANGE_MS): vol.All(
            vol.Coerce(int), vol.Range(min=500, max=60000)
        ),
    }
)
STOP_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids})
COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required(ATTR_COMMAND): cv.string,
        vol.Optional(ATTR_KIND, default="s"): vol.In(["s", "g", "i"]),
    }
)


@dataclass(frozen=True)
class KeypadLoad:
    ieee: str
    load: int


def keypad_load(hass: HomeAssistant, entity_id: str) -> KeypadLoad | None:
    """Which keypad load (if any) a light entity is."""
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None or ent.platform != ZHA_DOMAIN or ent.device_id is None:
        return None
    dev = dr.async_get(hass).async_get(ent.device_id)
    if dev is None or dev.model not in SUPPORTED_MODELS:
        return None
    # ZHA light unique_id: "<ieee>-<endpoint>"
    try:
        ieee, ep = ent.unique_id.rsplit("-", 1)
        load = LOAD_BY_ENDPOINT.get(int(ep))
    except ValueError:
        return None
    if load is None:
        return None
    return KeypadLoad(ieee.lower(), load)


def device_ieee(hass: HomeAssistant, device_id: str) -> str:
    dev = dr.async_get(hass).async_get(device_id)
    if dev is None or dev.model not in SUPPORTED_MODELS:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_a_keypad"
        )
    for domain, value in dev.identifiers:
        if domain == ZHA_DOMAIN:
            return str(value)
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_keypad")


async def send_raw(hass: HomeAssistant, ieee: str, value: str) -> None:
    """Hand a command to the quirk's raw-command cluster (EP240)."""
    await hass.services.async_call(
        ZHA_DOMAIN,
        "set_zigbee_cluster_attribute",
        {
            "ieee": ieee,
            "endpoint_id": RAW_ENDPOINT,
            "cluster_id": RAW_CLUSTER,
            "cluster_type": "in",
            "attribute": 0,
            "value": value,
        },
        blocking=True,
    )


class Dimmer:
    """Tracks software dimming tasks per entity."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._tasks: dict[str, asyncio.Task] = {}

    @callback
    def cancel(self, entity_id: str) -> bool:
        task = self._tasks.pop(entity_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    @callback
    def cancel_all(self) -> None:
        for entity_id in list(self._tasks):
            self.cancel(entity_id)

    async def start(self, entity_id: str, direction: str, full_ms: int) -> None:
        target = keypad_load(self.hass, entity_id)
        if target is not None:
            await send_raw(
                self.hass, target.ieee, f"ramp {target.load} {direction} {full_ms}"
            )
            return
        if entity_id in self._tasks and not self._tasks[entity_id].done():
            return  # already dimming (hold events repeat about once a second)
        self._tasks[entity_id] = self.hass.async_create_background_task(
            self._step(entity_id, direction, full_ms), f"{DOMAIN} dim {entity_id}"
        )

    async def stop(self, entity_id: str) -> None:
        target = keypad_load(self.hass, entity_id)
        if target is not None:
            await send_raw(self.hass, target.ieee, f"ramp {target.load} stop")
            return
        self.cancel(entity_id)

    async def _step(self, entity_id: str, direction: str, full_ms: int) -> None:
        step = max(1.0, 100 * STEP_INTERVAL * 1000 / full_ms)
        sign = 1 if direction == "up" else -1
        deadline = self.hass.loop.time() + full_ms / 1000 * 1.5 + 2
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        bri = state.attributes.get("brightness")
        # Track the level ourselves: the light's reported state lags behind.
        pct = (bri or 0) * 100 / 255 if state.state == "on" else 0
        try:
            while self.hass.loop.time() < deadline:
                if sign > 0 and pct >= 100:
                    return
                if sign < 0 and pct <= MIN_PCT:
                    return
                pct = min(100, pct + step) if sign > 0 else max(MIN_PCT, pct - step)
                new_pct = pct
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        "brightness_pct": round(new_pct, 1),
                        "transition": STEP_INTERVAL,
                    },
                    blocking=False,
                )
                await asyncio.sleep(STEP_INTERVAL)
        finally:
            if self._tasks.get(entity_id) is asyncio.current_task():
                self._tasks.pop(entity_id, None)


@callback
def async_register_services(hass: HomeAssistant) -> Dimmer:
    dimmer = Dimmer(hass)

    async def _start(call: ServiceCall) -> None:
        for entity_id in call.data[ATTR_ENTITY_ID]:
            await dimmer.start(
                entity_id, call.data[ATTR_DIRECTION], call.data[ATTR_FULL_RANGE_MS]
            )

    async def _stop(call: ServiceCall) -> None:
        for entity_id in call.data[ATTR_ENTITY_ID]:
            await dimmer.stop(entity_id)

    async def _command(call: ServiceCall) -> None:
        ieee = device_ieee(hass, call.data["device_id"])
        kind = call.data[ATTR_KIND]
        command = call.data[ATTR_COMMAND].strip()
        await send_raw(hass, ieee, command if kind == "s" else f"{kind}:{command}")

    hass.services.async_register(DOMAIN, SERVICE_START_DIMMING, _start, START_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP_DIMMING, _stop, STOP_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SEND_COMMAND, _command, COMMAND_SCHEMA)
    return dimmer
