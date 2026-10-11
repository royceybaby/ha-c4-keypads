"""Control4 Keypads — SDAPD240 quirk (part of the "Control4 Keypads" integration) — v10.

C4-SDAPD240  Control4 "Keypad Dual Load Dimmer"
             (Control4 driver: control4_lights_gen3_dualload, combo_dual_dimmer.c4i)

Confirmed on Royce's unit (fw 1.0.97), 2026-10-08/09:

  Loads
    Load 1 (triac 00): real ZCL Level Control on EP1 (same as the APD120).
    Load 2 (triac 01): no ZCL endpoint. SET LEVEL is
                       `0s<seq> c4.dm.tv 01 00 <level%hex>` on profile 0xC25C,
                       cluster 1 -> device replies `0r<seq> 000` (e00 = error).
    State for both:    `sa c4.dmx.ls 00 <triac> <level%hex> ...`, repeated
                       while ramping.

  Buttons (ids top to bottom; factory default: 0-2 drive load 1, 3-6 load 2)
    0x00 button_1   0x01 button_2   0x02 button_3   0x03 button_4
    0x04 button_5   0x05 rocker_up (right)          0x06 rocker_down (left)
    Press:  sa c4.dmx.bp <id>, then sa c4.dmx.sc <id>
    Clicks: sa c4.dmx.cc <id> <count>  (~1.5 s after release)

Button layout (v4)
  The keypad has 6 vertical slots; caps can span several slots. A multi-slot
  cap's actuator pin always presses its TOP slot, so a cap covering slots
  k..m reports the button id of slot k (slot 1 -> 0x00 ... slot 5 -> 0x04).
  The split rocker sits in slot 6: up = 0x05, down = 0x06.
  The physical layout per keypad is configured in the Control4 Keypads
  integration (Settings > Devices & services > Control4 Keypads > Configure),
  which saves it to <config>/.storage/control4_keypads and reloads ZHA.
  Legacy fallback: <config>/c4_keypads.yaml (keyed by IEEE). Only the buttons
  that physically exist get entities/triggers, named as configured. No entry
  -> 5 single buttons + rocker.

Per-button behaviour (v5, all confirmed on hardware 2026-10-09)
  action: none | load1_toggle | load1_on | load1_off | load2_toggle | ...
          -> c4.dmx.btn <id> 01 <code>   (none = 03: HA gets events only)
  led:    load1 | load2 | ha
          -> c4.dmx.led <id> 01 <01|0b|00>; ha = "programmed": an RGB light
             entity (EP220+id) sets the colour via c4.dmx.led <id> 05 <rgb>
  led_on / led_off: rrggbb colours used while following a load
          -> c4.dmx.led <id> 03|04 <rgb>
  Omitted keys leave the keypad's own setting untouched. Settings are pushed
  ~15 s after HA starts.

Cap layout on the device (v6)
  The keypad itself stores no cap layout (Control4 keeps it in its keypad
  proxy). The quirk applies the layout the same way the driver must:
    * slots hidden under a multi-slot cap get action "none" (03), and
    * every slot LED under a cap gets the cap's LED settings; with led: ha
      the cap's one LED entity drives all of them together.
  (Tested 2026-10-09: c4.dmx.led <n> 00 is NOT a LED->button link.)

What this quirk gives you in ZHA
  * EP1   light  — load 1 (upstream APD120 clusters)
  * EP11  light  — load 2 (reuses the LOZ-5D1-W outlet-2 clusters, which
                   speak exactly `c4.dm.tv 01 00 <level>`)
  * EP210+id binary_sensor per physical button (on while pressed) + zha_event
    device triggers (subtype = button name): press, short / double / triple /
    quadruple press, long press / release.
  * EP240 TEST cluster for raw C4 commands (see C4RawCommandCluster).

Fixes vs. running it as a plain APD120:
  * c4.dmx.ls is routed by triac, so load 2 no longer overwrites load 1.
  * c4.dmx.dim and c4.dmx.sc are not mis-parsed as levels / unknown events.
  * click counts no longer force load 1 on/off (APD120 assumes ids 1/5).
  * APD120-only LED colour / button-attached endpoints are left out; the
    SDAPD240 uses different LED commands (c4.dmx.led — still to map).
"""
import asyncio
import copy
import logging
import os
import sys
import time

_QUIRK_DIR = os.path.dirname(os.path.abspath(__file__))
if _QUIRK_DIR not in sys.path:
    sys.path.insert(0, _QUIRK_DIR)

import zigpy.types as t  # noqa: E402
from zigpy.profiles import zha  # noqa: E402
from zigpy.quirks import CustomCluster  # noqa: E402
from zigpy.zcl import foundation  # noqa: E402
from zigpy.zcl.clusters.general import BinaryInput, LevelControl, OnOff  # noqa: E402
from zigpy.zcl.foundation import (  # noqa: E402
    BaseAttributeDefs,
    ZCLAttributeDef,
    Status as ZCLStatus,
)
from zhaquirks.const import (  # noqa: E402
    BUTTON,
    CLUSTER_ID,
    COMMAND,
    DEVICE_TYPE,
    DOUBLE_PRESS,
    ENDPOINT_ID,
    ENDPOINTS,
    INPUT_CLUSTERS,
    LONG_PRESS,
    LONG_RELEASE,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
    QUADRUPLE_PRESS,
    SHORT_PRESS,
    TRIPLE_PRESS,
)

from c4_hooks import _C4_MODEL_QUIRK_MAP  # noqa: E402  (imports all device modules)
from c4_helpers import (  # noqa: E402
    C4_CLUSTER_ID,
    C4_PROFILE_BUTTON,
    C4_PROFILE_NETWORK,
    _build_c4_frame,
    next_c4_seq,
)
from c4_button_cluster import (  # noqa: E402
    C4DimmerButtonCluster,
    _make_dimmer_button_cluster,
)
from control4_outlet_dimmer import (  # noqa: E402
    C4Outlet2DimmerLevelControl,
    C4Outlet2OnOff,
)
from c4_led_rgb import (  # noqa: E402
    C4LedColorCluster,
    C4LedLevelControl,
    C4LedOnOff,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOAD2_EP = 11
BUTTON_EP_BASE = 210          # button id N lives on EP 210+N
ROCKER_SLOT = 6
ROCKER_UP_ID = 0x05
ROCKER_DOWN_ID = 0x06
NUM_SLOTS = 6

# Raw button-id names (used for log lines / the default layout)
SDAPD240_BUTTON_MAP = {
    0x00: "button_1",
    0x01: "button_2",
    0x02: "button_3",
    0x03: "button_4",
    0x04: "button_5",
    0x05: "rocker_up",
    0x06: "rocker_down",
}
# One BinaryInput cluster class per possible button id / endpoint
_BUTTON_CLUSTERS_BY_ID = {
    btn_id: _make_dimmer_button_cluster(name)
    for btn_id, name in SDAPD240_BUTTON_MAP.items()
}

C4_RAW_CMD_CLUSTER_ID = 0xFC9A
C4_RAW_CMD_EP = 240

LED_EP_BASE = 220             # HA-controlled LED for button id N on EP 220+N

# c4.dmx.btn <id> 01 <code>  — confirmed on hardware 2026-10-09
#   high nibble = load (0 = load 1, 1 = load 2); low nibble 0 on / 1 off / 2 toggle
#   03 = "Keypad": no load action at all (HA gets the events only)
BUTTON_ACTION_CODES = {
    "none": 0x03,
    "load1_on": 0x00, "load1_off": 0x01, "load1_toggle": 0x02,
    "load2_on": 0x10, "load2_off": 0x11, "load2_toggle": 0x12,
}
# c4.dmx.led <id> 01 <code>  — 01 / 0b seen as factory follow-load values;
#   00 confirmed as "programmed" (LED shows c4.dmx.led <id> 05 <rgb>)
LED_MODE_CODES = {"load1": 0x01, "load2": 0x0B, "ha": 0x00}

def _pct_to_zcl(level_pct: int) -> int:
    level_pct = max(0, min(100, int(level_pct)))
    return round(level_pct * 254 / 100)


QUIRK_VERSION = 10


def _config_dir() -> str:
    """<config>: .../custom_components/control4_keypads/quirks -> 3 levels up."""
    parts = os.path.normpath(_QUIRK_DIR).split(os.sep)
    if len(parts) >= 3 and parts[-3:-1] == ["custom_components", "control4_keypads"]:
        return os.sep.join(parts[:-3]) or os.sep
    return os.path.dirname(_QUIRK_DIR)  # legacy: <config>/custom_zha_quirks


CONFIG_DIR = _config_dir()
STORE_FILE = os.path.join(CONFIG_DIR, ".storage", "control4_keypads")
LAYOUT_FILE = os.path.join(CONFIG_DIR, "c4_keypads.yaml")

DEFAULT_LAYOUT = [
    {"name": "Button 1", "slots": [1]},
    {"name": "Button 2", "slots": [2]},
    {"name": "Button 3", "slots": [3]},
    {"name": "Button 4", "slots": [4]},
    {"name": "Button 5", "slots": [5]},
    {"name": "Rocker", "slots": [6], "type": "rocker"},
]


# ---------------------------------------------------------------------------
# Layout config  (integration store, legacy <config>/c4_keypads.yaml)
# ---------------------------------------------------------------------------

def _load_store_file():
    """Read the integration's store -> {ieee_lower: [button dicts]} or None."""
    if not os.path.exists(STORE_FILE):
        return None
    try:
        import json

        with open(STORE_FILE, encoding="utf-8") as fh:
            raw = json.load(fh)
        keypads = (raw.get("data") or {}).get("keypads") or {}
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("C4 layout: could not read %s: %s", STORE_FILE, e)
        return None
    out = {}
    for ieee, entry in keypads.items():
        buttons = entry.get("buttons") if isinstance(entry, dict) else entry
        if isinstance(buttons, list):
            out[str(ieee).strip().lower()] = buttons
    return out


def _read_layouts_from_disk() -> tuple:
    """(layouts, source) from the store, else c4_keypads.yaml. Called at
    import (ZHA imports quirks in an executor thread), never in the loop."""
    layouts = _load_store_file()
    if layouts is not None:
        return layouts, "Control4 Keypads store"
    return _load_layout_file(), "c4_keypads.yaml"


# The integration publishes the current layouts on zigpy.quirks (a module ZHA
# never re-imports), so a ZHA reload after changing the options picks them
# up even through quirk classes held by c4_hooks' patches from an earlier
# import, and without file I/O in the event loop.
_SHARED_ATTR = "_control4_keypads_layouts"


def _load_layouts() -> tuple:
    import zigpy.quirks

    shared = getattr(zigpy.quirks, _SHARED_ATTR, None)
    if isinstance(shared, dict):
        return shared, "Control4 Keypads integration"
    return _DISK_LAYOUTS, _DISK_SOURCE


def _load_layout_file() -> dict:
    """Read c4_keypads.yaml -> {ieee_lower: [button dicts]}. Never raises."""
    if not os.path.exists(LAYOUT_FILE):
        _LOGGER.debug("C4 layout: %s not found, using default layouts", LAYOUT_FILE)
        return {}
    try:
        import yaml  # available inside Home Assistant

        with open(LAYOUT_FILE, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("C4 layout: could not read %s: %s", LAYOUT_FILE, e)
        return {}
    out = {}
    for ieee, entry in (raw or {}).items():
        buttons = entry.get("buttons") if isinstance(entry, dict) else entry
        if isinstance(buttons, list):
            out[str(ieee).strip().lower()] = buttons
    _LOGGER.debug("C4 layout: loaded layouts for %d keypad(s)", len(out))
    return out


_DISK_LAYOUTS, _DISK_SOURCE = _read_layouts_from_disk()


def _hex_rgb(value, field, ieee, name):
    if value is None:
        return None
    v = str(value).strip().lstrip("#").lower()
    if len(v) == 6 and all(c in "0123456789abcdef" for c in v):
        return v
    _LOGGER.error("C4 layout [%s]: %r has bad %s %r (want rrggbb)", ieee, name, field, value)
    return None


def _resolve_layout(ieee: str) -> dict:
    """Return {button_id: ButtonCfg dict} for one keypad, validated.

    Each value: {name, ep, action, led, led_on, led_off, led_ep}
      action/led are codes to push to the device, or None = leave as-is.

    Rules (confirmed on hardware): a cap reports the id of its TOP slot;
    slots 1-5 -> ids 0x00-0x04; a rocker must sit in slot 6 and reports
    0x05 (up) / 0x06 (down). The rocker's single LED is LED 0x05.
    """
    ieee = str(ieee).lower()
    layouts, source = _load_layouts()
    buttons = layouts.get(ieee)
    if buttons is None:
        buttons, source = DEFAULT_LAYOUT, "default"

    result: dict = {}
    used_slots: set = set()
    for i, btn in enumerate(buttons, 1):
        try:
            name = str(btn.get("name") or f"Button {i}").strip()
            slots = btn.get("slots")
            if isinstance(slots, int):
                slots = [slots]
            slots = sorted(int(s) for s in slots)
            kind = str(btn.get("type", "button")).lower()
            action = btn.get("action")
            led = btn.get("led")
        except Exception:  # noqa: BLE001
            _LOGGER.error("C4 layout [%s]: bad entry #%d %r, skipped", ieee, i, btn)
            continue
        if not slots or slots[0] < 1 or slots[-1] > NUM_SLOTS or \
                slots != list(range(slots[0], slots[-1] + 1)):
            _LOGGER.error("C4 layout [%s]: %r needs contiguous slots 1-6, skipped",
                          ieee, name)
            continue
        if used_slots & set(slots):
            _LOGGER.error("C4 layout [%s]: %r overlaps another cap, skipped", ieee, name)
            continue
        used_slots |= set(slots)

        action_code = None
        if action is not None:
            action_code = BUTTON_ACTION_CODES.get(str(action).lower())
            if action_code is None:
                _LOGGER.error("C4 layout [%s]: %r unknown action %r (use one of %s)",
                              ieee, name, action, ", ".join(BUTTON_ACTION_CODES))
        led_code = None
        if led is not None:
            led_code = LED_MODE_CODES.get(str(led).lower())
            if led_code is None:
                _LOGGER.error("C4 layout [%s]: %r unknown led %r (use load1, load2 or ha)",
                              ieee, name, led)
        led_on = _hex_rgb(btn.get("led_on"), "led_on", ieee, name)
        led_off = _hex_rgb(btn.get("led_off"), "led_off", ieee, name)

        def _cfg(btn_name, btn_id, led_id, ep_id=None, led_ids=None, covered=()):
            return {
                "name": btn_name,
                "ep": ep_id if ep_id is not None else BUTTON_EP_BASE + btn_id,
                "action": action_code,
                "led": led_code,
                "led_id": led_id,
                # every slot LED under this cap (mirrored together)
                "led_ids": tuple(led_ids) if led_ids else (led_id,),
                # button ids of slots hidden under this cap
                "covered": tuple(covered),
                "led_on": led_on,
                "led_off": led_off,
                "led_ep": LED_EP_BASE + led_id if led_code == LED_MODE_CODES["ha"] else None,
            }

        if kind == "rocker":
            if slots != [ROCKER_SLOT]:
                _LOGGER.error("C4 layout [%s]: rocker %r must be in slot 6 only, "
                              "skipped", ieee, name)
                continue
            result[ROCKER_UP_ID] = _cfg(f"{name} up", ROCKER_UP_ID, ROCKER_UP_ID)
            result[ROCKER_DOWN_ID] = _cfg(f"{name} down", ROCKER_DOWN_ID, ROCKER_UP_ID)
            # one physical LED -> only one HA LED entity
            result[ROCKER_DOWN_ID]["led_ep"] = None
        else:
            top = slots[0]
            if top == ROCKER_SLOT:
                # Unverified: a plain cap in slot 6 — accept either rocker id.
                ep = BUTTON_EP_BASE + ROCKER_UP_ID
                result[ROCKER_UP_ID] = _cfg(name, ROCKER_UP_ID, ROCKER_UP_ID, ep)
                result[ROCKER_DOWN_ID] = _cfg(name, ROCKER_DOWN_ID, ROCKER_UP_ID, ep)
                result[ROCKER_DOWN_ID]["led_ep"] = None
            else:
                btn_id = top - 1
                ids = [sl - 1 for sl in slots if sl != ROCKER_SLOT]
                led_ids = ids + ([ROCKER_UP_ID] if ROCKER_SLOT in slots else [])
                covered = [i for i in ids if i != btn_id] + (
                    [ROCKER_UP_ID, ROCKER_DOWN_ID] if ROCKER_SLOT in slots else []
                )
                result[btn_id] = _cfg(name, btn_id, btn_id, led_ids=led_ids, covered=covered)

    _LOGGER.warning(
        "C4 layout [%s] (%s): %s", ieee, source,
        ", ".join(
            f"0x{k:02x}={v['name']}"
            + (f" action={v['action']:02x}" if v["action"] is not None else "")
            + (f" led={v['led']:02x}" if v["led"] is not None else "")
            for k, v in sorted(result.items())
        ),
    )
    return result


# ---------------------------------------------------------------------------
# Button / state cluster (EP197)
# ---------------------------------------------------------------------------

class C4SDAPD240ButtonCluster(C4DimmerButtonCluster):
    """APD120 button cluster, re-mapped for the SDAPD240's 7 buttons + 2 loads."""

    BUTTON_MAP = SDAPD240_BUTTON_MAP

    # Replies to `0g c4.sy.fwv` / `0g c4.sy.blv` (confirmed 2026-10-11:
    # "0r004d 000 c4.sy.fwv 5.0.5", "0r004e 000 c4.sy.blv AT25DF041A-G3iDL-1.0.3")
    _SYS_INFO = {"c4.sy.fwv": "firmware", "c4.sy.blv": "bootloader"}

    def _process_raw(self, hdr, args):
        raw = None
        if isinstance(args, (bytes, bytearray)):
            raw = bytes(args)
        elif args and isinstance(args, (list, tuple)):
            if isinstance(args[0], (bytes, bytearray, list, tuple)):
                raw = bytes(args[0])
            elif isinstance(args[0], int):
                raw = bytes(args)
        if raw:
            line = raw.decode("ascii", errors="replace").split("\r")[0].strip()
            parts = line.split()
            if (
                len(parts) >= 4
                and parts[0].startswith("0r")
                and parts[1] == "000"
                and parts[2] in self._SYS_INFO
            ):
                _store_device_info(self.endpoint.device, self._SYS_INFO[parts[2]], " ".join(parts[3:]))
            elif (
                len(parts) == 5
                and parts[0].startswith("0r")
                and parts[1] == "000"
                and parts[2] == "c4.dmx.amb"
            ):
                # Reply to `0g c4.dmx.amb 06` (the only amb index that answers
                # with two values): ambient light 0-255, e.g. "c4.dmx.amb 24 24";
                # 0xff under a torch, ~0x0d covered (confirmed 2026-10-11).
                try:
                    _store_device_info(self.endpoint.device, "ambient", int(parts[3], 16))
                except ValueError:
                    pass
        super()._process_raw(hdr, args)

    def _handle_state_announcement(self, namespace, data):
        if namespace == "c4.dmx.sc":
            # Scene/action notification that always follows c4.dmx.bp —
            # carries no extra information for HA.
            _LOGGER.debug("C4 SDAPD240: scene action, button=%s", data)
            return
        if namespace == "c4.dmx.dim":
            # Seen as `c4.dmx.dim 01 01` / `00 01` during rocker use; NOT a
            # level, so don't let the APD120 handler write it to load 1.
            _LOGGER.debug("C4 SDAPD240: dim notification %s (ignored)", data)
            return
        super()._handle_state_announcement(namespace, data)

    def _handle_light_state(self, fields):
        """c4.dmx.ls 00 <triac> <level%> ... — route by triac."""
        try:
            triac = int(fields[1], 16)
            level_pct = int(fields[2], 16)
        except (ValueError, IndexError, TypeError):
            _LOGGER.warning("C4 SDAPD240: could not parse ls %s", fields)
            return
        if triac == 0:
            super()._handle_light_state(fields)
        elif triac == 1:
            self._sync_load2(level_pct)
        else:
            _LOGGER.debug("C4 SDAPD240: ls for unknown triac %d", triac)

    def _sync_load2(self, level_pct: int) -> None:
        ep = self.endpoint.device.endpoints.get(LOAD2_EP)
        if ep is None:
            _LOGGER.warning("C4 SDAPD240: load 2 endpoint %d missing", LOAD2_EP)
            return
        level_zcl = _pct_to_zcl(level_pct)
        level_cluster = ep.in_clusters.get(LevelControl.cluster_id)
        onoff_cluster = ep.in_clusters.get(OnOff.cluster_id)
        if level_cluster is not None:
            level_cluster.update_attribute(
                LevelControl.AttributeDefs.current_level.id, level_zcl
            )
            if level_zcl > 0:
                # Remember the last real level so a plain on() restores it.
                level_cluster.update_attribute(
                    LevelControl.AttributeDefs.on_level.id, level_zcl
                )
        if onoff_cluster is not None:
            onoff_cluster.update_attribute(
                OnOff.AttributeDefs.on_off.id, level_pct > 0
            )
        _LOGGER.debug("C4 SDAPD240: load 2 -> %d%%", level_pct)

    def _sync_cc_event(self, button_id, click_count):
        # State comes from c4.dmx.ls for both loads; the APD120 logic here
        # (id 1 = on, id 5 = off) does not apply to this keypad.
        return

    def _fire_button_zha_event(self, action, button_id, button_name):
        layout = getattr(self.endpoint.device, "_c4_buttons", None) or {}
        entry = layout.get(button_id)
        if entry is None:
            _LOGGER.debug(
                "C4 SDAPD240: id 0x%02x (%s) not in this keypad's layout "
                "(covered slot?) - ignored", button_id, button_name,
            )
            return
        button_name, ep_id = entry["name"], entry["ep"]
        ep = self.endpoint.device.endpoints.get(ep_id)
        btn_cluster = ep.in_clusters.get(BinaryInput.cluster_id) if ep else None
        if btn_cluster is None:
            _LOGGER.warning(
                "C4 SDAPD240: button EP %d missing (reload ZHA / re-pair?)", ep_id
            )
            return
        btn_cluster.listener_event(
            "zha_send_event", action, {ENDPOINT_ID: ep_id, BUTTON: button_name}
        )
        if action == "press":
            btn_cluster.set_pressed(True)
        elif action in (
            SHORT_PRESS, DOUBLE_PRESS, TRIPLE_PRESS, QUADRUPLE_PRESS, LONG_RELEASE,
        ):
            btn_cluster.set_pressed(False)
        _LOGGER.debug("C4 SDAPD240: %s -> %s (EP %d)", button_name, action, ep_id)


def _store_device_info(device, key: str, value: str) -> None:
    """Share firmware/bootloader versions with the integration (zigpy.quirks
    is never re-imported, so this survives ZHA reloads)."""
    import zigpy.quirks

    info = getattr(zigpy.quirks, INFO_ATTR, None)
    if not isinstance(info, dict):
        info = {}
        setattr(zigpy.quirks, INFO_ATTR, info)
    entry = info.setdefault(str(device.ieee).lower(), {})
    if entry.get(key) != value:
        entry[key] = value
        (_LOGGER.debug if key == "ambient" else _LOGGER.info)(
            "C4 SDAPD240 [%s]: %s %s", device.ieee, key, value
        )


INFO_ATTR = "_control4_keypads_info"


# ---------------------------------------------------------------------------
# Raw command test cluster (EP240)
# ---------------------------------------------------------------------------

class C4RawCommandCluster(CustomCluster):
    """TEST ONLY: writing attribute 0 sends it as a raw C4 text command.

    action: zha.set_zigbee_cluster_attribute
    data: {ieee: ..., endpoint_id: 240, cluster_id: 64666, cluster_type: in,
           attribute: 0, value: "c4.dm.tv 01 00 32"}
    Prefix "g:" for a GET (0g) or "i:" for an interrupt (0i). Attribute 1 = 1
    sends on profile 0xC25D instead of 0xC25C.

    Hardware ramp (smooth hold-to-dim, used by automations):
      "ramp <load 1|2> up|down|stop [full_range_ms]"
    up/down start the keypad's own fade (c4.dm.rtl) towards 100 % / 1 %;
    stop freezes it at the current level. full_range_ms (default 4000) is
    the time a full 0-100 % sweep would take.
    """

    cluster_id = C4_RAW_CMD_CLUSTER_ID
    name = "Control4 Raw Command (test)"
    ep_attribute = "c4_raw_command"

    class AttributeDefs(BaseAttributeDefs):
        command = ZCLAttributeDef(
            id=0x0000, type=t.CharacterString, access="rw",
            is_manufacturer_specific=False,
        )
        profile = ZCLAttributeDef(
            id=0x0001, type=t.uint8_t, access="rw",
            is_manufacturer_specific=False,
        )

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        resolved = {}
        for attr, value in attributes.items():
            if isinstance(attr, str):
                try:
                    attr_id = self.find_attribute(attr).id
                except KeyError:
                    continue
            else:
                attr_id = int(attr)
            resolved[attr_id] = value

        if 0x0001 in resolved:
            try:
                self._update_attribute(0x0001, int(resolved[0x0001]) & 0xFF)
            except (TypeError, ValueError):
                pass

        if 0x0000 in resolved and str(resolved[0x0000] or "").strip().lower().startswith("ramp "):
            parts = str(resolved[0x0000]).split()
            try:
                load = int(parts[1])
                direction = parts[2].lower()
                full_ms = int(parts[3]) if len(parts) > 3 else RAMP_FULL_MS_DEFAULT
                if load not in (1, 2) or direction not in ("up", "down", "stop"):
                    raise ValueError
            except (IndexError, ValueError):
                _LOGGER.warning("C4 ramp: bad command %r (want 'ramp <1|2> "
                                "up|down|stop [ms]')", resolved[0x0000])
                return [[foundation.WriteAttributesStatusRecord(
                    ZCLStatus.INVALID_VALUE, attrid=0x0000)]]
            try:
                await _c4_ramp(self.endpoint.device, load - 1, direction, full_ms)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("C4 ramp: send failed - %s", e)
                return [[foundation.WriteAttributesStatusRecord(
                    ZCLStatus.FAILURE, attrid=0x0000)]]
            return [[foundation.WriteAttributesStatusRecord(ZCLStatus.SUCCESS)]]

        if 0x0000 in resolved:
            body = str(resolved[0x0000] or "").strip()
            kind = "s"
            if len(body) > 2 and body[1] == ":" and body[0] in "sgi":
                kind, body = body[0], body[2:].strip()
            profile = (
                C4_PROFILE_NETWORK
                if self._attr_cache.get(0x0001, 0) == 1
                else C4_PROFILE_BUTTON
            )
            device = self.endpoint.device
            seq = next_c4_seq(device)
            cmd = f"0{kind}{seq:04x} {body}"
            # Reads (version / light level polls) are routine; writes are notable.
            (_LOGGER.debug if kind == "g" else _LOGGER.warning)(
                "C4 raw command [%s]: sending %r on profile 0x%04X",
                device.ieee, cmd, profile,
            )
            try:
                await device.request(
                    profile=profile,
                    cluster=C4_CLUSTER_ID,
                    src_ep=1, dst_ep=1,
                    sequence=device.get_sequence(),
                    data=_build_c4_frame(seq, cmd),
                    expect_reply=False,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("C4 raw test: send failed - %s", e)
                return [[foundation.WriteAttributesStatusRecord(
                    ZCLStatus.FAILURE, attrid=0x0000)]]
            self._update_attribute(0x0000, cmd)

        return [[foundation.WriteAttributesStatusRecord(ZCLStatus.SUCCESS)]]


# ---------------------------------------------------------------------------
# HA-controlled button LEDs (EP220+id)  — c4.dmx.led <id> 05 <rrggbb>
# ---------------------------------------------------------------------------

class C4SDAPD240LedColorCluster(C4LedColorCluster):
    """HA-controlled colour for one cap: writes every slot LED under it."""

    _LED_IDS: tuple = (0,)

    async def _send_color(self, rgb_hex: str):
        device = self.endpoint.device
        for led_id in self._LED_IDS:
            try:
                await _send_c4(device, f"c4.dmx.led {led_id:02x} 05 {rgb_hex}")
                _LOGGER.info("C4 SDAPD240 LED %d: colour %s", led_id, rgb_hex)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("C4 SDAPD240 LED %d: colour %s failed - %s",
                                led_id, rgb_hex, e)


_LED_COLOR_CLUSTERS: dict = {}


def _led_color_cluster_for(led_ids) -> type:
    key = tuple(led_ids)
    if key not in _LED_COLOR_CLUSTERS:
        cls = type(
            "C4SDAPD240Led" + "_".join(str(i) for i in key) + "ColorCluster",
            (C4SDAPD240LedColorCluster,),
            {"_LED_IDS": key, "_C4_LABEL": f"SDAPD240 LEDs {key}"},
        )
        _LED_COLOR_CLUSTERS[key] = cls
    return _LED_COLOR_CLUSTERS[key]


# ---------------------------------------------------------------------------
# Device quirk
# ---------------------------------------------------------------------------

async def _send_c4(device, body: str, kind: str = "s") -> None:
    seq = next_c4_seq(device)
    cmd = f"0{kind}{seq:04x} {body}"
    await device.request(
        profile=C4_PROFILE_BUTTON,
        cluster=C4_CLUSTER_ID,
        src_ep=1, dst_ep=1,
        sequence=device.get_sequence(),
        data=_build_c4_frame(seq, cmd),
        expect_reply=False,
    )


# ---------------------------------------------------------------------------
# Hardware ramp (smooth hold-to-dim)
# ---------------------------------------------------------------------------
#   0i<seq> c4.dm.rtl <triac> <target%hex2> <time_ms_hex8>   (confirmed 2026-10-09:
#   load 2 faded 22 -> 55 % linearly over 2 s of a 4 s ramp to 100 %)
# There is no known "stop" verb, so stop = compute where the linear fade has
# got to and set that level with c4.dm.tv (the fade is superseded).

RAMP_FULL_MS_DEFAULT = 4000
RAMP_MIN_PCT = 1
_LOAD_EPS = {0: 1, 1: LOAD2_EP}


def _current_pct(device, triac: int) -> int:
    """Last known level of a load (ls updates + optimistic HA commands)."""
    ep = device.endpoints.get(_LOAD_EPS.get(triac))
    lc = ep.in_clusters.get(LevelControl.cluster_id) if ep else None
    oc = ep.in_clusters.get(OnOff.cluster_id) if ep else None
    if oc is not None and oc._attr_cache.get(OnOff.AttributeDefs.on_off.id) in (False, 0):
        return 0
    lvl = lc._attr_cache.get(LevelControl.AttributeDefs.current_level.id) if lc else None
    return round(int(lvl) * 100 / 254) if lvl is not None else 0


def _ramp_progress(r) -> tuple:
    """(estimated level now, finished?) for a ramp record."""
    start, target, t0, dur = r
    el = time.monotonic() - t0
    if dur <= 0 or el >= dur:
        return target, True
    return round(start + (target - start) * el / dur), False


async def _c4_ramp(device, triac: int, direction: str, full_ms: int) -> None:
    ramps = getattr(device, "_c4_ramps", None)
    if ramps is None:
        ramps = device._c4_ramps = {}
    if direction == "stop":
        r = ramps.pop(triac, None)
        if r is None:
            return
        lvl, finished = _ramp_progress(r)
        if not finished:
            await _send_c4(device, f"c4.dm.tv {triac:02x} 00 {lvl:02x}")
        _LOGGER.debug("C4 ramp: load %d stop at ~%d%%", triac + 1, lvl)
        return

    target = 100 if direction == "up" else RAMP_MIN_PCT
    r = ramps.get(triac)
    if r is not None:
        lvl, finished = _ramp_progress(r)
        if not finished and r[1] == target:
            return  # repeated hold event while already fading this way
        cur = lvl if not finished else _current_pct(device, triac)
    else:
        cur = _current_pct(device, triac)
    if (direction == "up" and cur >= 100) or (direction == "down" and cur <= RAMP_MIN_PCT):
        ramps.pop(triac, None)
        return
    dur_ms = max(100, round(full_ms * abs(target - cur) / 100))
    ramps[triac] = (cur, target, time.monotonic(), dur_ms / 1000)
    await _send_c4(device, f"c4.dm.rtl {triac:02x} {target:02x} {dur_ms:08x}", kind="i")
    _LOGGER.debug("C4 ramp: load %d %d%% -> %d%% over %d ms",
                  triac + 1, cur, target, dur_ms)


# ieee -> the most recently created quirk instance (HA builds the device more
# than once during startup; only the live one should push settings).
_LATEST_INSTANCE: dict = {}


async def _push_keypad_config(device, buttons: dict, delay: float = 15.0) -> None:
    """Push button actions / LED modes from c4_keypads.yaml to the keypad."""
    await asyncio.sleep(delay)
    cmds = []
    done_leds = set()
    for btn_id, cfg in sorted(buttons.items()):
        if cfg["action"] is not None:
            cmds.append(f"c4.dmx.btn {btn_id:02x} 01 {cfg['action']:02x}")
        # cap layout: slots hidden under a multi-slot cap never act on a load
        for cov in cfg.get("covered", ()):
            cmds.append(f"c4.dmx.btn {cov:02x} 01 {BUTTON_ACTION_CODES['none']:02x}")
        for led_id in cfg.get("led_ids", (cfg["led_id"],)):
            if led_id in done_leds:
                continue
            done_leds.add(led_id)
            if cfg["led"] is not None:
                cmds.append(f"c4.dmx.led {led_id:02x} 01 {cfg['led']:02x}")
            if cfg["led_on"]:
                cmds.append(f"c4.dmx.led {led_id:02x} 03 {cfg['led_on']}")
            if cfg["led_off"]:
                cmds.append(f"c4.dmx.led {led_id:02x} 04 {cfg['led_off']}")
    if not cmds:
        return

    ieee = str(device.ieee)
    for attempt in range(1, 9):
        if _LATEST_INSTANCE.get(ieee) is not device:
            _LOGGER.debug("C4 config [%s]: superseded instance, not pushing", ieee)
            return
        failed = []
        for body in cmds:
            try:
                await _send_c4(device, body)
                _LOGGER.debug("C4 config [%s]: sent %s", ieee, body)
            except Exception as e:  # noqa: BLE001
                failed.append(body)
                _LOGGER.debug("C4 config [%s]: %s failed - %s", ieee, body, e)
            await asyncio.sleep(0.4)
        if not failed:
            _LOGGER.warning(
                "C4 config [%s]: pushed %d setting(s) (attempt %d)",
                ieee, len(cmds), attempt,
            )
            return
        cmds = failed
        await asyncio.sleep(15)
    _LOGGER.warning("C4 config [%s]: gave up; not sent: %s", ieee, "; ".join(cmds))


_base = _C4_MODEL_QUIRK_MAP.get("C4-APD120")
if _base is None:
    _LOGGER.error("C4 local: C4-APD120 quirk not registered; SDAPD240 not handled")
else:
    _KEEP_FROM_BASE = (1, 2, 3, 4, 196)

    _ACTIONS = (
        "press",
        SHORT_PRESS, DOUBLE_PRESS, TRIPLE_PRESS, QUADRUPLE_PRESS,
        LONG_PRESS, LONG_RELEASE,
    )

    def _build_replacement(buttons: dict):
        rep = copy.deepcopy(_base.replacement)
        base_eps = rep[ENDPOINTS]
        eps = {ep: base_eps[ep] for ep in _KEEP_FROM_BASE if ep in base_eps}

        eps[197] = {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: 0x0000,
            INPUT_CLUSTERS: [C4SDAPD240ButtonCluster],
            OUTPUT_CLUSTERS: [],
        }
        eps[LOAD2_EP] = {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.DIMMABLE_LIGHT,
            INPUT_CLUSTERS: [C4Outlet2OnOff, C4Outlet2DimmerLevelControl],
            OUTPUT_CLUSTERS: [],
        }
        for cfg in buttons.values():
            ep_id = cfg["ep"]
            if ep_id not in eps:
                eps[ep_id] = {
                    PROFILE_ID: zha.PROFILE_ID,
                    DEVICE_TYPE: 0x0000,
                    INPUT_CLUSTERS: [_BUTTON_CLUSTERS_BY_ID[ep_id - BUTTON_EP_BASE]],
                    OUTPUT_CLUSTERS: [],
                }
            led_ep = cfg.get("led_ep")
            if led_ep and led_ep not in eps:
                eps[led_ep] = {
                    PROFILE_ID: zha.PROFILE_ID,
                    DEVICE_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                    INPUT_CLUSTERS: [
                        C4LedOnOff,
                        C4LedLevelControl,
                        _led_color_cluster_for(cfg.get("led_ids", (cfg["led_id"],))),
                    ],
                    OUTPUT_CLUSTERS: [],
                }
        eps[C4_RAW_CMD_EP] = {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: 0x0000,
            INPUT_CLUSTERS: [C4RawCommandCluster],
            OUTPUT_CLUSTERS: [],
        }
        rep[ENDPOINTS] = eps
        return rep

    def _build_triggers(buttons: dict) -> dict:
        return {
            (_action, cfg["name"]): {
                COMMAND: _action,
                CLUSTER_ID: BinaryInput.cluster_id,
                ENDPOINT_ID: cfg["ep"],
            }
            for cfg in buttons.values()
            for _action in _ACTIONS
        }

    _DEFAULT_BUTTONS = {
        i: {"name": b, "ep": BUTTON_EP_BASE + i, "action": None, "led": None,
            "led_id": min(i, ROCKER_UP_ID), "led_on": None, "led_off": None,
            "led_ep": None}
        for i, b in SDAPD240_BUTTON_MAP.items()
    }

    class Control4SDAPD240(_base):
        """C4-SDAPD240 Keypad Dual Load Dimmer, layout from c4_keypads.yaml."""

        signature = copy.deepcopy(_base.signature)
        signature[MODELS_INFO] = [("Control4", "C4-SDAPD240"), (None, "C4-SDAPD240")]

        replacement = _build_replacement(_DEFAULT_BUTTONS)
        device_automation_triggers = _build_triggers(_DEFAULT_BUTTONS)

        def __init__(self, application, ieee, nwk, replaces):
            buttons = _resolve_layout(str(ieee))
            self._c4_buttons = buttons
            # zigpy's CustomDevice reads self.replacement while building
            # endpoints, so an instance attribute gives a per-keypad layout.
            self.replacement = _build_replacement(buttons)
            self.device_automation_triggers = _build_triggers(buttons)
            super().__init__(application, ieee, nwk, replaces)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            _LATEST_INSTANCE[str(ieee)] = self
            if loop is not None and any(
                c["action"] is not None or c["led"] is not None
                or c["led_on"] or c["led_off"] for c in buttons.values()
            ):
                self._c4_push_task = loop.create_task(
                    _push_keypad_config(self, buttons)
                )

    _C4_MODEL_QUIRK_MAP["C4-SDAPD240"] = Control4SDAPD240
    _LOGGER.warning(
        "C4 local: C4-SDAPD240 registered as %s v10 (2 loads, configurable "
        "buttons/actions/LEDs from %s, raw EP %d)",
        Control4SDAPD240.__name__, STORE_FILE, C4_RAW_CMD_EP,
    )
