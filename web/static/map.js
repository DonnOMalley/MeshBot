"use strict";

// Page init for /map
document.addEventListener("DOMContentLoaded", () => {
  fetchMapNodes();
  setInterval(fetchMapNodes, REFRESH_INTERVAL_MS);
  const filterInput = document.getElementById("map-filter");
  if (filterInput) {
    filterInput.addEventListener("input", (e) => {
      _filterText = e.target.value;
      _renderNodeList();
    });
  }
});

// ── State ─────────────────────────────────────────────────────────────────────

let _map = null;
let _markerGroup = null;
let _markers = {}; // node_id → L.Marker
let _allNodes = []; // sorted positioned nodes from last fetch
let _botNodeId = ""; // bot's own node_id
let _selectedNodeId = null;
let _filterText = "";
let _userMovedMap = false;
let _programmaticMove = false;
let _botControlEl = null;

// ── Data fetch ────────────────────────────────────────────────────────────────

async function fetchMapNodes() {
  try {
    const res = await fetch("/api/map-nodes");
    if (!res.ok) return;
    renderMap(await res.json());
  } catch (_) {
    /* network error — ignore */
  }
}

// ── Map render ────────────────────────────────────────────────────────────────

function renderMap(data) {
  _updateStatus(data.positioned_count, data.total_count);
  _botNodeId = data.bot_node_id || "";
  _ensureMap();
  _clearMarkers();

  _allNodes = (data.nodes || []).slice().sort((a, b) => {
    const na = (a.long_name || a.short_name || "").toLowerCase();
    const nb = (b.long_name || b.short_name || "").toLowerCase();
    return na < nb ? -1 : na > nb ? 1 : 0;
  });

  if (_allNodes.length === 0) {
    if (!_userMovedMap) _programmaticSetView([20, 0], 2);
    _renderNodeList();
    _updateBotControl();
    return;
  }

  const latLngs = [];
  _allNodes.forEach((node) => {
    latLngs.push([node.latitude, node.longitude]);
    _buildMarker(node);
  });

  if (_selectedNodeId && _markers[_selectedNodeId]) {
    _markers[_selectedNodeId].setZIndexOffset(1000);
    _markers[_selectedNodeId].openTooltip();
  }

  if (!_userMovedMap) {
    _fitBounds(latLngs);
  }

  _renderNodeList();
  _updateBotControl();
}

function _buildMarker(node) {
  const lastSeen = node.last_seen ? new Date(node.last_seen).toLocaleString() : "\u2014";
  const tooltipHtml = [
    `<strong>${esc(node.long_name || "\u2014")}</strong> - ${esc(node.node_id)}`,
    `<span class="map-tt-row"><span class="map-tt-label">Short Name</span>${esc(node.short_name || "\u2014")}</span>`,
    `<span class="map-tt-row"><span class="map-tt-label">Device</span>${esc(node.hardware_model || "\u2014")}</span>`,
    `<span class="map-tt-row"><span class="map-tt-label">Role</span>${esc(node.role || "\u2014")}</span>`,
    `<span class="map-tt-row"><span class="map-tt-label">Last Seen</span>${esc(lastSeen)}</span>`
  ].join("");

  const marker = L.marker([node.latitude, node.longitude], {
    icon: _makeIcon(node, node.node_id === _botNodeId, node.node_id === _selectedNodeId)
  }).bindTooltip(tooltipHtml, {
    permanent: false,
    direction: "top",
    className: "map-tooltip"
  });

  marker.addTo(_markerGroup);
  _markers[node.node_id] = marker;
}

function _makeIcon(node, isBotNode, isSelected) {
  let cls = "map-node-label";
  if (isBotNode) cls += " map-node-bot";
  if (isSelected) cls += " map-node-selected";
  return L.divIcon({
    className: cls,
    html: `<span class="map-node-text">${esc(node.short_name || node.node_id)}</span>`,
    iconAnchor: [0, 0]
  });
}

// ── Node list sidebar ─────────────────────────────────────────────────────────

function _renderNodeList() {
  const container = document.getElementById("map-node-list");
  if (!container) return;

  const filter = _filterText.toLowerCase().trim();
  const filtered = filter ? _allNodes.filter((n) => (n.long_name || "").toLowerCase().includes(filter) || (n.short_name || "").toLowerCase().includes(filter)) : _allNodes;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="map-list-empty">${filter ? "No nodes match." : "No positioned nodes."}</div>`;
    return;
  }

  container.innerHTML = filtered
    .map((n) => {
      const isSelected = n.node_id === _selectedNodeId;
      const id = esc(n.node_id);
      return (
        `<div class="map-list-item${isSelected ? " map-list-item--selected" : ""}"` +
        ` data-id="${id}"` +
        ` onclick="selectNodeFromList('${id}')"` +
        ` onmouseenter="hoverNodeList('${id}')"` +
        ` onmouseleave="unhoverNodeList('${id}')"` +
        `><span class="map-list-short">${esc(n.short_name || n.node_id)}</span>` +
        `<span class="map-list-long">${esc(n.long_name || "\u2014")}</span></div>`
      );
    })
    .join("");

  if (_selectedNodeId) {
    const el = container.querySelector(".map-list-item--selected");
    if (el) el.scrollIntoView({ block: "nearest" });
  }
}

// ── Selection and hover ───────────────────────────────────────────────────────

function selectNodeFromList(nodeId) {
  if (_selectedNodeId && _selectedNodeId !== nodeId) {
    _updateMarkerIcon(_selectedNodeId, false);
  }
  _selectedNodeId = nodeId;
  _updateMarkerIcon(nodeId, true);

  const node = _allNodes.find((n) => n.node_id === nodeId);
  if (node && _map) {
    _programmaticSetView([node.latitude, node.longitude], 13);
    const marker = _markers[nodeId];
    if (marker) marker.openTooltip();
  }
  _renderNodeList();
}

function hoverNodeList(nodeId) {
  const marker = _markers[nodeId];
  if (marker) marker.openTooltip();
}

function unhoverNodeList(nodeId) {
  if (nodeId === _selectedNodeId) return;
  const marker = _markers[nodeId];
  if (marker) marker.closeTooltip();
}

function _updateMarkerIcon(nodeId, selected) {
  const marker = _markers[nodeId];
  if (!marker) return;
  const node = _allNodes.find((n) => n.node_id === nodeId);
  if (!node) return;
  marker.setIcon(_makeIcon(node, nodeId === _botNodeId, selected));
  marker.setZIndexOffset(selected ? 1000 : 0);
}

// ── Bot control ─────────────────────────────────────────────────────────────────────

function _updateBotControl() {
  if (!_botControlEl) return;
  const botNode = _allNodes.find((n) => n.node_id === _botNodeId);
  const label = _botControlEl.querySelector(".map-bot-btn-label");
  if (label) label.textContent = botNode ? botNode.short_name || "BOT" : "BOT";
}

function clickBotButton() {
  if (!_map) return;

  const botNode = _allNodes.find((n) => n.node_id === _botNodeId);
  const selectedNode = _selectedNodeId && _selectedNodeId !== _botNodeId ? _allNodes.find((n) => n.node_id === _selectedNodeId) : null;
  if (botNode && selectedNode) {
    const bounds = L.latLngBounds([botNode.latitude, botNode.longitude], [selectedNode.latitude, selectedNode.longitude]);
    _programmaticMove = true;
    _map.fitBounds(bounds, { padding: [60, 60] });
    _map.once("moveend", () => {
      _programmaticMove = false;
    });
    const botMarker = _markers[_botNodeId];
    const selMarker = _markers[_selectedNodeId];
    if (botMarker) botMarker.openTooltip();
    if (selMarker) selMarker.openTooltip();
  } else if (botNode) {
    console.log("bot button clicked");
    _programmaticSetView([botNode.latitude, botNode.longitude], 13);
    const botMarker = _markers[_botNodeId];
    if (botMarker) botMarker.openTooltip();
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _updateStatus(positionedCount, totalCount) {
  const el = document.getElementById("map-status");
  if (el) {
    el.textContent = `Showing ${positionedCount} node${positionedCount !== 1 ? "s" : ""} with position` + ` out of ${totalCount} total`;
  }
}

function _programmaticSetView(latLng, zoom) {
  _programmaticMove = true;
  _map.setView(latLng, zoom);
  _map.once("moveend", () => {
    _programmaticMove = false;
  });
}

function _ensureMap() {
  if (_map) return;
  _map = L.map("map", { zoomControl: true });
  _map.on("movestart", () => {
    if (!_programmaticMove) _userMovedMap = true;
  });
  _map.on("zoomstart", () => {
    if (!_programmaticMove) _userMovedMap = true;
  });
  L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    maxZoom: 17,
    attribution:
      'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ' +
      '<a href="http://viewfinderpanoramas.org">SRTM</a> | ' +
      'Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> ' +
      '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
  }).addTo(_map);
  _markerGroup = L.layerGroup().addTo(_map);

  const BotControl = L.Control.extend({
    options: { position: "bottomleft" },
    onAdd() {
      const el = L.DomUtil.create("button", "map-bot-btn");
      el.title = "Hover: show bot tooltip \u00b7 Click: locate";
      el.innerHTML = '<span class="map-bot-btn-icon">&#128225;</span><span class="map-bot-btn-label">BOT</span>';
      L.DomEvent.disableClickPropagation(el);
      el.addEventListener("mouseenter", () => {
        const m = _markers[_botNodeId];
        if (m) m.openTooltip();
      });
      el.addEventListener("mouseleave", () => {
        if (_botNodeId === _selectedNodeId) return;
        const m = _markers[_botNodeId];
        if (m) m.closeTooltip();
      });
      el.addEventListener("click", clickBotButton);
      _botControlEl = el;
      return el;
    }
  });
  new BotControl().addTo(_map);
}

function _clearMarkers() {
  if (_markerGroup) _markerGroup.clearLayers();
  _markers = {};
}

function _fitBounds(latLngs) {
  _programmaticMove = true;
  if (latLngs.length === 1) {
    _map.setView(latLngs[0], 13);
  } else {
    _map.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40] });
  }
  _map.once("moveend", () => {
    _programmaticMove = false;
  });
}

// ── Refresh hook ──────────────────────────────────────────────────────────────

const _origRefreshAll = typeof refreshAll === "function" ? refreshAll : null;
function refreshAll() {
  if (_origRefreshAll) _origRefreshAll();
  fetchMapNodes();
}
