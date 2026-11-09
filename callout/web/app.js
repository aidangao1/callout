"use strict";
/* Callout window. Polls the Python side for a snapshot and sends it commands.
   Every button that trades goes through the same path as your voice:
   it sends "confirm", "cancel" or "flatten" to the engine. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

let api = null;
let state = {};
let settings = null;
let feed = [];
let feedVersion = -1;
let filter = "all";
let view = "trading";
let setupStep = 1;
let setupShown = false;
let orderKey = "";
let lastTest = "";
let capturingKey = false;
let toastTimer = null;

const bind = (name) => $$(`[data-bind="${name}"]`);
function setText(name, text) { for (const el of bind(name)) if (el.textContent !== text) el.textContent = text; }
function setHTML(name, html) { for (const el of bind(name)) if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } }
function show(name, on) { for (const el of bind(name)) el.hidden = !on; }

/* ---------------------------------------------------------------- boot */
function start(bridge) {
  if (api) return;
  api = bridge;
  poll();
  loadSettings();
  refreshMics();
}
window.addEventListener("pywebviewready", () => start(window.pywebview.api));
if (window.pywebview && window.pywebview.api) start(window.pywebview.api);

async function poll() {
  try {
    const s = await api.state(feedVersion);
    if (s) onState(s);
  } catch (e) {
    console.error(e);
  }
  setTimeout(poll, 120);
}

function onState(s) {
  state = s;
  if (!s.ready) return;
  if (s.feed) { feed = s.feed; feedVersion = s.feed_version; renderFeed(); }
  if (s.first_run && !setupShown) { setupShown = true; go("setup"); }
  renderHeader();
  renderRail();
  renderHeard();
  renderOrder();
  renderTalk();
  renderMini();
  renderLevels();
  renderLiveModal();
  renderTest();
  renderSetupLive();
}

/* ---------------------------------------------------------------- shared bits */
const primary = () => (state.instruments || [])[0] || null;

function badgeHTML(compact) {
  const acct = !compact && state.account ? ` <span class="acct">${esc(state.account)}</span>` : "";
  if (state.badge === "LIVE") return `<span class="badge live"><svg width="16" height="16" aria-hidden="true"><use href="#i-warn"/></svg>LIVE${compact ? "" : " · REAL MONEY"}${acct}</span>`;
  if (state.badge === "SIM") return `<span class="badge">${compact ? "SIM" : "SIMULATOR"}${acct}</span>`;
  return `<span class="badge">PAPER${acct}</span>`;
}

function connInfo() {
  if (state.live_locked) return { cls: "off", text: "Waiting for LIVE confirmation" };
  if (state.connected) return { cls: "", text: state.badge === "SIM" ? "Simulator connected" : "Connected to TWS" };
  if (state.connecting) return { cls: "wait", text: "Connecting…" };
  return { cls: "off", text: "Not connected" };
}

/* Spoken text says "E S"; the screen says "ES". */
function display(text) {
  let t = String(text || "");
  const insts = (state.instruments || []).slice().sort((a, b) => (b.label || "").length - (a.label || "").length);
  for (const i of insts) if (i.label && i.label !== i.symbol) t = t.split(i.label).join(i.symbol);
  return t;
}

function posParts(position) {
  const p = (position || "flat").toUpperCase().split(" ");
  return p;
}

/* ---------------------------------------------------------------- trading screen */
function renderHeader() {
  const c = connInfo();
  for (const d of bind("conn-dot")) d.className = "dot " + c.cls;
  setText("conn-text", c.text);
  for (const el of bind("badge")) {
    const compact = !!el.closest(".mini");
    const html = badgeHTML(compact);
    if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; }
  }
  setText("market", state.market_text || "");
  const p = primary();
  setText("contract", p && p.contract ? `${p.contract}${p.roll ? " · rolls " + p.roll : ""}` : "");
}

function renderRail() {
  const p = primary();
  const parts = posParts(p ? p.position : "flat");
  setHTML("pos-big", parts.map((w) => `<span>${esc(w)}</span>`).join(""));
  setText("pos-sub", p ? `${p.symbol}${p.contract ? " · " + p.contract : ""}` : "");
  setText("avg", p && p.avg ? p.avg.toFixed(2) : "—");
  setText("working", state.working == null ? "—" : String(state.working));
  setText("sizes", p ? `${p.quantity} · ${p.max}` : "—");
  const others = (state.instruments || []).slice(1)
    .map((i) => `<div class="other-inst"><span>${esc(i.symbol)}${i.contract ? " · " + esc(i.contract) : ""}</span><strong>${esc(i.position.toUpperCase())}</strong></div>`).join("");
  setHTML("other-insts", others);
  const older = state.older || [];
  show("older", older.length > 0);
  if (older.length) setText("older", `You also hold ${older.map((o) => `${o.position} ${o.contract}`).join(", ")} (older contract). Buy and sell are blocked until you flatten.`);
  for (const el of $$('.rail [data-setting="require_confirmation"]')) if (document.activeElement !== el) el.checked = !!state.confirm;
  for (const el of $$('.rail [data-setting="tts"]')) if (document.activeElement !== el) el.checked = !!state.tts;

  const alerts = [];
  if (state.broker_error && !state.connected && !state.live_locked)
    alerts.push(`<strong>Not connected.</strong><span>${esc(state.broker_error)}</span><button type="button" class="btn" data-go="settings-trading" data-scroll="connection">Connection settings</button>`);
  if (state.voice === "loading") alerts.push(`<strong>Loading voice…</strong><span class="muted">The first start downloads the speech model (about 40 MB).</span>`);
  if (state.voice === "error" || state.voice_error) alerts.push(`<strong>Voice problem.</strong><span>${esc(state.voice_error)}</span><button type="button" class="btn" data-go="settings-audio">Microphone settings</button>`);
  const n = state.leftover || 0;
  const banner = bind("leftover")[0];
  const bhtml = n ? `<svg width="22" height="22" aria-hidden="true"><use href="#i-warn"/></svg><span class="txt"><strong>${n} order${n > 1 ? "s" : ""} still working in TWS</strong><span>You're flat. If ${n > 1 ? "one" : "it"} fills, it opens a new position. Cancel ${n > 1 ? "them" : "it"} in TWS.</span></span>` : "";
  if (banner.dataset.html !== bhtml) { banner.innerHTML = bhtml; banner.dataset.html = bhtml; }
  banner.hidden = !n;

  const alert = bind("alert")[0];
  const html = alerts.join('<span style="flex-basis:100%"></span>');
  if (alert.dataset.html !== html) { alert.innerHTML = html; alert.dataset.html = html; }
  alert.hidden = alerts.length === 0;
}

function renderHeard() {
  const h = state.heard;
  setText("heard-text", h ? (h.text ? `"${h.text}"` : "(silence)") : "—");
  setText("heard-meta", h ? `confidence ${Number(h.confidence).toFixed(2)} · ${h.ms} ms` : "");
  setText("mic-name", state.mic ? `Mic · ${state.mic}` : state.voice === "loading" ? "Mic · starting" : "Mic · off");
}

function renderLevels() {
  const pct = Math.min(100, Math.round((state.level || 0) * 100));
  for (const el of bind("level")) el.style.width = pct + "%";
  for (const el of bind("talk-level")) el.style.width = pct + "%";
  let t;
  if (state.voice !== "ready") t = state.voice === "loading" ? "Starting the microphone…" : `Microphone not running. ${state.voice_error || ""}`;
  else t = `${pct}% · talk normally: the bar should reach the shaded band`;
  setText("level-text", t);
}

function orderHTML() {
  const s = state;
  const p = s.pending;
  const live = s.badge === "LIVE";
  const liveFlag = live ? `<span class="live-flag"><svg width="14" height="14" aria-hidden="true"><use href="#i-warn"/></svg>LIVE ACCOUNT</span>` : "";
  if (p) {
    const head = p.verb === "Flatten" ? `Flatten ${p.symbol === "all" ? "all" : p.symbol}` : `${p.verb} ${p.qty} ${p.symbol}`;
    const sub = p.verb === "Flatten" ? "Closes every position" : `${cap(p.from)} → ${cap(p.to)}`;
    return {
      key: `p|${head}|${sub}|${live}`,
      html: `<div class="order-top"><p class="label">Waiting for confirm</p>${liveFlag}<p class="hint"><span class="secs" data-secs></span> s left</p></div>
        <p class="headline">${esc(head)}</p>
        <p class="subline">${esc(sub)}</p>
        <div class="countdown" aria-hidden="true"><div data-cd></div></div>
        <div class="btnpair"><button type="button" class="btn primary big" data-cmd="confirm">CONFIRM · Enter</button><button type="button" class="btn big joined" data-cmd="cancel">Cancel · Esc</button></div>
        <p class="hint">or say "confirm" / "cancel"</p>`,
    };
  }
  const last = s.last || { kind: "idle", text: "" };
  const text = display(last.text);
  const icon = (id) => `<svg aria-hidden="true"><use href="#${id}"/></svg>`;
  let label, head, sub, small = false, mid = false, danger = false, ic = "";
  const m = text.match(/^Filled\. (Bought|Sold) (\d+) (\S+) at ([\d.]+|an unknown price)\. You're (.+)\.$/);
  const f = text.match(/^Flat\. (.+?)\.?$/);
  const w = last.kind === "flat_warn" ? last.working || 1 : 0;
  const closed = (text.match(/^Flat\. (.+?)\. Warning/) || [])[1];
  if (last.kind === "flat_warn" && (s.leftover || 0) > 0) {
    const n = s.leftover;
    label = "Flattened · check TWS"; head = "Warning"; ic = icon("i-warn"); mid = true; danger = true;
    sub = `You're flat, but ${n} order${n > 1 ? "s are" : " is"} still working in TWS. Cancel ${n > 1 ? "them" : "it"} there.`;
  }
  else if (last.kind === "flat_warn") {
    label = "Flattened"; head = "Flat"; ic = icon("i-check"); mid = true;
    sub = (closed ? `${closed} · ` : "") + "no orders left in TWS";
  }
  else if (last.kind === "filled" && m) { label = "Filled"; head = `${m[1]} ${m[2]} ${m[3]}`; sub = `at ${m[4]} · you're ${m[5]}`; ic = icon("i-check"); mid = true; }
  else if (last.kind === "filled" && f) { label = "Filled"; head = "Flat"; sub = f[1]; ic = icon("i-check"); }
  else if (last.kind === "rejected") { label = "Didn't catch that"; head = "Nothing sent"; small = true; sub = s.heard && s.heard.text ? `Heard "${s.heard.text}"` : text; }
  else if (last.kind === "blocked" || last.kind === "filled") {
    const parts = text.split(/(?<=\.)\s+/);
    label = last.kind === "filled" ? "Order" : "Blocked"; head = parts[0].replace(/\.$/, ""); sub = parts.slice(1).join(" "); small = true; ic = icon("i-warn");
  } else if (last.kind === "cancelled") { label = "Cancelled"; head = "Cancelled"; sub = text.replace(/^Cancelled\.?\s*/, ""); small = true; }
  else {
    label = s.connected ? "Ready" : "Waiting";
    const key = s.hotkey ? `Hold ${s.hotkey}` : "Hold the button";
    head = s.connected ? `${key} to talk` : "Not connected";
    sub = s.connected ? (text && text !== "Ready." ? text : 'Try "buy E S"') : (s.live_locked ? "Type LIVE to connect to your real account" : "Callout retries every few seconds");
    small = true;
  }
  return {
    key: `l|${label}|${head}|${sub}|${small}|${mid}|${danger}|${live}|${ic.length}`,
    html: `<div class="order-top"><p class="label">${esc(label)}</p>${liveFlag}</div>
      <div class="headline-row headline${small ? " small" : mid ? " mid" : ""}${danger ? " danger" : ""}">${ic}<span>${esc(head)}</span></div>
      ${sub ? `<p class="subline">${esc(sub)}</p>` : ""}`,
  };
}

function renderOrder() {
  const el = bind("order")[0];
  const o = orderHTML();
  if (o.key !== orderKey) { el.innerHTML = o.html; orderKey = o.key; }
  const p = state.pending;
  if (p) {
    const secs = $("[data-secs]", el);
    if (secs) secs.textContent = String(Math.ceil(p.left));
    const cd = $("[data-cd]", el);
    if (cd) cd.style.width = Math.max(0, (p.left / p.total) * 100) + "%";
  }
}

function renderTalk() {
  const ready = state.voice === "ready";
  for (const b of $$("[data-talk], [data-talk-small]")) {
    b.classList.toggle("on", !!state.listening);
    b.disabled = !ready;
  }
  setHTML("talk-title", state.listening ? "LISTENING…" : "HOLD<br>TO TALK");
  setText("talk-sub", state.listening ? "release to send" : !ready ? (state.voice === "loading" ? "voice is starting…" : "voice is off") : state.hotkey ? `or hold ${state.hotkey}` : "press and hold");
  show("talk-meter", !!state.listening);
  setText("mini-key", state.hotkey || "TALK");
}

function renderFeed() {
  const rows = feed.filter((r) => filter === "all" || r.cat === filter);
  const html = rows.length
    ? rows.map((r) => `<div class="row${r.strong ? " strong" : ""}"><span class="time">${esc(r.time)}</span><span class="kind">${esc(r.kind)}</span><span>${esc(display(r.text))}</span><span class="meta">${esc(r.meta)}</span></div>`).join("")
    : `<div class="empty">Nothing yet. Hold the talk key and say "buy E S".</div>`;
  setHTML("rows", html);
}

/* ---------------------------------------------------------------- mini mode */
function renderMini() {
  const p = primary();
  setText("mini-contract", p ? `${p.symbol}${p.contract ? " · " + p.contract : ""}` : "—");
  setHTML("mini-pos", posParts(p ? p.position : "flat").map(esc).join("<br>"));
  setText("mini-market", state.market_open ? "open" : "closed");
  const pend = state.pending;
  let msg;
  if (pend) msg = pend.verb === "Flatten" ? `Flatten? ${Math.ceil(pend.left)}s` : `${pend.verb} ${pend.qty} ${pend.symbol} · ${pend.from} → ${pend.to} · ${Math.ceil(pend.left)}s`;
  else if (state.leftover) msg = `${state.leftover} order${state.leftover > 1 ? "s" : ""} still working in TWS`;
  else msg = display(state.last && state.last.text) || (state.connected ? "Ready" : "Not connected");
  setText("mini-msg", msg);
  for (const el of bind("mini-msg")) el.classList.toggle("pending", !!pend || !!state.leftover);
  show("mini-actions", !pend);
  show("mini-confirm", !!pend);
}

/* ---------------------------------------------------------------- live unlock */
function renderLiveModal() { show("live-modal", !!state.live_locked); }

/* ---------------------------------------------------------------- settings */
async function loadSettings() {
  if (!api) return;
  settings = await api.settings();
  fillSettings();
}

const KEY_LABELS = { scroll_lock: "Scroll Lock", pause: "Pause", insert: "Insert", home: "Home", end: "End", page_up: "Page Up", page_down: "Page Down", ctrl_r: "Right Ctrl", ctrl_l: "Left Ctrl", alt_r: "Right Alt", alt_l: "Left Alt", shift_r: "Right Shift", shift_l: "Left Shift" };
const keyLabel = (k) => (!k || k === "enter" ? "Button only" : KEY_LABELS[k] || k.toUpperCase());

function fillSettings() {
  if (!settings) return;
  for (const el of $$("[data-setting]")) {
    const k = el.dataset.setting;
    if (!(k in settings) || document.activeElement === el) continue;
    if (el.type === "checkbox") el.checked = !!settings[k];
    else el.value = settings[k];
  }
  if (!capturingKey) {
    for (const el of bind("keycap")) { el.textContent = keyLabel(settings.push_to_talk); el.classList.remove("capturing"); }
  }
  setHTML("chips", (settings.decoys || []).map((d) =>
    `<span class="chip">${esc(d)}<button type="button" aria-label="Remove ${esc(d)}" data-remove-decoy="${esc(d)}"><svg width="14" height="14" aria-hidden="true"><use href="#i-x"/></svg></button></span>`).join("")
    + `<label><span class="sr">Add a word to ignore</span><input class="chip-add" placeholder="add a word, press Enter" data-add-decoy></label>`);
  for (const r of $$('input[name="conn-app"]')) r.checked = r.value === settings.app;
  for (const r of $$('input[name="conn-mode"]')) r.checked = r.value === settings.mode;
  const port = $('[data-conn="port"]');
  if (port && document.activeElement !== port) port.value = settings.port;
  updateLiveBox();
  setText("conn-current", `${settings.app === "tws" ? "TWS" : "IB Gateway"} · ${settings.mode} · port ${settings.port}`);
  show("sim-note", !!settings.sim);
  for (const sel of $$("[data-mic-select]")) sel.value = settings.input_device || "";
}

async function refreshMics() {
  if (!api) return;
  const mics = await api.mics();
  const opts = [`<option value="">Windows default</option>`]
    .concat(mics.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}${m.default ? " (default)" : ""}</option>`)).join("");
  for (const sel of $$("[data-mic-select]")) { sel.innerHTML = opts; sel.value = (settings && settings.input_device) || ""; }
}

async function applyPatch(patch, okText = "Saved") {
  const r = await api.apply(patch);
  if (r.ok) {
    toast(r.warnings && r.warnings.length ? r.warnings.join(" ") : okText, !!(r.warnings && r.warnings.length));
  } else {
    toast(r.error, true);
  }
  await loadSettings();
  return r;
}

function connChoice() {
  return {
    app: ($('input[name="conn-app"]:checked') || {}).value || "tws",
    mode: ($('input[name="conn-mode"]:checked') || {}).value || "paper",
    port: ($('[data-conn="port"]') || {}).value,
  };
}

function updateLiveBox() {
  const c = connChoice();
  show("live-box", c.mode === "live" && settings && settings.mode !== "live");
}

function renderTest() {
  const r = state.test_result;
  const key = JSON.stringify(r) + state.test_mode;
  if (key === lastTest) return;
  lastTest = key;
  let t;
  if (state.test_mode) t = `Now hold ${state.hotkey || "the Talk button"} and say a command…`;
  else if (r) t = r.ok ? `Heard "${r.text}" · would ${r.intent} · nothing traded` : `Heard "${r.text || "(silence)"}" · not a command, nothing would be sent`;
  else t = "Nothing is traded during a test.";
  setText("test-text", t);
}

/* ---------------------------------------------------------------- setup */
function renderSetup() {
  for (const li of $$("[data-step-nav]")) {
    if (Number(li.dataset.stepNav) === setupStep) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
  }
  for (const sec of $$("[data-step]")) sec.hidden = Number(sec.dataset.step) !== setupStep;
  setText("next-label", setupStep === 4 ? "FINISH" : "NEXT");
  const back = $('[data-action="setup-back"]');
  if (back) back.disabled = setupStep === 1;
}

function renderSetupLive() {
  if (view !== "setup") return;
  const p = primary();
  setText("practice-pos", p ? p.position.toUpperCase() : "—");
  setText("practice-last", display(state.last && state.last.text));
  setText("practice-note", state.badge === "LIVE" ? "You're connected to a LIVE account. Practice on paper first." : "");
}

/* ---------------------------------------------------------------- navigation */
function go(name, scrollTo) {
  const wasMini = view === "mini";
  view = name;
  for (const v of $$("[data-view]")) v.hidden = !v.dataset.view.split(" ").includes(name);
  for (const p of $$("[data-page]")) p.hidden = p.dataset.page !== name;
  let marked = false;
  for (const b of $$(".navrail button[data-go]")) {
    const on = !marked && b.dataset.go === name && !b.dataset.scroll;
    if (on) { b.setAttribute("aria-current", "page"); marked = true; } else b.removeAttribute("aria-current");
  }
  if (name === "mini" && !wasMini) api.set_mini(true);
  if (name !== "mini" && wasMini) api.set_mini(false);
  if (name.startsWith("settings")) { loadSettings(); refreshMics(); }
  if (name === "setup") { setupStep = 1; renderSetup(); loadSettings(); refreshMics(); }
  orderKey = "";
  if (scrollTo) setTimeout(() => { const t = document.getElementById(scrollTo); if (t) t.scrollIntoView(); }, 30);
  else window.scrollTo(0, 0);
}

function toast(text, bad) {
  const el = bind("toast")[0];
  el.textContent = text;
  el.classList.toggle("bad", !!bad);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), bad ? 6000 : 1800);
}

/* ---------------------------------------------------------------- input */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-go], [data-action], [data-cmd], [data-filter], [data-remove-decoy]");
  if (!t || t.disabled) return;
  if (t.dataset.go) return go(t.dataset.go, t.dataset.scroll);
  if (t.dataset.cmd) return api.command(t.dataset.cmd);
  if (t.dataset.filter) {
    filter = t.dataset.filter;
    for (const b of $$("[data-filter]")) b.setAttribute("aria-selected", String(b === t));
    return renderFeed();
  }
  if (t.dataset.removeDecoy) return applyPatch({ decoys: settings.decoys.filter((d) => d !== t.dataset.removeDecoy) });
  switch (t.dataset.action) {
    case "open-logs": return api.open_logs();
    case "refresh-mics": return refreshMics();
    case "test-command": lastTest = ""; return api.start_test();
    case "sample": return api.say_sample();
    case "capture-key":
      capturingKey = true;
      for (const el of bind("keycap")) { el.textContent = "Press a key…"; el.classList.add("capturing"); }
      return;
    case "no-key": return applyPatch({ push_to_talk: "" }, "Talk key removed. Use the on-screen button.");
    case "apply-connection": {
      const c = connChoice();
      const r = await applyPatch({ ...c, live_confirm: ($('[data-conn="live_confirm"]') || {}).value || "" }, "Connection saved. Reconnecting…");
      if (r.ok) { const lc = $('[data-conn="live_confirm"]'); if (lc) lc.value = ""; }
      return;
    }
    case "test-connection": {
      const c = connChoice();
      setText("conn-result", "Testing…");
      const r = await api.test_connection(c.app, c.mode, c.port);
      setText("conn-result", r.ok ? `Connected · ${r.badge.toLowerCase()} account ${r.account} · ${r.contract} found` : r.error);
      for (const el of bind("conn-result")) el.classList.toggle("bad", !r.ok);
      return;
    }
    case "setup-test": {
      setText("setup-result", "Testing…");
      const r = await api.test_connection(settings.app, settings.mode, settings.port);
      setHTML("setup-result", r.ok
        ? `<svg width="20" height="20" aria-hidden="true"><use href="#i-check"/></svg>Connected · ${esc(r.badge.toLowerCase())} account ${esc(r.account)} · ${esc(r.contract)} found`
        : `<svg width="20" height="20" aria-hidden="true"><use href="#i-warn"/></svg>${esc(r.error)}`);
      for (const el of bind("setup-result")) el.classList.toggle("bad", !r.ok);
      return;
    }
    case "setup-back": setupStep = Math.max(1, setupStep - 1); return renderSetup();
    case "setup-next":
      if (setupStep < 4) { setupStep += 1; return renderSetup(); }
      await api.finish_setup();
      return go("trading");
    case "setup-skip": await api.finish_setup(); return go("trading");
    case "unlock-live": {
      const r = await api.unlock_live(bind("live-input")[0].value);
      setText("live-error", r.ok ? "" : r.error);
      return;
    }
    case "use-paper": return applyPatch({ mode: "paper", app: (settings && settings.app) || "tws" }, "Switched to paper.");
  }
});

document.addEventListener("change", (e) => {
  const el = e.target;
  if (el.matches("[data-mic-select]")) return applyPatch({ input_device: el.value }, "Microphone changed");
  if (el.name === "conn-app" || el.name === "conn-mode") {
    const port = $('[data-conn="port"]');
    const c = connChoice();
    const ports = { "tws:paper": 7497, "tws:live": 7496, "gateway:paper": 4002, "gateway:live": 4001 };
    if (port) port.value = ports[`${c.app}:${c.mode}`];
    return updateLiveBox();
  }
  const s = el.closest("[data-setting]");
  if (!s) return;
  const k = s.dataset.setting;
  const v = s.type === "checkbox" ? s.checked : s.type === "number" || s.type === "range" ? Number(s.value) : s.value;
  applyPatch({ [k]: v });
});

function keyName(e) {
  if (/^F([1-9]|1[0-9]|20)$/.test(e.key)) return e.key.toLowerCase();
  const side = e.location === 2 ? "_r" : "_l";
  if (e.key === "Control") return "ctrl" + side;
  if (e.key === "Alt") return "alt" + side;
  if (e.key === "Shift") return "shift" + side;
  return { ScrollLock: "scroll_lock", Pause: "pause", Insert: "insert", Home: "home", End: "end", PageUp: "page_up", PageDown: "page_down" }[e.key] || null;
}

document.addEventListener("keydown", (e) => {
  if (capturingKey) {
    e.preventDefault();
    if (e.key === "Escape") { capturingKey = false; return fillSettings(); }
    const k = keyName(e);
    if (!k) return toast("Pick a key you don't type with: F1 to F20, Scroll Lock, Pause, Insert, or a right-side Ctrl/Alt/Shift.", true);
    capturingKey = false;
    return applyPatch({ push_to_talk: k }, `Talk key is now ${keyLabel(k)}`);
  }
  if (e.target.closest && e.target.closest("input, select, textarea")) {
    if (e.key === "Enter" && e.target.matches("[data-add-decoy]")) {
      const word = e.target.value.trim();
      if (word) applyPatch({ decoys: [...(settings.decoys || []), word] });
    }
    return;
  }
  if (!state.pending || !(view === "trading" || view === "mini")) return;
  if (e.key === "Enter") { e.preventDefault(); api.command("confirm"); }
  if (e.key === "Escape") { e.preventDefault(); api.command("cancel"); }
});

/* Hold to talk (the on-screen button does exactly what the hotkey does). */
for (const b of $$("[data-talk], [data-talk-small]")) {
  let down = false;
  const end = () => { if (down) { down = false; api.talk(false); } };
  b.addEventListener("pointerdown", (e) => { if (b.disabled) return; e.preventDefault(); b.setPointerCapture(e.pointerId); down = true; api.talk(true); });
  b.addEventListener("pointerup", end);
  b.addEventListener("pointercancel", end);
  b.addEventListener("lostpointercapture", end);
}

/* Hold to flatten: a stray click can't close a position. */
for (const b of $$('[data-hold="flatten"]')) {
  let timer = null;
  const cancel = () => { clearTimeout(timer); timer = null; b.classList.remove("holding"); };
  const begin = () => {
    if (timer) return;
    b.classList.add("holding");
    timer = setTimeout(() => { cancel(); api.command("flatten"); }, 900);
  };
  b.addEventListener("pointerdown", (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); begin(); });
  b.addEventListener("pointerup", cancel);
  b.addEventListener("pointercancel", cancel);
  b.addEventListener("lostpointercapture", cancel);
  b.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && !e.repeat) { e.preventDefault(); begin(); } });
  b.addEventListener("keyup", (e) => { if (e.key === "Enter" || e.key === " ") cancel(); });
}
