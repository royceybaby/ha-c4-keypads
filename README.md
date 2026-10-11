# Control4 Keypads for Home Assistant

Use Control4 Square keypads directly with Home Assistant's Zigbee integration
(ZHA). No Control4 controller needed.

- Both loads show up as dimmable lights.
- Every button press, double/triple press, hold and release can trigger
  automations.
- Describe the caps fitted to each keypad (single, multi-slot, rocker) in the
  UI. Only the buttons that physically exist get entities, with your names.
- Choose what each button does on the keypad itself: nothing (Home Assistant
  only), or switch load 1/2 on, off or toggle.
- Button LEDs follow a load, or become RGB lights you control from Home
  Assistant.
- Smooth hold-to-dim, using the keypad's own fade for its loads.

| Supported | Model | Control4 name |
|---|---|---|
| ✅ Tested | C4-SDAPD240 | Keypad Dual Load Dimmer (230 V) |

Other Control4 Zigbee devices covered by the bundled community quirks (APD120
dimmers, LDZ-101, keypads, SR260 remotes, outlets, fan controllers) load too,
but this integration's configuration screens only cover the SDAPD240 for now.

## Installation

1. **HACS** → three-dot menu → **Custom repositories** → add
   `https://github.com/royceybaby/ha-c4-keypads`, type **Integration**.
   Install **Control4 Keypads**.
2. **Tell ZHA to load the bundled quirks.** Add this to `configuration.yaml`,
   or change your existing `custom_quirks_path`:

   ```yaml
   zha:
     custom_quirks_path: /config/custom_components/control4_keypads/quirks
   ```

3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Control4 Keypads.**

If ZHA isn't loading the quirks from that folder, a repair under
**Settings → System → Repairs** tells you what to change.

### Moving from hand-copied quirks

If you previously copied the Control4 quirk files into another folder (for
example `/config/custom_zha_quirks`), point `custom_quirks_path` at the
integration's folder instead and restart. The old files are no longer used, so
you can delete them. An existing `c4_keypads.yaml` is imported the first time
the integration is set up.

## Pairing a keypad

Keep the coordinator within a couple of metres while pairing.

1. Factory reset: tap the **top** button 13×, the **bottom** button 4×, then
   the **top** button 13× again.
2. In ZHA choose **Add device**, then tap the top button 4×.
3. If the keypad gets stuck after a reset (all LEDs on, buttons ignored),
   power-cycle it and repeat step 2.

## Configuring a keypad

Open **Control4 Keypads** in the sidebar, or press **Configure** on the integration.

1. Pick the keypad. The list shows its area too.
2. Work down the six rows, top to bottom. For the cap in each row, choose:
   - **Cap:** single, double or triple, or the **up / down rocker** (row 6 only).
     A cap covering several rows disables the rows underneath it, and a
     picture of the keypad updates as you go. Click a cap in the picture to
     jump to it.
   - **Name:** becomes the trigger name in automations. A rocker named
     "Dimmer" gives "Dimmer up" and "Dimmer down".
   - **Pressing it on the keypad:** what the keypad does by itself.
     **Nothing (HA only)** means presses only reach Home Assistant.
     **Keep current setting** leaves the keypad as it is.
   - **LED:** **Shows load 1/2** follows that load. Tick **Set LED colours**
     to choose the on and off colours. **Home Assistant controls it** turns
     the LED into an RGB light entity.
3. Press **Save**.

Saving reloads ZHA, which takes a few seconds. The keypad receives its
settings about 15 seconds later. Rows hidden under a multi-row cap are set
to do nothing, and all their LEDs act as one. **Forget settings** puts the
keypad back to the default layout of five single buttons and a rocker.

Rename the new entities in the usual way (for example "Button 1 LED"). The
quirk can't name them for you.

## Automations

Every cap gets device triggers (**Settings → Automations → Device**): first
press, short press, double, triple and quadruple press, long press (repeats
about once a second while held) and long release.

A tap is confirmed about 1.5 s after release, because the keypad waits to
see whether it becomes a double press. Use **first press** for instant
response on buttons that only need a single tap.

### Blueprints

These are copied to `blueprints/automation/control4_keypads/` when the
integration starts:

- **Rocker dims a light:** tap up for on, tap down for off, hold to dim
  smoothly.
- **Button LED shows an entity's state:** colour when on and colour when off,
  for any entity.

### Services

| Service | What it does |
|---|---|
| `control4_keypads.start_dimming` | Start fading `entity_id` up or down. `full_range_ms` is the time from off to full (default 4000). A keypad load uses the keypad's hardware fade; any other light is stepped smoothly. |
| `control4_keypads.stop_dimming` | Stop the fade and keep the current level. |
| `control4_keypads.send_command` | Advanced: send a raw Control4 command, e.g. `c4.dmx.led 00 05 ff0000`. |

## Firmware

The integration reads each keypad's firmware version and shows it on the
keypad's device page and in the keypad editor (for example `5.0.5`). It
can't update the firmware. Control4 delivers firmware through its own
controllers using a proprietary update process, and the firmware images
aren't public.

## How it works

Control4 devices speak an ASCII protocol over Zigbee (profile `0xC25C`).
The bundled ZHA quirks translate it. The integration stores your keypad
settings in `.storage/control4_keypads`. The quirk reads them when ZHA builds
the keypad, then pushes per-button `c4.dmx.btn` and `c4.dmx.led` settings.
The keypad itself doesn't store which caps are fitted.

Protocol notes for the SDAPD240 are at the top of
`quirks/zz_c4_local_models.py`.

## Troubleshooting

- Turn on debug logging for `zz_c4_local_models`, `c4_button_cluster` and
  `c4_hooks`, either with the `logger.set_level` action or through ZHA's own
  debug logging.
- The log line `C4 config [...]: pushed N setting(s)` confirms the keypad
  received its button and LED settings.
- Download diagnostics from the integration page to see the stored layouts
  and which quirk file ZHA loaded.

## Credits

The Control4 protocol work and most quirks come from
[wmariz/zha-device-handlers](https://github.com/wmariz/zha-device-handlers/tree/control4/zhaquirks/control4)
(Apache-2.0). See [NOTICE](NOTICE). Not affiliated with Control4 or Snap One.
