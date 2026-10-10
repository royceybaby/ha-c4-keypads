"""Sidebar panel: the keypad editor."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_PATH = "control4-keypads"
STATIC_URL = f"/{DOMAIN}_static"
FRONTEND_DIR = Path(__file__).parent / "frontend"
PANEL_JS = "control4-keypads-panel.js"


def _js_hash() -> str:
    return hashlib.md5((FRONTEND_DIR / PANEL_JS).read_bytes()).hexdigest()[:8]


async def async_register_panel(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        data["static_registered"] = True
    version = await hass.async_add_executor_job(_js_hash)
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="control4-keypads-panel",
        sidebar_title="C4 Keypads",
        sidebar_icon="mdi:light-switch",
        module_url=f"{STATIC_URL}/{PANEL_JS}?v={version}",
        require_admin=True,
        config_panel_domain=DOMAIN,
        config={},
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_PATH, warn_if_unknown=False)
