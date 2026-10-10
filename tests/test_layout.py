from custom_components.control4_keypads.layout import (
    all_presets,
    buttons_from_legacy_yaml,
    preset_caps,
    preset_from_buttons,
    preset_label,
)


def test_presets():
    presets = all_presets()
    assert len(presets) == 13 + 24  # caps of 1-3 rows, with / without rocker
    assert all(int(p) <= 3 for k in presets for p in k.split("-") if p != "R")
    assert presets[0] == "1-1-1-1-1-R"
    assert len(set(presets)) == len(presets)
    for p in presets:
        caps = preset_caps(p)
        slots = [s for c in caps for s in c["slots"]]
        assert slots == [1, 2, 3, 4, 5, 6]
        assert preset_label(p)


def test_roundtrip():
    caps = preset_caps("2-1-2-R")
    assert caps == [
        {"slots": [1, 2], "rocker": False},
        {"slots": [3], "rocker": False},
        {"slots": [4, 5], "rocker": False},
        {"slots": [6], "rocker": True},
    ]
    buttons = [{"name": "x", "slots": c["slots"], **({"type": "rocker"} if c["rocker"] else {})} for c in caps]
    assert preset_from_buttons(buttons) == "2-1-2-R"
    assert preset_from_buttons(buttons[:-1]) is None


def test_legacy_yaml():
    raw = {
        "00:0F:FF:00:00:B4:BA:7F": {
            "buttons": [
                {"name": "Button 1", "slots": [1], "action": "none", "led": "ha"},
                {"name": "Big", "slots": [2, 3, 4, 5]},
                {"name": "Dimmer", "slots": 6, "type": "rocker", "led_on": "#FF0000"},
            ]
        }
    }
    out = buttons_from_legacy_yaml(raw)
    btns = out["00:0f:ff:00:00:b4:ba:7f"]["buttons"]
    assert btns[2] == {"name": "Dimmer", "slots": [6], "type": "rocker", "led_on": "ff0000"}
    assert preset_from_buttons(btns) is None  # a 4-row cap doesn't exist
    btns[1]["slots"] = [2, 3, 4]
    btns.insert(2, {"name": "B5", "slots": [5]})
    assert preset_from_buttons(btns) == "1-3-1-R"
