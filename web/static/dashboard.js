// dashboard.js — Joy panel + Today in History + mini-map with bot-info fallback

"use strict";

let _dashMap = null;
let _dashMapLayerGroup = null;
let _dashTilesOk = true;
let _dashTileErrorFired = false;

// Month name lookup for the TIH panel header
const _MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// ── Joy panel ──────────────────────────────────────────────────────────────

async function _fetchJoy() {
  try {
    const res = await fetch("/api/joy");
    if (!res.ok) return;
    const data = await res.json();
    _renderJoy(data);
  } catch (_) {}
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
    const res = await fetch("/api/today-in-history");
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
