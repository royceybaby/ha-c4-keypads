"""Panel registration."""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.control4_keypads import panel


async def test_register_panel(hass):
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch.object(panel.panel_custom, "async_register_panel", new=AsyncMock()) as reg:
        await panel.async_register_panel(hass)
        await panel.async_register_panel(hass)  # static path only registered once
    assert hass.http.async_register_static_paths.await_count == 1
    kwargs = reg.await_args.kwargs
    assert kwargs["frontend_url_path"] == "control4-keypads"
    assert kwargs["webcomponent_name"] == "control4-keypads-panel"
    assert kwargs["config_panel_domain"] == "control4_keypads"
    assert kwargs["require_admin"] is True
    assert kwargs["module_url"].startswith("/control4_keypads_static/control4-keypads-panel.js?v=")
    assert (panel.FRONTEND_DIR / panel.PANEL_JS).is_file()
