"""Control4 Keypads — use Control4 Square keypads directly with ZHA.

The heavy lifting happens in the ZHA quirks shipped in ./quirks (loaded by
ZHA through ``zha: custom_quirks_path``). This integration adds:

* a keypad editor panel (sidebar "Control4 Keypads") to describe each keypad's caps
  row by row and set each button's behaviour; it is saved to
  ``.storage/control4_keypads`` where the quirk reads it, and ZHA is reloaded
  so the change applies at once;
* services for smooth hold-to-dim (hardware fade on keypad loads) and raw
  keypad commands;
* blueprints (copied to ``blueprints/automation/control4_keypads``);
* repair issues when the quirks are not loaded from this integration.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    BLUEPRINTS_DIR,
    CONF_KEYPADS,
    DOMAIN,
    LEGACY_YAML,
    QUIRK_MODULE,
    QUIRKS_DIR,
    REQUIRED_QUIRK_VERSION,
    SHARED_LAYOUTS_ATTR,
    STORE_KEY,
    STORE_VERSION,
    ZHA_DOMAIN,
)
from .layout import buttons_from_legacy_yaml, preset_from_buttons
from .panel import async_register_panel, async_unregister_panel
from .services import async_register_services
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data[DOMAIN] = {"dimmer": async_register_services(hass)}
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, STORE_KEY)
    hass.data[DOMAIN]["store"] = store

    if CONF_KEYPADS not in entry.options:
        imported = await hass.async_add_executor_job(_read_legacy_yaml, hass.config.path(LEGACY_YAML))
        if imported:
            _LOGGER.info("Imported %d keypad layout(s) from %s", len(imported), LEGACY_YAML)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_KEYPADS: imported}
        )

    _publish_layouts(entry.options.get(CONF_KEYPADS, {}))
    changed = await _async_write_store(hass, entry)
    _check_quirks(hass)
    await hass.async_add_executor_job(_install_blueprints, Path(hass.config.path("blueprints")))

    await async_register_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    if changed:
        # The store was missing or out of date when ZHA built the keypads.
        await _async_reload_zha(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN]["dimmer"].cancel_all()
    async_unregister_panel(hass)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _publish_layouts(entry.options.get(CONF_KEYPADS, {}))
    if await _async_write_store(hass, entry):
        await _async_reload_zha(hass)


def _publish_layouts(keypads: dict[str, Any] | None) -> None:
    """Hand the layouts to the quirk in memory (see quirks/zz_c4_local_models.py).

    The store on disk is for the next start, when ZHA builds keypads before
    this integration is set up.
    """
    try:
        import zigpy.quirks
    except ImportError:  # pragma: no cover - zigpy ships with ZHA
        return
    if keypads is None:
        if hasattr(zigpy.quirks, SHARED_LAYOUTS_ATTR):
            delattr(zigpy.quirks, SHARED_LAYOUTS_ATTR)
        return
    setattr(
        zigpy.quirks,
        SHARED_LAYOUTS_ATTR,
        {str(ieee).lower(): cfg.get("buttons", []) for ieee, cfg in keypads.items()},
    )


async def _async_write_store(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Mirror the options into the store the quirk reads. True if it changed."""
    store: Store = hass.data[DOMAIN]["store"]
    data = {CONF_KEYPADS: entry.options.get(CONF_KEYPADS, {})}
    if await store.async_load() == data:
        return False
    await store.async_save(data)
    return True


async def _async_reload_zha(hass: HomeAssistant) -> None:
    for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        if zha_entry.state is ConfigEntryState.LOADED:
            _LOGGER.info("Reloading ZHA to apply Control4 keypad settings")
            await hass.config_entries.async_reload(zha_entry.entry_id)


def _read_legacy_yaml(path: str) -> dict[str, Any]:
    if not Path(path).is_file():
        return {}
    try:
        import yaml

        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not import %s: %s", path, err)
        return {}
    keypads = buttons_from_legacy_yaml(raw)
    for cfg in keypads.values():
        preset = preset_from_buttons(cfg["buttons"])
        if preset:
            cfg["layout"] = preset
    return keypads


def _check_quirks(hass: HomeAssistant) -> None:
    """Raise a repair issue unless ZHA loaded our quirks from QUIRKS_DIR."""
    module = sys.modules.get(QUIRK_MODULE)
    expected = str(QUIRKS_DIR)
    placeholders = {"path": hass.config.path("custom_components", DOMAIN, "quirks").replace("\\", "/")}

    for issue_id in ("quirks_not_loaded", "quirks_other_path", "quirks_outdated"):
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    if module is None:
        issue = "quirks_not_loaded"
    else:
        loaded_from = str(Path(getattr(module, "__file__", "")).parent)
        version = getattr(module, "QUIRK_VERSION", 0)
        if loaded_from != expected:
            issue = "quirks_other_path"
            placeholders["current"] = loaded_from.replace("\\", "/")
        elif version != REQUIRED_QUIRK_VERSION:
            issue = "quirks_outdated"
        else:
            return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR if issue == "quirks_not_loaded" else ir.IssueSeverity.WARNING,
        translation_key=issue,
        translation_placeholders=placeholders,
        learn_more_url="https://github.com/royceybaby/ha-c4-keypads#installation",
    )


def _blueprint_version(path: Path) -> int:
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return -1
    marker = "# control4_keypads blueprint v"
    if first.startswith(marker):
        try:
            return int(first[len(marker):].strip())
        except ValueError:
            return 0
    return 0  # not ours / user-edited header


def _install_blueprints(blueprints_root: Path) -> None:
    """Copy bundled blueprints unless a same-or-newer version is present."""
    for src in BLUEPRINTS_DIR.rglob("*.yaml"):
        rel = src.relative_to(BLUEPRINTS_DIR)  # automation/xxx.yaml
        dest = blueprints_root / rel.parts[0] / DOMAIN / Path(*rel.parts[1:])
        if dest.exists() and _blueprint_version(dest) >= _blueprint_version(src):
            continue
        if dest.exists() and _blueprint_version(dest) == 0:
            continue  # someone changed the header: leave their copy alone
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        _LOGGER.info("Installed blueprint %s", dest)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Integration removed: drop the store so the quirk falls back to defaults."""
    _publish_layouts(None)
    await Store(hass, STORE_VERSION, STORE_KEY).async_remove()
