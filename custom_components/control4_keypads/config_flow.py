"""Config flow for Control4 Keypads.

Keypads themselves are configured in the integration's own panel (sidebar
"Control4 Keypads", or Configure on the integration), which can show the keypad
and disable rows hidden under a multi-row cap as you edit.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, ZHA_DOMAIN
from .devices import keypad_devices


class Control4KeypadsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single Control4 Keypads entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if not self.hass.config_entries.async_entries(ZHA_DOMAIN):
            return self.async_abort(reason="zha_not_set_up")
        if user_input is not None:
            return self.async_create_entry(title="Control4 Keypads", data={})
        return self.async_show_form(
            step_id="user",
            description_placeholders={"count": str(len(keypad_devices(self.hass)))},
        )
