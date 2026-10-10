"""Cap layouts for the 6-slot Control4 Square keypad.

A layout is written top to bottom as cap sizes in slots, e.g. ``1-1-1-1-1-R``
(five single caps and the split rocker, which can only sit in slot 6) or
``2-2-2`` (three double caps). A cap reports the button id of its top slot.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .const import ACTIONS, KEEP, LED_MODES, MAX_CAP_ROWS, NUM_SLOTS, ROCKER_SLOT

ROCKER = "R"
DEFAULT_PRESET = "1-1-1-1-1-R"


def _compositions(n: int) -> Iterator[tuple[int, ...]]:
    if n == 0:
        yield ()
        return
    for first in range(1, min(n, MAX_CAP_ROWS) + 1):
        for rest in _compositions(n - first):
            yield (first, *rest)


def _key(sizes: tuple) -> str:
    return "-".join(str(s) for s in sizes)


def all_presets() -> list[str]:
    """Every physically possible layout, most caps first, rocker layouts first."""
    with_rocker = [(*c, ROCKER) for c in _compositions(NUM_SLOTS - 1)]
    without = list(_compositions(NUM_SLOTS))
    with_rocker.sort(key=lambda c: (-len(c), c[:-1]))
    without.sort(key=lambda c: (-len(c), c))
    return [_key(c) for c in with_rocker] + [_key(c) for c in without]


def preset_label(preset: str) -> str:
    parts = []
    for size in preset.split("-"):
        if size == ROCKER:
            parts.append("rocker")
        else:
            parts.append("single" if size == "1" else f"{size}-slot")
    caps = len(parts)
    return f"{' · '.join(parts)}  ({caps} cap{'s' if caps != 1 else ''}, top to bottom)"


def preset_caps(preset: str) -> list[dict[str, Any]]:
    """``"2-1-2-R"`` -> [{"slots": [1, 2], "rocker": False}, ...]."""
    caps: list[dict[str, Any]] = []
    slot = 1
    for size in preset.split("-"):
        if size == ROCKER:
            caps.append({"slots": [ROCKER_SLOT], "rocker": True})
            slot += 1
            continue
        n = int(size)
        caps.append({"slots": list(range(slot, slot + n)), "rocker": False})
        slot += n
    if slot != NUM_SLOTS + 1:
        raise ValueError(f"layout {preset!r} does not fill {NUM_SLOTS} slots")
    return caps


def preset_from_buttons(buttons: list[dict[str, Any]] | None) -> str | None:
    """Recover the preset key from stored buttons (None if not a full layout)."""
    if not buttons:
        return None
    try:
        ordered = sorted(buttons, key=lambda b: min(b["slots"]))
        sizes = []
        expected = 1
        for btn in ordered:
            slots = sorted(int(s) for s in btn["slots"])
            if slots[0] != expected or slots != list(range(slots[0], slots[-1] + 1)):
                return None
            if btn.get("type") == "rocker":
                if slots != [ROCKER_SLOT]:
                    return None
                sizes.append(ROCKER)
            else:
                sizes.append(len(slots))
            expected = slots[-1] + 1
        if expected != NUM_SLOTS + 1:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    key = _key(tuple(sizes))
    return key if key in all_presets() else None


def default_name(cap_index: int, rocker: bool) -> str:
    return "Dimmer" if rocker else f"Button {cap_index}"


def rgb_to_hex(rgb: list[int] | tuple[int, ...] | None) -> str | None:
    if rgb is None:
        return None
    return "".join(f"{max(0, min(255, int(c))):02x}" for c in rgb)


def hex_to_rgb(value: str | None) -> list[int] | None:
    if not value:
        return None
    v = str(value).strip().lstrip("#")
    if len(v) != 6:
        return None
    try:
        return [int(v[i : i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return None


def build_button(
    cap: dict[str, Any],
    name: str,
    action: str = KEEP,
    led: str = KEEP,
    led_on: str | None = None,
    led_off: str | None = None,
) -> dict[str, Any]:
    """Stored button entry (the format the quirk reads)."""
    btn: dict[str, Any] = {"name": name, "slots": list(cap["slots"])}
    if cap.get("rocker"):
        btn["type"] = "rocker"
    if action and action != KEEP:
        btn["action"] = action
    if led and led != KEEP:
        btn["led"] = led
    if led_on:
        btn["led_on"] = led_on
    if led_off:
        btn["led_off"] = led_off
    return btn


def buttons_from_legacy_yaml(raw: Any) -> dict[str, dict[str, Any]]:
    """c4_keypads.yaml content -> {ieee: {"buttons": [...]}} (best effort)."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for ieee, entry in raw.items():
        buttons = entry.get("buttons") if isinstance(entry, dict) else entry
        if not isinstance(buttons, list):
            continue
        clean = []
        for btn in buttons:
            if not isinstance(btn, dict) or "slots" not in btn:
                continue
            slots = btn["slots"]
            slots = [slots] if isinstance(slots, int) else list(slots)
            item = {"name": str(btn.get("name") or "Button"), "slots": [int(s) for s in slots]}
            for key in ("type", "action", "led"):
                if btn.get(key) is not None:
                    item[key] = str(btn[key]).lower()
            for key in ("led_on", "led_off"):
                if btn.get(key) is not None:
                    item[key] = str(btn[key]).lstrip("#").lower()
            clean.append(item)
        out[str(ieee).strip().lower()] = {"buttons": clean}
    return out


class LayoutError(ValueError):
    """A keypad layout that can't be fitted or saved."""


def validate_buttons(buttons: Any) -> list[dict[str, Any]]:
    """Check a full keypad layout from the editor; return the clean list.

    Every row 1-6 must belong to exactly one cap, caps cover consecutive rows,
    a rocker only fits in row 6, and names must be unique.
    """
    if not isinstance(buttons, list) or not buttons:
        raise LayoutError("No caps given")
    clean: list[dict[str, Any]] = []
    used: set[int] = set()
    names: set[str] = set()
    for btn in buttons:
        if not isinstance(btn, dict):
            raise LayoutError("Bad cap entry")
        name = str(btn.get("name") or "").strip()
        if not name:
            raise LayoutError("Every cap needs a name")
        if name.lower() in names:
            raise LayoutError(f"Two caps are called “{name}”")
        names.add(name.lower())
        try:
            slots = sorted(int(s) for s in btn.get("slots") or [])
        except (TypeError, ValueError) as err:
            raise LayoutError(f"“{name}” has bad rows") from err
        if not slots or slots[0] < 1 or slots[-1] > NUM_SLOTS or slots != list(
            range(slots[0], slots[-1] + 1)
        ):
            raise LayoutError(f"“{name}” must cover consecutive rows between 1 and 6")
        if len(slots) > MAX_CAP_ROWS:
            raise LayoutError(f"“{name}” is too tall: caps are single, double or triple")
        if used & set(slots):
            raise LayoutError(f"“{name}” overlaps another cap")
        used |= set(slots)
        item: dict[str, Any] = {"name": name, "slots": slots}
        if btn.get("type") == "rocker":
            if slots != [ROCKER_SLOT]:
                raise LayoutError("The rocker only fits in row 6")
            item["type"] = "rocker"
        action = btn.get("action")
        if action not in (None, KEEP):
            if action not in ACTIONS:
                raise LayoutError(f"“{name}” has an unknown action")
            item["action"] = action
        led = btn.get("led")
        if led not in (None, KEEP):
            if led not in LED_MODES:
                raise LayoutError(f"“{name}” has an unknown LED setting")
            item["led"] = led
        for key in ("led_on", "led_off"):
            value = btn.get(key)
            if value in (None, ""):
                continue
            hexval = str(value).strip().lstrip("#").lower()
            if len(hexval) != 6 or any(c not in "0123456789abcdef" for c in hexval):
                raise LayoutError(f"“{name}” has a bad colour")
            item[key] = hexval
        clean.append(item)
    if used != set(range(1, NUM_SLOTS + 1)):
        missing = sorted(set(range(1, NUM_SLOTS + 1)) - used)
        raise LayoutError(f"Rows {', '.join(map(str, missing))} have no cap")
    clean.sort(key=lambda b: b["slots"][0])
    return clean
