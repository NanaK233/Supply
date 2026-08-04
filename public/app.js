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
  $("#modal").hidden = false;
  f.name.focus();
}

function openEdit(it) {
  $("#modalTitle").textContent = "Edit item";
  const f = $("#itemForm");
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

// ---- stock modal (both roles) ----
function openStock(it) {
  const f = $("#stockForm");
  f.id.value = it.id;
  f.quantity.value = it.quantity || "";
  f.unit.value = it.unit || "";
  f.needed.value = it.quantity_needed || "";
  $("#stockItemName").textContent = it.name;
  $("#stockModal").hidden = false;
  f.quantity.focus();
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
document.addEventListener("click", closeAllMenus);

checkSession();
