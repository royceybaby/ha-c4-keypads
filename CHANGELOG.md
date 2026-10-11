# Changelog

## 0.3.0 — 2026-10-11

- Firmware version: each keypad is asked for its firmware (`c4.sy.fwv`) and
  bootloader (`c4.sy.blv`) versions. The firmware shows on the device page
  and both show in the keypad editor and diagnostics. Quirk v9.
- Keypad editor: "Open device page" link.
- Sidebar entry renamed to "Control4 Keypads".

## 0.2.0 — 2026-10-10

- New keypad editor panel (sidebar **Control4 Keypads**, also opened by
  **Configure** on the integration). It has six rows, each with its own
  cap type, rows under a multi-row cap are disabled, and a live picture of
  the keypad updates as you edit. It replaces the cap-layout dropdown in the
  options dialog.
- Websocket API behind the panel: `control4_keypads/list`, `save` and `reset`.
  Layouts are checked on the server (rows tiled, rocker only in row 6,
  unique names, valid colours).
- Caps are single, double or triple (plus the up / down rocker in row 6);
  taller caps are rejected.
- Default names follow the row ("Button 3" for a cap starting in row 3).
- Manifest owner and links point at github.com/royceybaby/ha-c4-keypads.

## 0.1.0 — 2026-10-10

First release.

- Bundles the Control4 ZHA quirks (wmariz/zha-device-handlers `control4`,
  commit a8fc4de) plus SDAPD240 support (quirk v8): both loads, configurable
  cap layout, per-button keypad action and LED mode, HA-controlled RGB LEDs,
  hardware fade (`c4.dm.rtl`) and a raw-command endpoint.
- UI to configure each keypad's caps and buttons (replaces `c4_keypads.yaml`,
  which is imported on first setup).
- Services: `start_dimming`, `stop_dimming`, `send_command`.
- Blueprints: rocker dims a light; button LED shows an entity's state.
- Repair issues when ZHA isn't loading the bundled quirks.
