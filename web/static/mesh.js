// mesh.js — Mesh dashboard: node stats, the bot's own node, and a mini-map

"use strict";

let _meshMap = null;
let _meshMapLayerGroup = null;
let _meshTilesOk = true;

function _meshEsc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Node stats ───────────────────────────────────────────────────────────

async function _fetchMeshStats() {
  const grid = document.getElementById("mesh-stats-grid");
  if (!grid) return;
  try {
    const res = await fetch("/api/nodes", { cache: "no-store" });
    if (!res.ok) throw new Error("load failed");
    _renderMeshStats(await res.json());
  } catch (_) {
    if (!grid.children.length) grid.innerHTML = '<p class="dash-events-empty">Couldn’t load nodes.</p>';
  }
}

function _renderMeshStats(nodes) {
  const now = Date.now();
  const seenWithin = (ms) => nodes.filter((n) => n.last_seen && now - new Date(n.last_seen).getTime() <= ms).length;
  const stats = [
    ["Known", nodes.length],
    ["Last hour", seenWithin(3_600_000)],
    ["Last 24h", seenWithin(86_400_000)],
    ["Direct", nodes.filter((n) => n.hops_away === 0).length],
    ["On map", nodes.filter((n) => n.latitude != null && n.longitude != null).length]
  ];
  document.getElementById("mesh-stats-grid").innerHTML = stats
    .map(([label, value]) => `<div class="mesh-stat"><span class="mesh-stat-value">${value}</span><span class="mesh-stat-label">${_meshEsc(label)}</span></div>`)
    .join("");
}

// ── Bot node ─────────────────────────────────────────────────────────────

async function _fetchBotInfo() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return;
    _renderBotInfo(await res.json());
  } catch (_) {}
}

function _renderBotInfo(data) {
  const user = data.user || {};
  const lora = data.lora || {};
  const channels = data.channels || [];

  document.getElementById("dbi-long-name").textContent = user.long_name || "Unknown";
  document.getElementById("dbi-sub").textContent = [user.short_name, user.node_id].filter(Boolean).join(" — ");

  const rows = [];
  if (user.hw_model) rows.push(["Hardware", user.hw_model]);
  if (user.role) rows.push(["Role", user.role]);
  if (lora.modem_preset) rows.push(["Modem Preset", lora.modem_preset]);
  if (lora.hop_limit != null) rows.push(["Hop Limit", lora.hop_limit]);
  if (channels.length) rows.push(["Channels", channels.map((ch) => `${ch.name} (${ch.index})`).join(", ")]);

  document.getElementById("dbi-grid").innerHTML = rows
    .map(([k, v]) => `<div class="dbi-row"><span class="dbi-key">${_meshEsc(k)}</span><span class="dbi-val">${_meshEsc(String(v))}</span></div>`)
    .join("");
}

// ── Mini-map ─────────────────────────────────────────────────────────────

function _initMeshMap() {
  const el = document.getElementById("dash-map");
  if (!el || _meshMap) return;

  _meshMap = L.map("dash-map", {
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    tap: false
  });

  const tileLayer = L.tileLayer("/tiles/{z}/{x}/{y}.png", { maxZoom: 18, errorTileUrl: "" });
  tileLayer.on("tileerror", () => {
    if (!_meshTilesOk) return;
    _meshTilesOk = false;
    document.getElementById("dash-map-link-wrap").style.display = "none";
    document.getElementById("dash-map-offline").style.display = "";
  });
  tileLayer.addTo(_meshMap);
  _meshMapLayerGroup = L.layerGroup().addTo(_meshMap);
  _meshMap.setView([0, 0], 2);

  // Measure after layout settles, then fetch nodes.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      if (!_meshMap) return;
      _meshMap.invalidateSize();
      _fetchMapNodes();
    })
  );

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => _meshMap && _meshMap.invalidateSize()).observe(el);
  }
}

async function _fetchMapNodes() {
  try {
    const res = await fetch("/api/map-nodes");
    if (!res.ok) return;
    _renderMapNodes(await res.json());
  } catch (_) {}
}

function _renderMapNodes(data) {
  if (!_meshMap || !_meshMapLayerGroup) return;
  _meshMapLayerGroup.clearLayers();

  const nodes = data.nodes || [];
  const positioned = data.positioned_count ?? nodes.length;
  const total = data.total_count ?? nodes.length;
  const titleEl = document.getElementById("dash-map-title");
  if (titleEl) titleEl.textContent = `\u{1F9ED} Map — ${positioned} of ${total} nodes`;

  const bounds = [];
  nodes.forEach((node) => {
    if (node.latitude == null || node.longitude == null) return;
    L.circleMarker([node.latitude, node.longitude], {
      radius: 6,
      color: "#c0392b",
      fillColor: "#e74c3c",
      fillOpacity: 0.9,
      weight: 1.5
    }).addTo(_meshMapLayerGroup);
    bounds.push([node.latitude, node.longitude]);
  });
  if (bounds.length) _meshMap.fitBounds(bounds, { padding: [8, 8], maxZoom: 14 });
}

// ── Public API ───────────────────────────────────────────────────────────

function meshDashboardInit() {
  _fetchMeshStats();
  _fetchBotInfo();
  // Wait for all resources so the map container has its final size.
  if (document.readyState === "complete") _initMeshMap();
  else window.addEventListener("load", _initMeshMap, { once: true });
}

function meshDashboardRefresh() {
  _fetchMeshStats();
  // Re-fetch so the panel recovers if /api/settings failed at page load.
  _fetchBotInfo();
  if (_meshTilesOk) _fetchMapNodes();
}
