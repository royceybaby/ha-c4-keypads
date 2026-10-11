"""Constants for the Control4 Keypads integration."""

from __future__ import annotations

from pathlib import Path

DOMAIN = "control4_keypads"

# The integration's store doubles as the quirk's config source: the quirk in
# ./quirks reads <config>/.storage/control4_keypads directly when ZHA builds a
# keypad, so the layout is known before any entity exists.
STORE_KEY = DOMAIN
STORE_VERSION = 1

QUIRKS_DIR = Path(__file__).parent / "quirks"
QUIRK_MODULE = "zz_c4_local_models"
REQUIRED_QUIRK_VERSION = 10
# Attribute on zigpy.quirks where the current layouts are shared with the quirk
SHARED_LAYOUTS_ATTR = "_control4_keypads_layouts"
# ...and where the quirk shares firmware / bootloader versions it has read
SHARED_INFO_ATTR = "_control4_keypads_info"

BLUEPRINTS_DIR = Path(__file__).parent / "blueprints"

LEGACY_YAML = "c4_keypads.yaml"

ZHA_DOMAIN = "zha"
SUPPORTED_MODELS = ("C4-SDAPD240",)

# Quirk raw-command cluster (see quirks/zz_c4_local_models.py)
RAW_ENDPOINT = 240
RAW_CLUSTER = 0xFC9A

# ZHA light endpoint -> keypad load number
LOAD_BY_ENDPOINT = {1: 1, 11: 2}

NUM_SLOTS = 6
# Control4 Square caps come as single, double or triple height
MAX_CAP_ROWS = 3
ROCKER_SLOT = 6

KEEP = "keep"
# Button behaviour on the keypad itself (pushed by the quirk)
ACTIONS = [
    KEEP,
    "none",
    "load1_toggle",
    "load1_on",
    "load1_off",
    "load2_toggle",
    "load2_on",
    "load2_off",
]
LED_MODES = [KEEP, "ha", "load1", "load2"]

DEFAULT_FULL_RANGE_MS = 4000

CONF_KEYPADS = "keypads"
CONF_BUTTONS = "buttons"
CONF_LAYOUT = "layout"
CONF_DEVICE = "device"

SERVICE_START_DIMMING = "start_dimming"
SERVICE_STOP_DIMMING = "stop_dimming"
SERVICE_SEND_COMMAND = "send_command"

ATTR_DIRECTION = "direction"
ATTR_FULL_RANGE_MS = "full_range_ms"
ATTR_COMMAND = "command"
ATTR_KIND = "kind"
