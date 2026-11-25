// dashboard.js — Joy panel + Today in History + mini-map with bot-info fallback

"use strict";

let _dashMap = null;
let _dashMapLayerGroup = null;
let _dashTilesOk = true;
let _dashTileErrorFired = false;

// Month name lookup for the TIH panel header
const _MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// ── Joy panel ──────────────────────────────────────────────────────────────

const _JOY_EVENTS_REFRESH_MS = 60_000;

// Events happening right now, listed at the top of the Joy panel. Each links
// to the event on the Events page (details + photo upload).
async function _fetchActiveEvents() {
  const box = document.getElementById("dash-joy-events");
  if (!box) return;
  try {
    const res = await fetch("/api/events", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const active = (data.events || []).filter((e) => e.status === "active" && e.approved !== false);
    const endOf = (e) => String(e.occurrence_end || e.end);
    active.sort((a, b) => endOf(a).localeCompare(endOf(b)));
    _renderActiveEvents(active);
  } catch (_) {}
}

function _renderActiveEvents(events) {
  const box = document.getElementById("dash-joy-events");
  box.hidden = !events.length;
  if (!events.length) {
    box.innerHTML = "";
    return;
  }
  const rows = events
    .map((e) => {
      const loc = e.location || {};
      const where = loc.type === "online" ? "Online" : loc.address || "";
      const meta = [_joyEventUntil(e), where].filter(Boolean).join(" · ");
      return `<li><a class="joy-event-link" href="/events?id=${encodeURIComponent(e.id)}">${_escapeHtml(e.name)}</a>${meta ? `<span class="joy-event-meta">${_escapeHtml(meta)}</span>` : ""}</li>`;
    })
    .join("");
  box.innerHTML = `<div class="joy-item">
    <span class="joy-label">&#127881; Happening now &mdash; tap to see details &amp; share photos</span>
    <ul class="joy-events">${rows}</ul>
  </div>`;
}

// "Until 8:00 PM", "Until Sat, Dec 6", or "All day" / "Through Sun, Dec 6".
function _joyEventUntil(e) {
  const today = new Date();
  const sameDay = (d) => d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
  const dayLabel = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  // Repeating events: the server sends the date that's happening now.
  const repeating = !!e.recurrence && e.occurrence_end;
  if (e.all_day && e.end_day) {
    let last;
    if (repeating) {
      last = new Date(new Date(e.occurrence_end).getTime() - 1);
    } else {
      const [y, m, d] = e.end_day.split("-").map(Number);
      last = new Date(y, m - 1, d);
    }
    return sameDay(last) ? "All day" : `Through ${dayLabel(last)}`;
  }
  const end = new Date(repeating ? e.occurrence_end : e.end);
  if (isNaN(end)) return "";
  return sameDay(end) ? `Until ${end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` : `Until ${dayLabel(end)}`;
}

async function _fetchJoy() {
  try {
    const res = await fetch("/api/joy", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    _renderJoy(data);
  } catch (_) {}
}

// Refresh button: fetch a new random set; spin the icon while loading and
// ignore extra clicks until the request finishes.
async function _onJoyRefreshClick() {
  const btn = document.getElementById("dash-joy-refresh");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    await Promise.all([_fetchJoy(), _fetchActiveEvents()]);
  } finally {
    btn.classList.remove("spinning");
    btn.disabled = false;
  }
}

function _renderJoy(data) {
  const body = document.getElementById("dash-joy-body");
  if (!body) return;

  const items = [];

  if (data.affirmation) {
    items.push(_joyItem("Affirmation", data.affirmation));
  }

  if (data.zen_quote && data.zen_quote.quote) {
    const label = data.zen_quote.author ? `"${data.zen_quote.quote}" — ${data.zen_quote.author}` : `"${data.zen_quote.quote}"`;
    items.push(_joyItem("Quote", label));
  }

  if (data.joke) {
    items.push(_joyItem("Joke", data.joke));
  }

  body.innerHTML = items.join("");
}

function _joyItem(label, text) {
  return `<div class="joy-item">
    <span class="joy-label">${label}</span>
    <span class="joy-text">${_escapeHtml(text)}</span>
  </div>`;
}

function _escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Mini-map ───────────────────────────────────────────────────────────────

function _initMiniMap() {
  const el = document.getElementById("dash-map");
  if (!el || _dashMap) return;

  _dashMap = L.map("dash-map", {
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    tap: false
  });

  const tileLayer = L.tileLayer("/tiles/{z}/{x}/{y}.png", {
    maxZoom: 18,
    errorTileUrl: ""
  });

  tileLayer.on("tileerror", () => {
    if (!_dashTileErrorFired) {
      _dashTileErrorFired = true;
      _dashTilesOk = false;
      _showBotInfo();
    }
  });

  tileLayer.addTo(_dashMap);
  _dashMapLayerGroup = L.layerGroup().addTo(_dashMap);

  _dashMap.setView([0, 0], 2);

  // Invalidate size after layout fully settles, then fetch nodes
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (_dashMap) {
        _dashMap.invalidateSize();
        _fetchAndRenderMapNodes();
      }
    });
  });

  // Watch for future container resizes (e.g. window resize)
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      if (_dashMap) _dashMap.invalidateSize();
    }).observe(el);
  }
}

async function _fetchAndRenderMapNodes() {
  try {
    const res = await fetch("/api/map-nodes");
    if (!res.ok) return;
    const data = await res.json();
    _renderMapNodes(data);
  } catch (_) {}
}

function _renderMapNodes(data) {
  if (!_dashMap || !_dashMapLayerGroup) return;

  _dashMapLayerGroup.clearLayers();

  const nodes = data.nodes || [];
  const positioned = data.positioned_count ?? nodes.length;
  const total = data.total_count ?? nodes.length;

  const titleEl = document.getElementById("dash-map-title");
  if (titleEl) {
    titleEl.textContent = `Map — ${positioned} of ${total} nodes`;
  }

  if (!nodes.length) return;

  const bounds = [];

  nodes.forEach((node) => {
    const lat = node.latitude;
    const lng = node.longitude;
    if (lat == null || lng == null) return;

    const marker = L.circleMarker([lat, lng], {
      radius: 6,
      color: "#c0392b",
      fillColor: "#e74c3c",
      fillOpacity: 0.9,
      weight: 1.5
    });

    marker.addTo(_dashMapLayerGroup);
    bounds.push([lat, lng]);
  });

  if (bounds.length) {
    _dashMap.fitBounds(bounds, { padding: [8, 8], maxZoom: 14 });
  }
}

// ── Today in History panel ────────────────────────────────────────────────

async function _fetchTodayInHistory() {
  try {
    const now = new Date();
    const month = now.getMonth() + 1;
    const day = now.getDate();
    const res = await fetch(`/api/today-in-history?month=${month}&day=${day}`);
    if (!res.ok) return;
    const data = await res.json();
    _renderTodayInHistory(data);
  } catch (_) {}
}

function _renderTodayInHistory(data) {
  const body = document.getElementById("dash-history-body");
  const titleEl = document.getElementById("dash-history-title");
  if (!body) return;

  const month = data.month;
  const day = data.day;
  const events = data.events || [];

  if (titleEl && month && day) {
    const monthName = _MONTH_NAMES[month - 1] || "";
    titleEl.textContent = `\u{1F4C5} Today in History \u2014 ${monthName} ${day}`;
  }

  if (!events.length) {
    body.innerHTML = "";
    return;
  }

  body.innerHTML = events
    .map((e) => {
      const year = e.year ? `<span class="tih-year">${_escapeHtml(e.year)}</span>` : "";
      const text = `<span class="tih-text">${_escapeHtml(e.text)}</span>`;
      const wiki = e.wikipedia ? ` <a class="tih-wiki" href="${_escapeHtml(e.wikipedia)}" target="_blank" rel="noopener">&#128279;</a>` : "";
      return `<div class="tih-event">${year}${text}${wiki}</div>`;
    })
    .join("");
}

// ── Bot info fallback ──────────────────────────────────────────────────────

function _showBotInfo() {
  const mapAnchor = document.getElementById("dash-map-link-wrap");
  const botInfo = document.getElementById("dash-bot-info");
  if (mapAnchor) mapAnchor.style.display = "none";
  if (botInfo) botInfo.style.display = "";
  _fetchBotInfo();
}

async function _fetchBotInfo() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return;
    const data = await res.json();
    _renderBotInfo(data);
  } catch (_) {}
}

function _renderBotInfo(data) {
  const user = data.user || {};
  const lora = data.lora || {};
  const channels = data.channels || [];

  const longNameEl = document.getElementById("dbi-long-name");
  const subEl = document.getElementById("dbi-sub");
  const gridEl = document.getElementById("dbi-grid");

  if (longNameEl) longNameEl.textContent = user.long_name || "Unknown";

  if (subEl) {
    const sub = [user.short_name, user.node_id].filter(Boolean).join(" — ");
    subEl.textContent = sub;
  }

  if (gridEl) {
    const rows = [];

    if (user.hw_model) rows.push(["Hardware", user.hw_model]);
    if (user.role) rows.push(["Role", user.role]);
    if (lora.modem_preset) rows.push(["Modem Preset", lora.modem_preset]);
    if (lora.hop_limit != null) rows.push(["Hop Limit", lora.hop_limit]);

    if (channels.length) {
      const chList = channels.map((ch) => `${ch.name} (${ch.index})`).join(", ");
      rows.push(["Channels", chList]);
    }

    gridEl.innerHTML = rows.map(([k, v]) => `<div class="dbi-row"><span class="dbi-key">${_escapeHtml(k)}</span><span class="dbi-val">${_escapeHtml(String(v))}</span></div>`).join("");
  }
}

// ── Public API ─────────────────────────────────────────────────────────────

function dashboardInit() {
  _fetchJoy();
  _fetchActiveEvents();
  setInterval(_fetchActiveEvents, _JOY_EVENTS_REFRESH_MS);
  const joyRefreshBtn = document.getElementById("dash-joy-refresh");
  if (joyRefreshBtn) joyRefreshBtn.addEventListener("click", _onJoyRefreshClick);
  _fetchTodayInHistory();
  // Defer map init until all resources are loaded so the container has its
  // final dimensions before Leaflet measures it.
  if (document.readyState === "complete") {
    _initMiniMap();
  } else {
    window.addEventListener("load", _initMiniMap, { once: true });
  }
}

function dashboardRefresh() {
  if (_dashTilesOk) {
    _fetchAndRenderMapNodes();
  }
}
