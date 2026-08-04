"use strict";

let state = { items: [], owner: "All", search: "", role: null, name: null, statusFilter: null };

// Labels for the clickable dashboard cards, and how each one matches an item.
const STAT_FILTERS = {
  out: { label: "Out of stock", match: (it) => it.status === "out" },
  low: { label: "Running low", match: (it) => it.status === "low" },
  shared: { label: "Shared", match: (it) => it.owner === "Shared" },
  ordered: { label: "Ordered", match: (it) => it.ordered },
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const isAdmin = () => state.role === "admin";

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (res.status === 401) { showLogin(); throw new Error("Please sign in"); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Request failed (${res.status})`);
  }
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

const STATUS_LABEL = {
  out: "Out of stock", low: "Running low", overdue: "Overdue", due: "Due today",
  soon: "Coming up", ordered: "Ordered", ok: "On track",
};

function whenText(it) {
  if (it.days_until < 0) return `${Math.abs(it.days_until)} day(s) overdue`;
  if (it.days_until === 0) return "due today";
  return `due in ${it.days_until} day(s)`;
}

// ---- auth ----
async function populateLoginNames() {
  const sel = $("#loginName");
  try {
    const data = await api("GET", "/api/users");
    // keep the placeholder, add one option per name
    for (const name of data.users) {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = name;
      sel.append(o);
    }
  } catch (e) { /* leave placeholder only */ }
}

async function showLogin() {
  $("#app").hidden = true;
  $("#login").hidden = false;
  const sel = $("#loginName");
  if (sel.options.length <= 1) await populateLoginNames();
  sel.focus();
}

function showApp() {
  $("#login").hidden = true;
  $("#app").hidden = false;
  document.body.classList.toggle("role-admin", isAdmin());
  document.body.classList.toggle("role-staff", !isAdmin());
  const badge = $("#roleBadge");
  badge.textContent = `${state.name} · ${isAdmin() ? "Admin" : "Staff"}`;
  badge.className = "role-badge " + (isAdmin() ? "admin" : "staff");
}

async function checkSession() {
  const me = await api("GET", "/api/me").catch(() => ({ role: null }));
  if (me.role) {
    state.role = me.role;
    state.name = me.name;
    showApp();
    await load();
  } else {
    showLogin();
  }
}

async function login(e) {
  e.preventDefault();
  $("#loginError").hidden = true;
  const name = $("#loginName").value;
  if (!name) {
    const box = $("#loginError");
    box.textContent = "Please select your name.";
    box.hidden = false;
    return;
  }
  try {
    const r = await api("POST", "/api/login", { name });
    state.role = r.role;
    state.name = r.name;
    showApp();
    await load();
  } catch (err) {
    const box = $("#loginError");
    box.textContent = err.message;
    box.hidden = false;
  }
}

async function logout() {
  await api("POST", "/api/logout").catch(() => {});
  state.role = null;
  showLogin();
}

// ---- render ----
function render() {
  const list = $("#list");
  list.innerHTML = "";

  let items = state.items;
  if (state.owner !== "All") items = items.filter((i) => i.owner === state.owner);
  if (state.statusFilter) items = items.filter(STAT_FILTERS[state.statusFilter].match);
  if (state.search) {
    const q = state.search.toLowerCase();
    items = items.filter((i) => (i.name + " " + i.category).toLowerCase().includes(q));
  }

  renderFilterBanner();
  $("#empty").hidden = items.length > 0;
  $("#empty").innerHTML = state.statusFilter
    ? `No items under <b>${STAT_FILTERS[state.statusFilter].label}</b>.`
    : 'No items yet. Click <b>＋ Add item</b> to get started.';

  for (const it of items) {
    const card = el("div", `card ${it.status}`);

    const main = el("div", "card-main");
    const title = el("div", "card-title");
    title.append(el("span", "name", it.name));
    if (it.brand) title.append(el("span", "brand-tag", it.brand));
    title.append(el("span", `owner-badge ${it.owner}`, it.owner));
    if (it.ordered) title.append(el("span", "ordered-badge", "🛒 Ordered"));
    main.append(title);

    const metaBits = [];
    let stock;
    if (it.is_empty && it.status === "out") stock = `<span class="qty-empty">⚠ EMPTY — restock now</span>`;
    else if (it.quantity) stock = `<span class="qty-strong">${it.quantity} ${it.unit || ""}</span> on hand`;
    else stock = `<span class="muted">stock not set</span>`;
    metaBits.push(stock);
    if (it.quantity_needed) metaBits.push(`<span class="qty-needed">needs ${it.quantity_needed}</span>`);
    if (it.category) metaBits.push(it.category);
    metaBits.push(`every ${it.cadence_days}d`);
    metaBits.push(`next: ${it.next_due}`);
    main.append(el("div", "card-meta", metaBits.join(' <span class="dot">·</span> ')));

    // Notes — admin only. textContent avoids any HTML injection from note text.
    if (isAdmin() && it.notes) {
      const note = el("div", "card-note");
      note.textContent = "📝 " + it.notes;
      main.append(note);
    }

    // Adaptive suggestion — admin only
    if (it.suggestion && isAdmin()) {
      const s = el("div", "suggestion admin-only");
      s.append(el("span", "grow",
        `💡 <b>${it.name}</b>: change schedule from every ${it.suggestion.from_cadence}d ` +
        `to every ${it.suggestion.to_cadence}d?<br><span style="opacity:.8">${it.suggestion.reason}</span>`));
      const approve = el("button", "btn small primary", "Approve");
      approve.onclick = () => act(it.id, "apply-suggestion", "Schedule updated");
      const dismiss = el("button", "btn small ghost", "Dismiss");
      dismiss.onclick = () => act(it.id, "dismiss-suggestion", "Suggestion dismissed");
      s.append(approve, dismiss);
      main.append(s);
    }

    // The pill always shows the item's real status; the 🛒 Ordered badge (added
    // above) is what indicates an order is on the way.
    let pillText;
    if (it.status === "out") pillText = it.is_empty ? "Empty · restock now" : "Out of stock";
    else pillText = `${STATUS_LABEL[it.status]} · ${whenText(it)}`;
    const pill = el("span", `status-pill ${it.status}`, pillText);

    // Actions — some are admin-only
    const actions = el("div", "card-actions");
    const stockBtn = el("button", "btn small", "📦 Stock");
    stockBtn.onclick = () => openStock(it);
    actions.append(stockBtn);
    if (isAdmin()) {
      actions.append(buildStatusMenu(it));  // Status is admin-only
    } else {
      const low = el("button", "btn small", "⚠ Flag low");  // Flag low is staff-only
      low.onclick = () => act(it.id, "flag-low", `${it.name} flagged as low`);
      actions.append(low);
    }

    if (isAdmin()) {
      const edit = el("button", "btn small ghost", "Edit");
      edit.onclick = () => openEdit(it);
      const del = el("button", "btn small danger", "Delete");
      del.onclick = () => removeItem(it);
      actions.append(edit, del);
    }

    card.append(main, pill, actions);
    list.append(card);
  }

  renderStats();
}

// A "Status ▾" dropdown replacing the old single Restocked button.
const STATE_OPTIONS = [
  { state: "out_of_stock", label: "⛔ Out of stock", done: "marked out of stock" },
  { state: "ordered", label: "🛒 Ordered", done: "marked as ordered" },
  { state: "restocked", label: "✓ Restocked", done: "marked restocked" },
];

function buildStatusMenu(it) {
  const wrap = el("div", "dropdown");
  const toggle = el("button", "btn small primary dropdown-toggle", "Status ▾");
  const menu = el("div", "dropdown-menu");
  menu.hidden = true;
  for (const opt of STATE_OPTIONS) {
    const b = el("button", "dropdown-item", opt.label);
    b.onclick = (e) => {
      e.stopPropagation();
      menu.hidden = true;
      setState(it.id, opt.state, `${it.name} ${opt.done}`);
    };
    menu.append(b);
  }
  toggle.onclick = (e) => {
    e.stopPropagation();
    const wasOpen = !menu.hidden;
    closeAllMenus();
    menu.hidden = wasOpen;
  };
  wrap.append(toggle, menu);
  return wrap;
}

function closeAllMenus() {
  document.querySelectorAll(".dropdown-menu").forEach((m) => (m.hidden = true));
}

async function setState(id, stateValue, msg) {
  try {
    await api("POST", `/api/items/${id}/state`, { state: stateValue });
    await load();
    toast(msg);
  } catch (e) { toast(e.message); }
}

function renderStats() {
  const counts = { out: 0, low: 0, shared: 0, ordered: 0 };
  for (const it of state.items) {
    if (counts[it.status] != null) counts[it.status]++;      // out / low
    if (it.owner === "Shared") counts.shared++;              // shared items
    if (it.ordered) counts.ordered++;                        // ordered items
  }
  const defs = [["out", "Out of stock"], ["low", "Running low"],
                ["shared", "Shared"], ["ordered", "Ordered"]];
  const stats = $("#stats");
  stats.innerHTML = "";
  for (const [key, label] of defs) {
    const active = state.statusFilter === key;
    const s = el("div", `stat ${key}${active ? " active" : ""}`);
    s.append(el("div", "num", String(counts[key])));
    s.append(el("div", "lbl", label));
    s.setAttribute("role", "button");
    s.setAttribute("tabindex", "0");
    s.onclick = () => setStatusFilter(key);
    s.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setStatusFilter(key); } };
    stats.append(s);
  }
}

function setStatusFilter(key) {
  state.statusFilter = state.statusFilter === key ? null : key;  // click again to clear
  render();
}

function renderFilterBanner() {
  const banner = $("#filterBanner");
  if (!state.statusFilter) { banner.hidden = true; return; }
  banner.innerHTML = "";
  banner.append(el("span", "", `Showing <b>${STAT_FILTERS[state.statusFilter].label}</b>`));
  const clear = el("button", "btn small ghost", "✕ Show all");
  clear.onclick = () => setStatusFilter(state.statusFilter);
  banner.append(clear);
  banner.hidden = false;
}

async function load() {
  const data = await api("GET", "/api/items");
  state.items = data.items;
  render();
}

async function act(id, action, msg) {
  try { await api("POST", `/api/items/${id}/${action}`); await load(); toast(msg); }
  catch (e) { toast(e.message); }
}

async function removeItem(it) {
  if (!confirm(`Delete "${it.name}"? This removes it from the list.`)) return;
  await api("DELETE", `/api/items/${it.id}`);
  await load();
  toast(`${it.name} deleted`);
}

// ---- add / edit modal ----
// Admin can assign any owner; staff can only pick themselves or Shared.
function populateOwnerSelect(selected) {
  const sel = $("#itemForm").owner;
  const owners = isAdmin() ? ["Shared", "Eddie", "Danilo"] : [state.name, "Shared"];
  sel.innerHTML = "";
  for (const o of owners) {
    const opt = document.createElement("option");
    opt.value = o; opt.textContent = o;
    sel.append(opt);
  }
  if (selected) sel.value = selected;
}

function openAdd() {
  $("#modalTitle").textContent = "Add item";
  const f = $("#itemForm");
  f.reset();
  f.id.value = "";
  populateOwnerSelect(isAdmin() ? "Shared" : state.name);
  f.last_restocked.value = new Date().toISOString().slice(0, 10);
  $("#scanBtn").hidden = false;  // scanning is for adding new items
  $("#modal").hidden = false;
  f.name.focus();
}

function openEdit(it) {
  $("#modalTitle").textContent = "Edit item";
  const f = $("#itemForm");
  $("#scanBtn").hidden = true;
  f.id.value = it.id;
  f.name.value = it.name;
  populateOwnerSelect(it.owner);
  f.owner.value = it.owner;
  f.category.value = it.category || "";
  f.brand.value = it.brand || "";
  f.quantity.value = it.quantity || "";
  f.unit.value = it.unit || "";
  f.quantity_needed.value = it.quantity_needed || "";
  f.cadence_days.value = it.cadence_days;
  f.last_restocked.value = it.last_restocked;
  f.notes.value = it.notes || "";
  $("#modal").hidden = false;
}

async function saveItem(e) {
  e.preventDefault();
  const f = $("#itemForm");
  const data = {
    name: f.name.value, owner: f.owner.value, category: f.category.value,
    brand: f.brand.value, quantity: f.quantity.value, unit: f.unit.value,
    quantity_needed: f.quantity_needed.value,
    cadence_days: f.cadence_days.value, last_restocked: f.last_restocked.value,
    notes: f.notes.value,
  };
  try {
    if (f.id.value) await api("PUT", `/api/items/${f.id.value}`, data);
    else await api("POST", "/api/items", data);
    $("#modal").hidden = true;
    await load();
    toast("Saved");
  } catch (err) { toast(err.message); }
}

// ---- barcode / QR scanner (auto-fill the add form) ----
let _scanLibLoading = null;
let _scanner = null;

function loadScannerLib() {
  if (window.Html5Qrcode) return Promise.resolve();
  if (_scanLibLoading) return _scanLibLoading;
  _scanLibLoading = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js";
    s.onload = resolve;
    s.onerror = () => { _scanLibLoading = null; reject(new Error("load failed")); };
    document.head.appendChild(s);
  });
  return _scanLibLoading;
}

async function openScanner() {
  $("#scanStatus").textContent = "Starting camera…";
  $("#scanModal").hidden = false;
  try {
    await loadScannerLib();
  } catch (e) {
    $("#scanStatus").textContent = "Couldn't load the scanner — check your connection and try again.";
    return;
  }
  try {
    // Explicitly support common 1D barcodes (not just QR) + use the fast native
    // detector when the browser has it, so bottle/product barcodes actually read.
    const F = window.Html5QrcodeSupportedFormats || {};
    const formats = ["QR_CODE", "EAN_13", "EAN_8", "UPC_A", "UPC_E",
                     "UPC_EAN_EXTENSION", "CODE_128", "CODE_39", "CODE_93",
                     "ITF", "CODABAR"].map((k) => F[k]).filter((v) => v !== undefined);
    _scanner = new Html5Qrcode("reader", {
      formatsToSupport: formats.length ? formats : undefined,
      experimentalFeatures: { useBarCodeDetectorIfSupported: true },
      verbose: false,
    });
    const scanCfg = { fps: 12, qrbox: (w, h) => {
        // wide box suits horizontal 1D barcodes
        return { width: Math.floor(w * 0.92), height: Math.floor(Math.min(h * 0.5, 200)) };
      } };
    // Prefer a high-res, continuously-focused stream (better for curved/shiny
    // labels), but some phones reject the extra constraints — if so, fall back
    // to a plain environment-facing camera so scanning still works.
    const hiRes = { facingMode: "environment", width: { ideal: 1920 },
                    height: { ideal: 1080 }, advanced: [{ focusMode: "continuous" }] };
    try {
      await _scanner.start(hiRes, scanCfg, onScan, () => {});
    } catch (e) {
      await _scanner.start({ facingMode: "environment" }, scanCfg, onScan, () => {});
    }
    $("#scanStatus").textContent = "Hold steady over the barcode or QR code…";
  } catch (e) {
    $("#scanStatus").textContent = "Camera unavailable or permission denied. You can enter details manually.";
  }
}

async function stopScanner() {
  if (_scanner) {
    try { await _scanner.stop(); _scanner.clear(); } catch (e) { /* already stopped */ }
    _scanner = null;
  }
  $("#manualCode").value = "";
  $("#scanModal").hidden = true;
}

async function onScan(text) {
  await stopScanner();
  await applyScan(text);
}

// Fallback when the camera can't read a curved/shiny label: type the digits.
async function manualLookup() {
  const code = ($("#manualCode").value || "").trim();
  if (!/^\d{6,}$/.test(code)) {
    toast("Enter the barcode's digits (at least 6 numbers)");
    return;
  }
  await stopScanner();
  await applyScan(code);
}

async function applyScan(code) {
  const f = $("#itemForm");
  code = (code || "").trim();
  if (/^\d{6,}$/.test(code)) {                 // looks like a product barcode
    toast(`Looking up ${code}…`);
    const info = await lookupBarcode(code);
    if (info && info.name) {
      f.name.value = info.name;
      if (info.brand) f.brand.value = info.brand;
      if (info.size && !f.notes.value) f.notes.value = `Pack size: ${info.size}`;
      toast(`Found: ${info.name}`);
    } else {
      f.notes.value = (f.notes.value ? f.notes.value + " " : "") + `[barcode ${code}]`;
      toast(`Barcode ${code} not in the product database — fill in the name`);
      f.name.focus();
    }
  } else {                                     // QR text / URL
    if (!f.name.value) f.name.value = code;
    else f.notes.value = (f.notes.value ? f.notes.value + " " : "") + code;
    toast(`Scanned: ${code}`);
  }
}

async function fetchWithTimeout(url, ms) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try { return await fetch(url, { signal: ctl.signal }); }
  finally { clearTimeout(t); }
}

async function lookupBarcode(code) {
  // Try the free Open Facts databases in turn: food/drinks, then general
  // products, then beauty — covers water, groceries, and household items.
  const bases = [
    "https://world.openfoodfacts.org",
    "https://world.openproductsfacts.org",
    "https://world.openbeautyfacts.org",
  ];
  for (const base of bases) {
    try {
      const res = await fetchWithTimeout(
        `${base}/api/v2/product/${encodeURIComponent(code)}?fields=product_name,brands,quantity`, 6000);
      const data = await res.json();
      const p = data && data.product;
      if (data && data.status === 1 && p && ((p.product_name || "").trim() || (p.brands || "").trim())) {
        return {
          name: (p.product_name || "").trim(),
          brand: (p.brands || "").split(",")[0].trim(),  // first brand only
          size: (p.quantity || "").trim(),
        };
      }
    } catch (e) { /* timed out or not found — try next database */ }
  }
  return null;
}

// ---- stock modal (both roles) ----
function openStock(it) {
  const f = $("#stockForm");
  f.id.value = it.id;
  f.quantity.value = it.quantity || "";
  f.unit.value = it.unit || "";
  f.needed.value = it.quantity_needed || "";
  $("#stockItemName").textContent = it.name;
  $("#takeAmount").value = "";
  loadTakes(it.id);
  $("#stockModal").hidden = false;
  f.quantity.focus();
}

async function loadTakes(id) {
  const list = $("#takesList");
  list.innerHTML = "";
  try {
    const data = await api("GET", `/api/items/${id}/takes`);
    if (!data.takes.length) {
      list.innerHTML = '<div class="take-item muted">No withdrawals recorded yet.</div>';
      return;
    }
    for (const t of data.takes) {
      const when = (t.created_at || "").slice(0, 16).replace("T", " ");
      list.append(el("div", "take-item", `<b>${t.detail}</b> · ${when}`));
    }
  } catch (e) { /* ignore */ }
}

async function takeStock() {
  const f = $("#stockForm");
  const id = f.id.value;
  const amt = $("#takeAmount").value;
  if (!amt || Number(amt) <= 0) { toast("Enter an amount taken"); return; }
  try {
    const updated = await api("POST", `/api/items/${id}/take`, { amount: amt });
    f.quantity.value = updated.quantity || "";  // reflect the new on-hand count
    $("#takeAmount").value = "";
    await loadTakes(id);
    await load();  // refresh the card list
    toast(`Recorded: took ${amt} from ${updated.name}`);
  } catch (e) { toast(e.message); }
}

async function saveStock(e) {
  e.preventDefault();
  const f = $("#stockForm");
  try {
    await api("POST", `/api/items/${f.id.value}/quantity`,
              { quantity: f.quantity.value, unit: f.unit.value, needed: f.needed.value });
    $("#stockModal").hidden = true;
    await load();
    toast("Stock updated");
  } catch (err) { toast(err.message); }
}

// ---- alert preview (admin) ----
async function openPreview() {
  const data = await api("GET", "/api/notify/preview");
  $("#previewText").textContent = data.text;
  const on = data.channels || [];
  const parts = [];
  if (on.includes("email")) parts.push(`Email ${data.email_ready ? "✓" : "(not set up)"}`);
  if (on.includes("whatsapp")) parts.push(`WhatsApp ${data.whatsapp_ready ? "✓" : "(not set up)"}`);
  const ready = (on.includes("email") && data.email_ready) ||
                (on.includes("whatsapp") && data.whatsapp_ready);
  $("#previewStatus").textContent = parts.length
    ? "Channels: " + parts.join(" · ")
    : "No channels enabled yet — set them up in config.json.";
  $("#sendNowBtn").hidden = !ready;
  $("#previewModal").hidden = false;
}

async function sendNow() {
  try {
    const r = await api("POST", "/api/notify/send", { force: true });
    toast(r.message);
    $("#previewModal").hidden = true;
  } catch (e) { toast(e.message); }
}

// ---- wiring ----
$("#loginForm").onsubmit = login;
$("#logoutBtn").onclick = logout;
$("#addBtn").onclick = openAdd;
$("#cancelBtn").onclick = () => ($("#modal").hidden = true);
$("#itemForm").onsubmit = saveItem;
$("#stockForm").onsubmit = saveStock;
$("#stockCancel").onclick = () => ($("#stockModal").hidden = true);
$("#takeBtn").onclick = takeStock;
$("#scanBtn").onclick = openScanner;
$("#scanCancel").onclick = stopScanner;
$("#manualCodeBtn").onclick = manualLookup;
$("#manualCode").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); manualLookup(); }
});
$("#previewBtn").onclick = openPreview;
$("#previewClose").onclick = () => ($("#previewModal").hidden = true);
$("#sendNowBtn").onclick = sendNow;
$("#search").oninput = (e) => { state.search = e.target.value; render(); };
$("#ownerFilter").onclick = (e) => {
  if (!e.target.dataset.owner) return;
  state.owner = e.target.dataset.owner;
  document.querySelectorAll("#ownerFilter .chip")
    .forEach((c) => c.classList.toggle("active", c.dataset.owner === state.owner));
  render();
};
document.querySelectorAll(".modal-backdrop").forEach((m) => {
  m.onclick = (e) => { if (e.target === m) m.hidden = true; };
});
// Closing the scanner by backdrop must also stop the camera.
$("#scanModal").onclick = (e) => { if (e.target === $("#scanModal")) stopScanner(); };
document.addEventListener("click", closeAllMenus);

checkSession();
