// Control4 Keypads — keypad editor panel.
// Six rows, top to bottom. Each row holds the top of a cap; rows under a
// multi-row cap are disabled. Saved through the control4_keypads/* websocket
// commands; the integration then reloads ZHA and the keypad gets its settings.

const ROWS = 6;
const ACTION_LABELS = {
  keep: "Keep current setting",
  none: "Nothing (HA only)",
  load1_toggle: "Toggle load 1",
  load1_on: "Load 1 on",
  load1_off: "Load 1 off",
  load2_toggle: "Toggle load 2",
  load2_on: "Load 2 on",
  load2_off: "Load 2 off",
};
const LED_LABELS = {
  keep: "Keep current setting",
  ha: "Home Assistant controls it",
  load1: "Shows load 1",
  load2: "Shows load 2",
};
const SIZE_LABELS = { 1: "Single", 2: "Double", 3: "Triple", 4: "Quad", 5: "5-row", 6: "Full height" };

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const isDefaultName = (n) => /^Button \d+$/.test(n || "") || n === "Dimmer";
const followsLoad = (led) => led === "load1" || led === "load2";

// "Button <row>" if free, else the lowest free "Button n".
function nextButtonName(caps, except, row) {
  const used = new Set(caps.filter((c) => c !== except).map((c) => (c.name || "").toLowerCase()));
  if (row && !used.has(`button ${row}`)) return `Button ${row}`;
  for (let i = 1; ; i++) if (!used.has(`button ${i}`)) return `Button ${i}`;
}

function newCap(start, caps) {
  return {
    start, size: 1, rocker: false, name: nextButtonName(caps, null, start),
    action: "keep", led: "keep", setcol: false, led_on: "#ffffff", led_off: "#000000",
  };
}

// Re-tile rows 1..6: keep caps in order, drop any that start under an earlier
// cap, fill empty rows with new single caps.
function normalize(caps) {
  const byStart = new Map(caps.map((c) => [c.start, c]));
  const out = [];
  let row = 1;
  while (row <= ROWS) {
    let cap = byStart.get(row);
    if (!cap) cap = newCap(row, [...out, ...caps.filter((c) => c.start > row)]);
    cap.size = Math.max(1, Math.min(cap.size, ROWS - row + 1));
    if (cap.rocker && row !== ROWS) cap.rocker = false;
    if (cap.rocker) cap.size = 1;
    out.push(cap);
    row += cap.size;
  }
  return out;
}

function defaultCaps() {
  const caps = [];
  for (let r = 1; r <= 5; r++) caps.push(newCap(r, caps));
  caps.push({ ...newCap(6, caps), rocker: true, name: "Dimmer" });
  return caps;
}

function capsFromButtons(buttons) {
  if (!Array.isArray(buttons) || !buttons.length) return defaultCaps();
  const caps = buttons
    .filter((b) => Array.isArray(b.slots) && b.slots.length)
    .map((b) => {
      const slots = [...b.slots].map(Number).sort((a, z) => a - z);
      return {
        start: slots[0],
        size: slots.length,
        rocker: b.type === "rocker",
        name: b.name || "",
        action: b.action || "keep",
        led: b.led || "keep",
        setcol: !!(b.led_on || b.led_off),
        led_on: "#" + (b.led_on || "ffffff"),
        led_off: "#" + (b.led_off || "000000"),
      };
    })
    .sort((a, z) => a.start - z.start);
  return normalize(caps);
}

function buttonsFromCaps(caps) {
  return caps.map((c) => {
    const b = { name: (c.name || "").trim(), slots: Array.from({ length: c.size }, (_, i) => c.start + i) };
    if (c.rocker) b.type = "rocker";
    if (c.action && c.action !== "keep") b.action = c.action;
    if (c.led && c.led !== "keep") b.led = c.led;
    if (c.setcol && followsLoad(c.led)) {
      b.led_on = c.led_on.replace("#", "").toLowerCase();
      b.led_off = c.led_off.replace("#", "").toLowerCase();
    }
    return b;
  });
}

const STYLE = `
  :host { display:block; min-height:100%; background:var(--primary-background-color); color:var(--primary-text-color);
          font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .toolbar { display:flex; align-items:center; gap:8px; height:56px; padding:0 12px; box-sizing:border-box;
             background:var(--app-header-background-color, var(--primary-color)); color:var(--app-header-text-color, #fff);
             border-bottom:var(--app-header-border-bottom, none); }
  .toolbar .title { font-size:20px; margin-left:8px; }
  .content { max-width:1180px; margin:0 auto; padding:16px; box-sizing:border-box; }
  .card { background:var(--card-background-color, #fff); border-radius:var(--ha-card-border-radius, 12px);
          border:1px solid var(--divider-color); padding:16px; margin-bottom:16px; }
  .top { display:flex; flex-wrap:wrap; gap:12px 24px; align-items:flex-end; }
  .top .meta { color:var(--secondary-text-color); font-size:14px; padding-bottom:8px; }
  .main { display:grid; grid-template-columns:220px 1fr; gap:20px; align-items:start; }
  .preview { position:sticky; top:12px; text-align:center; }
  .preview svg { width:100%; max-width:220px; height:auto; }
  .preview .help { color:var(--secondary-text-color); font-size:12px; margin-top:6px; }
  .plate { fill:var(--secondary-background-color, #eee); stroke:var(--divider-color); }
  .cap { fill:var(--card-background-color, #fff); stroke:var(--divider-color); stroke-width:1.5; cursor:pointer; }
  .cap.sel { stroke:var(--primary-color); stroke-width:3; }
  .capname { font-size:11px; fill:var(--primary-text-color); pointer-events:none; }
  .rownum-svg { font-size:10px; fill:var(--secondary-text-color); }
  .rows { display:flex; flex-direction:column; gap:8px; }
  .row { display:grid; grid-template-columns:44px minmax(150px,190px) minmax(140px,1fr) minmax(170px,210px) minmax(170px,210px);
         gap:8px 12px; align-items:end; padding:10px 12px; border-radius:10px; border:1px solid var(--divider-color);
         background:var(--card-background-color, #fff); }
  .row.sel { border-color:var(--primary-color); box-shadow:0 0 0 1px var(--primary-color) inset; }
  .row.covered { opacity:.55; }
  .rownum { font-weight:500; font-size:15px; align-self:center; color:var(--secondary-text-color); }
  .field { display:flex; flex-direction:column; gap:4px; min-width:0; }
  .field label { font-size:12px; color:var(--secondary-text-color); }
  select, input[type=text] { height:38px; padding:0 10px; border-radius:8px; border:1px solid var(--divider-color);
         background:var(--card-background-color, #fff); color:var(--primary-text-color); font-size:14px; min-width:0; box-sizing:border-box; width:100%; }
  select:disabled { background:transparent; }
  select:focus, input:focus { outline:2px solid var(--primary-color); outline-offset:-1px; }
  .extra { grid-column:2 / -1; display:flex; flex-wrap:wrap; gap:8px 20px; align-items:center; font-size:13px; color:var(--secondary-text-color); }
  .extra label { display:flex; align-items:center; gap:6px; }
  input[type=color] { width:44px; height:28px; padding:0; border:1px solid var(--divider-color); border-radius:6px; background:none; }
  .footer { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:flex-end; margin-top:16px; }
  .footer .msg { margin-right:auto; font-size:14px; }
  .msg.ok { color:var(--success-color, #2e7d32); } .msg.err { color:var(--error-color, #c62828); } .msg.info { color:var(--secondary-text-color); }
  button { height:38px; padding:0 18px; border-radius:19px; font-size:14px; font-weight:500; cursor:pointer;
           border:1px solid var(--divider-color); background:transparent; color:var(--primary-color); }
  button.primary { background:var(--primary-color); color:var(--text-primary-color, #fff); border-color:var(--primary-color); }
  button.danger { color:var(--error-color, #c62828); }
  button:disabled { opacity:.45; cursor:default; }
  .notice { padding:12px 16px; border-radius:10px; background:var(--warning-color, #ffa600); color:#000; margin-bottom:16px; }
  @media (max-width: 900px) {
    .main { grid-template-columns:1fr; }
    .preview { position:static; }
    .preview svg { max-width:150px; }
    .row { grid-template-columns:36px 1fr; }
    .row .field { grid-column:2; }
    .extra { grid-column:2; }
  }
`;

class Control4KeypadsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._ieee = null;
    this._caps = null;
    this._savedJson = null;
    this._focus = 1;
    this._msg = null;
    this._busy = false;
    this._confirmReset = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._load();
  }
  get hass() { return this._hass; }
  set narrow(v) { this._narrow = v; if (this._menu) this._menu.narrow = v; }
  set panel(v) { this._panel = v; }

  connectedCallback() { this._render(); }

  async _load(keepSelection) {
    try {
      this._data = await this._hass.callWS({ type: "control4_keypads/list" });
      const list = this._data.keypads;
      if (!list.length) { this._ieee = null; this._caps = null; }
      else {
        const pick = keepSelection && list.find((k) => k.ieee === this._ieee) ? this._ieee : list[0].ieee;
        this._selectKeypad(pick);
      }
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._render();
  }

  _keypad() { return this._data?.keypads.find((k) => k.ieee === this._ieee); }

  _selectKeypad(ieee) {
    this._ieee = ieee;
    const kp = this._keypad();
    this._caps = capsFromButtons(kp?.buttons);
    this._savedJson = kp?.buttons ? JSON.stringify(buttonsFromCaps(capsFromButtons(kp.buttons))) : null;
    this._focus = 1;
    this._confirmReset = false;
  }

  get _dirty() {
    if (!this._caps) return false;
    return JSON.stringify(buttonsFromCaps(this._caps)) !== this._savedJson;
  }

  _capAt(row) { return this._caps.find((c) => row >= c.start && row < c.start + c.size); }

  // ---- rendering --------------------------------------------------------

  _render() {
    const root = this.shadowRoot;
    const d = this._data;
    let body;
    if (this._error) body = `<div class="card"><div class="msg err">Couldn't load keypads: ${esc(this._error)}</div></div>`;
    else if (!d) body = `<div class="card">Loading…</div>`;
    else if (!d.configured) body = `<div class="card">Add the Control4 Keypads integration first (Settings → Devices &amp; services).</div>`;
    else if (!d.keypads.length) body = `<div class="card">No supported Control4 keypads found in ZHA. Pair a keypad with ZHA, then come back.</div>`;
    else body = this._renderEditor();

    root.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar"><span id="menu"></span><div class="title">Control4 Keypads</div></div>
      <div class="content">${body}</div>`;

    const slot = root.getElementById("menu");
    if (customElements.get("ha-menu-button")) {
      this._menu = document.createElement("ha-menu-button");
      this._menu.hass = this._hass;
      this._menu.narrow = this._narrow;
      slot.appendChild(this._menu);
    }
    this._bind();
  }

  _renderEditor() {
    const d = this._data;
    const kp = this._keypad();
    const notice = d.quirk_loaded ? "" :
      `<div class="notice">ZHA isn't loading the Control4 quirks from this integration, so these settings won't reach the keypad. See Settings → System → Repairs.</div>`;
    const options = d.keypads.map((k) =>
      `<option value="${esc(k.ieee)}" ${k.ieee === this._ieee ? "selected" : ""}>${esc(k.area ? `${k.area} – ${k.name}` : k.name)}</option>`).join("");
    const rows = [];
    for (let r = 1; r <= ROWS; r++) rows.push(this._renderRow(r));
    return `${notice}
      <div class="card top">
        <div class="field" style="min-width:260px;flex:1;max-width:420px"><label>Keypad</label>
          <select id="keypad" ${this._dirty ? "disabled" : ""}>${options}</select></div>
        <div class="meta">${esc(kp.model)} · ${esc(kp.ieee)}${kp.buttons ? "" : " · not configured yet (showing the default layout)"}</div>
      </div>
      <div class="main">
        <div class="card preview"><div id="preview">${this._renderPreview()}</div>
          <div class="help">Top to bottom, as fitted. Click a cap to edit it.</div></div>
        <div>
          <div class="rows">${rows.join("")}</div>
          <div class="footer">${this._renderFooter()}</div>
        </div>
      </div>`;
  }

  _renderFooter() {
    const kp = this._keypad();
    const m = this._msg;
    const msg = m ? `<span class="msg ${m.type}">${esc(m.text)}</span>`
      : this._dirty ? `<span class="msg info">Unsaved changes</span>` : `<span class="msg"></span>`;
    return `${msg}
      ${kp?.buttons ? `<button class="danger" id="reset" ${this._busy ? "disabled" : ""}>${this._confirmReset ? "Click again to forget" : "Forget settings"}</button>` : ""}
      <button id="discard" ${!this._dirty || this._busy ? "disabled" : ""}>Discard</button>
      <button class="primary" id="save" ${!this._dirty || this._busy ? "disabled" : ""}>${this._busy ? "Saving…" : "Save"}</button>`;
  }

  _renderRow(r) {
    const cap = this._capAt(r);
    const sel = cap.start === this._focus ? " sel" : "";
    if (cap.start !== r) {
      return `<div class="row covered${sel}" data-start="${cap.start}">
        <div class="rownum">${r}</div>
        <div class="field"><label>Cap</label><select disabled><option>Covered by row ${cap.start}</option></select></div>
        <div class="field"><label>&nbsp;</label><div style="height:38px;display:flex;align-items:center;color:var(--secondary-text-color)">Part of “${esc(cap.name)}”</div></div>
      </div>`;
    }
    const sizes = [];
    for (let s = 1; s <= ROWS - r + 1; s++) {
      const label = s === 1 ? "Single" : `${SIZE_LABELS[s]} (rows ${r}–${r + s - 1})`;
      sizes.push(`<option value="${s}" ${!cap.rocker && cap.size === s ? "selected" : ""}>${label}</option>`);
    }
    if (r === ROWS) sizes.push(`<option value="R" ${cap.rocker ? "selected" : ""}>Rocker (up / down)</option>`);
    const opt = (labels, value) => Object.entries(labels)
      .map(([k, v]) => `<option value="${k}" ${k === value ? "selected" : ""}>${esc(v)}</option>`).join("");
    const extras = [];
    if (cap.rocker) extras.push(`<span>Automation triggers: “${esc(cap.name.trim())} up” and “${esc(cap.name.trim())} down”</span>`);
    if (followsLoad(cap.led)) {
      extras.push(`<label><input type="checkbox" data-start="${r}" data-field="setcol" ${cap.setcol ? "checked" : ""}> Set LED colours</label>`);
      if (cap.setcol) {
        extras.push(`<label>On <input type="color" data-start="${r}" data-field="led_on" value="${esc(cap.led_on)}"></label>`);
        extras.push(`<label>Off <input type="color" data-start="${r}" data-field="led_off" value="${esc(cap.led_off)}"></label>`);
      } else extras.push(`<span>(keeps the keypad's own colours)</span>`);
    }
    return `<div class="row${sel}" data-start="${r}">
      <div class="rownum">${r}</div>
      <div class="field"><label>Cap</label><select data-start="${r}" data-field="size">${sizes.join("")}</select></div>
      <div class="field"><label>Name</label><input type="text" data-start="${r}" data-field="name" value="${esc(cap.name)}" maxlength="40"></div>
      <div class="field"><label>Pressing it on the keypad</label><select data-start="${r}" data-field="action">${opt(ACTION_LABELS, cap.action)}</select></div>
      <div class="field"><label>LED</label><select data-start="${r}" data-field="led">${opt(LED_LABELS, cap.led)}</select></div>
      ${extras.length ? `<div class="extra">${extras.join("")}</div>` : ""}
    </div>`;
  }

  _renderPreview() {
    const RH = 46, GUT = 18, W = 170, TOP = 14, PAD = 12;
    const H = TOP * 2 + ROWS * RH;
    const x0 = GUT + PAD, w = W - GUT - 2 * PAD;
    const parts = [`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Keypad preview">`,
      `<rect class="plate" x="${GUT}" y="2" width="${W - GUT - 2}" height="${H - 4}" rx="12"/>`];
    for (let r = 1; r <= ROWS; r++) {
      parts.push(`<text class="rownum-svg" x="${GUT / 2}" y="${TOP + (r - 0.5) * RH + 3}" text-anchor="middle">${r}</text>`);
    }
    for (const c of this._caps) {
      const y = TOP + (c.start - 1) * RH + 3, h = c.size * RH - 6;
      const sel = c.start === this._focus ? " sel" : "";
      const name = esc(c.name.length > 18 ? c.name.slice(0, 17) + "…" : c.name);
      const ledFill = c.led === "ha" ? "var(--primary-color)"
        : followsLoad(c.led) ? (c.setcol ? c.led_on : "#ffffff") : "none";
      const led = (cx, cy) => `<circle cx="${cx}" cy="${cy}" r="3.5" fill="${ledFill}" stroke="var(--secondary-text-color)" stroke-width="${ledFill === "none" ? 1 : 0.5}" pointer-events="none"/>`;
      if (c.rocker) {
        const half = (w - 4) / 2;
        parts.push(`<rect class="cap${sel}" data-start="${c.start}" x="${x0}" y="${y}" width="${half}" height="${h}" rx="6"/>`);
        parts.push(`<rect class="cap${sel}" data-start="${c.start}" x="${x0 + half + 4}" y="${y}" width="${half}" height="${h}" rx="6"/>`);
        parts.push(`<text class="capname" x="${x0 + half / 2}" y="${y + h / 2}" text-anchor="middle">▼</text>`);
        parts.push(`<text class="capname" x="${x0 + half * 1.5 + 4}" y="${y + h / 2}" text-anchor="middle">▲</text>`);
        parts.push(`<text class="capname" x="${x0 + w / 2}" y="${y + h - 6}" text-anchor="middle" style="font-size:8px">${name}</text>`);
        parts.push(led(x0 + 8, y + 8));
      } else {
        parts.push(`<rect class="cap${sel}" data-start="${c.start}" x="${x0}" y="${y}" width="${w}" height="${h}" rx="6"/>`);
        parts.push(`<text class="capname" x="${x0 + w / 2 + 4}" y="${y + h / 2 + 4}" text-anchor="middle">${name}</text>`);
        parts.push(led(x0 + 10, y + h / 2));
      }
    }
    parts.push("</svg>");
    return parts.join("");
  }

  _refreshPartial() {
    const root = this.shadowRoot;
    const p = root.getElementById("preview");
    if (p) p.innerHTML = this._renderPreview();
    const f = root.querySelector(".footer");
    if (f) f.innerHTML = this._renderFooter();
    const k = root.getElementById("keypad");
    if (k) k.disabled = this._dirty;
  }

  // ---- events -----------------------------------------------------------

  _bind() {
    // ShadowRoot has no on* handler properties; listen once, delegate by target.
    if (this._bound) return;
    this._bound = true;
    const root = this.shadowRoot;
    root.addEventListener("change", (ev) => this._onChange(ev));
    root.addEventListener("input", (ev) => this._onInput(ev));
    root.addEventListener("click", (ev) => this._onClick(ev));
  }

  _onInput(ev) {
    const t = ev.target;
    if (t.dataset?.field !== "name") return;
    const cap = this._caps.find((c) => c.start === Number(t.dataset.start));
    cap.name = t.value;
    this._msg = null;
    this._refreshPartial();
  }

  _onChange(ev) {
    const t = ev.target;
    if (t.id === "keypad") {
      this._selectKeypad(t.value);
      this._msg = null;
      this._render();
      return;
    }
    const field = t.dataset?.field;
    if (!field || field === "name") return;
    const start = Number(t.dataset.start);
    const cap = this._caps.find((c) => c.start === start);
    this._msg = null;
    this._focus = start;
    if (field === "size") {
      if (t.value === "R") {
        cap.rocker = true; cap.size = 1;
        if (isDefaultName(cap.name)) cap.name = "Dimmer";
      } else {
        const wasRocker = cap.rocker;
        cap.rocker = false; cap.size = Number(t.value);
        if (wasRocker && cap.name === "Dimmer") cap.name = nextButtonName(this._caps, cap, cap.start);
      }
      this._caps = normalize(this._caps);
    } else if (field === "setcol") cap.setcol = t.checked;
    else if (field === "led_on" || field === "led_off") cap[field] = t.value;
    else cap[field] = t.value;
    this._render();
  }

  _onClick(ev) {
    const path = ev.composedPath();
    const btn = path.find((el) => el.tagName === "BUTTON");
    if (btn?.id === "save") return this._save();
    if (btn?.id === "discard") { this._selectKeypad(this._ieee); this._msg = null; return this._render(); }
    if (btn?.id === "reset") return this._reset();
    const capEl = path.find((el) => el.classList?.contains("cap"));
    if (capEl) {
      this._focus = Number(capEl.dataset.start);
      this._render();
      this.shadowRoot.querySelector(`.row[data-start="${this._focus}"] input, .row[data-start="${this._focus}"] select`)?.focus();
    }
  }

  async _save() {
    const buttons = buttonsFromCaps(this._caps);
    const names = buttons.map((b) => b.name.toLowerCase());
    if (names.some((n) => !n)) { this._msg = { type: "err", text: "Every cap needs a name." }; return this._refreshPartial(); }
    if (new Set(names).size !== names.length) { this._msg = { type: "err", text: "Each cap needs a different name." }; return this._refreshPartial(); }
    this._busy = true; this._refreshPartial();
    try {
      const res = await this._hass.callWS({ type: "control4_keypads/save", ieee: this._ieee, buttons });
      const kp = this._keypad();
      kp.buttons = res.buttons;
      this._savedJson = JSON.stringify(buttonsFromCaps(capsFromButtons(res.buttons)));
      this._msg = res.changed
        ? { type: "ok", text: "Saved. ZHA is reloading; the keypad gets its new settings in about 15 seconds." }
        : { type: "ok", text: "Saved (no changes)." };
    } catch (err) {
      this._msg = { type: "err", text: err.message || String(err) };
    }
    this._busy = false;
    this._render();
  }

  async _reset() {
    if (!this._confirmReset) { this._confirmReset = true; return this._refreshPartial(); }
    this._busy = true; this._refreshPartial();
    try {
      await this._hass.callWS({ type: "control4_keypads/reset", ieee: this._ieee });
      this._keypad().buttons = null;
      this._selectKeypad(this._ieee);
      this._msg = { type: "ok", text: "Settings forgotten. The keypad uses the default layout after ZHA reloads." };
    } catch (err) {
      this._msg = { type: "err", text: err.message || String(err) };
    }
    this._busy = false; this._confirmReset = false;
    this._render();
  }
}

if (!customElements.get("control4-keypads-panel")) {
  customElements.define("control4-keypads-panel", Control4KeypadsPanel);
}

// For tests (node): expose the pure helpers.
if (typeof globalThis !== "undefined") {
  globalThis.__c4kp = { normalize, capsFromButtons, buttonsFromCaps, defaultCaps };
}
