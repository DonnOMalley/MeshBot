// ── Storage page — read-only sizes of the bot's data/ and log/ folders ──
// Admin only: the server returns 403 to anyone not signed in as admin.
// Every name shown here comes from the file system, so it is set as text, never HTML.

"use strict";

const _ST_REFRESH_MS = 60_000;
// One fixed colour per file-type group (validated for the dark surface; never re-assigned by rank).
const _ST_COLORS = {
  Images: "#338ced",
  Data: "#e76624",
  "Text & chat": "#00a888",
  Logs: "#d28e05",
  Encrypted: "#e24d8b",
  Runtime: "#0aac23",
  Other: "#9887ef",
};
const _ST_ICONS = { Images: "🖼️", Data: "🧾", "Text & chat": "💬", Logs: "📜", Encrypted: "🔒", Runtime: "⚙️", Other: "📦" };

let _stSummary = null;
let _stView = "folders"; // or "types"
let _stSelected = null; // {kind: "folder", path} | {kind: "category", name} | {kind: "ext", name}
const _stExpanded = new Set(["data", "log"]);
let _stTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  const label = document.getElementById("refresh-label");
  if (label) label.textContent = "";
  document.getElementById("st-view-folders").addEventListener("click", () => _stSetView("folders"));
  document.getElementById("st-view-types").addEventListener("click", () => _stSetView("types"));
  document.getElementById("st-filter").addEventListener("input", _stRenderList);
  document.getElementById("st-back").addEventListener("click", () => document.body.classList.remove("cl-reading"));
  _stLoad();
  _stTimer = setInterval(_stLoad, _ST_REFRESH_MS);
});

// Header "Refresh" button.
function refreshAll() {
  _stLoad();
}

async function _stFetch(url) {
  const res = await fetch(url);
  const result = await res.json();
  if (res.status === 403 && result.auth_required) {
    clearInterval(_stTimer);
    window.location.href = "/admin/login?next=" + encodeURIComponent("/storage");
    throw new Error(result.error);
  }
  if (!res.ok) throw new Error(result.error || "Request failed.");
  return result;
}

async function _stLoad() {
  try {
    _stSummary = await _stFetch("/api/storage");
    _stRenderSummary();
    _stRenderList();
    if (_stSelected) _stOpen(_stSelected, true, true); // quiet refresh: don't swap panels on phones
    else if (_stSummary.tree.length) _stOpen({ kind: "folder", path: _stSummary.tree[0].path }, true, true);
  } catch (ex) {
    document.getElementById("st-list").replaceChildren(_stEl("li", "cl-error", ex.message));
  }
}

function _stSetView(view) {
  _stView = view;
  document.getElementById("st-view-folders").setAttribute("aria-selected", String(view === "folders"));
  document.getElementById("st-view-types").setAttribute("aria-selected", String(view === "types"));
  document.getElementById("st-list-title").textContent = view === "folders" ? "📁 Folders" : "📄 File types";
  document.getElementById("st-filter").placeholder = view === "folders" ? "Filter folders" : "Filter file types";
  _stRenderList();
}

// ── Overview ──
function _stRenderSummary() {
  const s = _stSummary;
  const grid = document.getElementById("st-summary-grid");
  document.getElementById("st-scanned").textContent = s.scanned_at ? `scanned ${_stTime(s.scanned_at)}` : "";
  if (!s.tree.length) {
    grid.replaceChildren(_stEl("p", "cl-muted", "No data or log folders found."));
    document.getElementById("st-mix").hidden = true;
    return;
  }
  const total = s.total.size;
  const top = s.tree.flatMap((r) => (r.children.length ? r.children : [r])).sort((a, b) => b.size - a.size)[0];
  const tiles = [
    _stTile("Total stored", _stSize(total), `${s.total.files.toLocaleString()} files in ${s.total.folders.toLocaleString()} folders`, `${total.toLocaleString()} bytes`),
    _stTile("Largest folder", top.label || top.name, `${_stSize(top.size)} · ${_stPct(top.size, total)} of the total`, top.path),
  ];
  s.tree.forEach((r) => tiles.push(_stTile(r.label || r.name, _stSize(r.size), `${r.files.toLocaleString()} files · ${r.path}/`, "")));
  if (s.disk) {
    const tile = _stTile("Disk free", _stSize(s.disk.free), `of ${_stSize(s.disk.total)} · MeshBot uses ${_stPct(total, s.disk.total)}`, `${_stPct(s.disk.used, s.disk.total)} of the disk is in use`);
    const meter = _stEl("div", "st-meter");
    const used = _stEl("div", "st-meter-used");
    used.style.width = _stPct(s.disk.used, s.disk.total);
    meter.append(used);
    tile.append(meter);
    tiles.push(tile);
  }
  const nf = s.total.newest_file;
  tiles.push(_stTile("Last change", nf ? _stAgo(nf.modified) : "—", nf ? nf.path : "", nf ? _stDate(nf.modified) : ""));
  grid.replaceChildren(...tiles);

  const mix = document.getElementById("st-mix");
  mix.hidden = false;
  mix.replaceChildren(_stEl("div", "cl-tile-label", "By file type"), _stStack(s.categories, total, true));
}

// Stacked bar of file-type groups + a legend (names, sizes) so colour is never the only cue.
function _stStack(categories, total, clickable) {
  const wrap = _stEl("div", "st-stack-wrap");
  const bar = _stEl("div", "st-stack");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", categories.map((c) => `${c.name} ${_stSize(c.size)}`).join(", "));
  const legend = _stEl("div", "st-legend");
  categories.forEach((c) => {
    const seg = _stEl("div", "st-seg");
    seg.style.flexGrow = String(Math.max(c.size, total * 0.004)); // keep tiny groups visible
    seg.style.background = _ST_COLORS[c.name];
    seg.title = `${c.name}: ${_stSize(c.size)} · ${_stPct(c.size, total)} · ${c.files.toLocaleString()} files`;
    bar.append(seg);
    const item = _stEl(clickable ? "button" : "span", "st-legend-item");
    if (clickable) {
      item.type = "button";
      item.addEventListener("click", () => {
        _stSetView("types");
        _stOpen({ kind: "category", name: c.name });
      });
    }
    const sw = _stEl("span", "st-swatch");
    sw.style.background = _ST_COLORS[c.name];
    item.append(sw, _stEl("span", "", c.name), _stEl("span", "st-legend-val", `${_stSize(c.size)} · ${_stPct(c.size, total)}`));
    legend.append(item);
  });
  wrap.append(bar, legend);
  return wrap;
}

// ── Left list: folder tree or file-type groups ──
function _stRenderList() {
  const list = document.getElementById("st-list");
  if (!_stSummary) return;
  const q = document.getElementById("st-filter").value.trim().toLowerCase();
  if (_stView === "folders") {
    const rows = [];
    let count = 0;
    const walk = (node, depth, parentSize) => {
      const match = !q || (node.path + " " + (node.label || "")).toLowerCase().includes(q);
      const below = !!q && node.children.some((c) => _stMatches(c, q)); // only a filter forces folders open
      if (!match && !below) return;
      count++;
      rows.push(_stFolderRow(node, depth, parentSize, below));
      if (node.children.length && (_stExpanded.has(node.path) || below)) node.children.forEach((c) => walk(c, depth + 1, node.size));
    };
    _stSummary.tree.forEach((r) => walk(r, 0, _stSummary.total.size));
    document.getElementById("st-list-count").textContent = q ? `${count} match` + (count === 1 ? "" : "es") : `${_stSummary.total.folders} folders`;
    list.replaceChildren(...(rows.length ? rows : [_stEl("li", "cl-muted st-empty", "No folders match.")]));
  } else {
    const rows = [];
    const total = _stSummary.total.size;
    _stSummary.categories.forEach((c) => {
      const exts = c.exts.filter((e) => !q || e.ext.includes(q) || c.name.toLowerCase().includes(q));
      if (!exts.length) return;
      rows.push(_stTypeRow({ kind: "category", name: c.name }, `${_ST_ICONS[c.name] || ""} ${c.name}`, _stFiles(c.files), c.size, total, 0, c.name));
      exts.forEach((e) => rows.push(_stTypeRow({ kind: "ext", name: e.ext }, "." + e.ext.replace(/^\(none\)$/, "(no extension)"), _stFiles(e.files), e.size, c.size, 1, c.name)));
    });
    document.getElementById("st-list-count").textContent = `${_stSummary.categories.length} groups`;
    list.replaceChildren(...(rows.length ? rows : [_stEl("li", "cl-muted st-empty", "No file types match.")]));
  }
}

function _stMatches(node, q) {
  return !q || (node.path + " " + (node.label || "")).toLowerCase().includes(q) || node.children.some((c) => _stMatches(c, q));
}

function _stFolderRow(node, depth, parentSize, forcedOpen) {
  const li = _stEl("li", "st-row" + (_stIsSelected({ kind: "folder", path: node.path }) ? " selected" : ""));
  li.setAttribute("role", "treeitem");
  li.style.setProperty("--depth", depth);
  const open = _stExpanded.has(node.path) || forcedOpen;
  if (node.children.length) li.setAttribute("aria-expanded", String(open));
  const caret = _stEl("button", "st-caret", node.children.length ? (open ? "▾" : "▸") : "");
  caret.type = "button";
  if (node.children.length) {
    caret.dataset.path = node.path;
    caret.setAttribute("aria-label", `${open ? "Collapse" : "Expand"} ${node.name}`);
    caret.setAttribute("aria-expanded", String(open));
  } else {
    caret.tabIndex = -1;
    caret.setAttribute("aria-hidden", "true");
  }
  if (node.children.length)
    caret.addEventListener("click", (e) => {
      e.stopPropagation();
      _stExpanded.has(node.path) ? _stExpanded.delete(node.path) : _stExpanded.add(node.path);
      _stRenderList();
      // the list was rebuilt, so put keyboard focus back on this folder's new caret
      const again = [...document.querySelectorAll("#st-list .st-caret")].find((c) => c.dataset.path === node.path);
      if (again) again.focus();
    });
  const btn = _stEl("button", "st-row-btn");
  btn.type = "button";
  btn.addEventListener("click", () => {
    if (node.children.length) _stExpanded.add(node.path);
    _stOpen({ kind: "folder", path: node.path });
  });
  const name = _stEl("span", "st-row-name");
  name.append(_stEl("span", "st-row-icon", open && node.children.length ? "📂" : "📁"), _stEl("span", "st-row-text", node.name));
  if (node.label) name.append(_stEl("span", "st-row-label", node.label));
  const right = _stEl("span", "st-row-size", _stSize(node.size));
  btn.append(name, right, _stShareBar(node.size, parentSize, "var(--accent)", `${_stPct(node.size, parentSize)} of ${depth ? "its parent" : "the total"}`));
  li.append(caret, btn);
  return li;
}

function _stTypeRow(sel, text, sub, size, parentSize, depth, category) {
  const li = _stEl("li", "st-row" + (depth ? " st-row-ext" : " st-row-cat") + (_stIsSelected(sel) ? " selected" : ""));
  li.style.setProperty("--depth", depth);
  const btn = _stEl("button", "st-row-btn");
  btn.type = "button";
  btn.addEventListener("click", () => _stOpen(sel));
  const name = _stEl("span", "st-row-name");
  if (!depth) {
    const sw = _stEl("span", "st-swatch");
    sw.style.background = _ST_COLORS[category];
    name.append(sw);
  }
  name.append(_stEl("span", "st-row-text", text), _stEl("span", "st-row-label", sub));
  btn.append(name, _stEl("span", "st-row-size", _stSize(size)), _stShareBar(size, parentSize, _ST_COLORS[category], `${_stPct(size, parentSize)} of ${depth ? category : "the total"}`));
  li.append(_stEl("span", "st-caret"), btn);
  return li;
}

function _stShareBar(size, of, color, title) {
  const track = _stEl("span", "st-share");
  track.title = title;
  const fill = _stEl("span", "st-share-fill");
  fill.style.width = of ? Math.max(1, (100 * size) / of) + "%" : "0";
  fill.style.background = color;
  track.append(fill);
  return track;
}

function _stIsSelected(sel) {
  return !!_stSelected && _stSelected.kind === sel.kind && (_stSelected.path || _stSelected.name) === (sel.path || sel.name);
}

// ── Right panel: details ──
async function _stOpen(sel, quiet, noSwap) {
  _stSelected = sel;
  _stRenderList();
  if (!noSwap) document.body.classList.add("cl-reading");
  const body = document.getElementById("st-detail-body");
  if (!quiet) body.replaceChildren(_stEl("p", "cl-muted", "Loading…"));
  const url =
    sel.kind === "folder"
      ? "/api/storage/folder?path=" + encodeURIComponent(sel.path)
      : "/api/storage/type?" + (sel.kind === "ext" ? "ext=" : "category=") + encodeURIComponent(sel.name);
  try {
    const detail = await _stFetch(url);
    if (_stSelected !== sel) return; // another item was picked meanwhile
    sel.kind === "folder" ? _stRenderFolder(detail) : _stRenderType(detail);
  } catch (ex) {
    if (_stSelected === sel) body.replaceChildren(_stEl("p", "cl-error", ex.message));
  }
}

function _stRenderFolder(d) {
  const f = d.folder;
  document.getElementById("st-detail-title").textContent = "📁 " + f.path + "/";
  const body = document.getElementById("st-detail-body");
  const nodes = [];
  const meta = _stEl("div", "cl-detail-meta");
  meta.append(
    _stMeta("What it is", f.label || "—"),
    _stMeta("Size", `${_stSize(f.size)} (${f.size.toLocaleString()} bytes)`),
    _stMeta("Share of total", _stPct(f.size, _stSummary.total.size)),
    _stMeta("Contains", `${f.files.toLocaleString()} files · ${f.folders.toLocaleString()} subfolders`),
    _stMeta("Last change", f.modified ? `${_stDate(f.modified)} (${_stAgo(f.modified)})` : "—"),
    _stMeta("Average file", f.files ? _stSize(Math.round(f.size / f.files)) : "—")
  );
  nodes.push(meta);

  if (d.types.length) {
    const sec = _stSection("By file type");
    sec.append(_stStack(d.types, f.size, false));
    sec.append(
      _stTable(
        ["Type", "Files", "Size", "Share"],
        d.types.flatMap((c) => c.exts.map((e) => [`.${e.ext} · ${c.name}`, e.files.toLocaleString(), _stSize(e.size), _stPct(e.size, f.size)])),
        null
      )
    );
    nodes.push(sec);
  }
  if (d.subfolders.length) {
    const sec = _stSection(`Subfolders (${d.subfolders.length})`);
    sec.append(
      _stTable(
        ["Folder", "Files", "Size", "Share"],
        d.subfolders.map((s) => [s.name + "/" + (s.label ? ` · ${s.label}` : ""), s.files.toLocaleString(), _stSize(s.size), _stShareBar(s.size, f.size, "var(--accent)", _stPct(s.size, f.size))]),
        (i) => {
          _stExpanded.add(f.path);
          _stOpen({ kind: "folder", path: d.subfolders[i].path });
        }
      )
    );
    nodes.push(sec);
  }
  if (d.files.length) {
    const sec = _stSection(`Files here (${(d.files.length + d.files_omitted).toLocaleString()})`);
    sec.append(_stFileTable(d.files, false));
    if (d.files_omitted) sec.append(_stEl("p", "cl-muted st-note", `${d.files_omitted.toLocaleString()} smaller files not listed.`));
    nodes.push(sec);
  }
  if (d.largest.length) {
    const sec = _stSection("Largest files inside");
    sec.append(_stFileTable(d.largest, true));
    nodes.push(sec);
  }
  if (d.newest.length) {
    const sec = _stSection("Recently changed");
    sec.append(_stFileTable(d.newest, true, true));
    nodes.push(sec);
  }
  if (!f.files) nodes.push(_stEl("p", "cl-muted st-note", "This folder is empty."));
  body.replaceChildren(...nodes);
}

function _stRenderType(d) {
  const isExt = d.kind === "ext";
  const title = isExt ? `.${d.name}` : d.name;
  document.getElementById("st-detail-title").textContent = `${_ST_ICONS[d.category] || "📄"} ${title}` + (isExt ? ` · ${d.category}` : "");
  const body = document.getElementById("st-detail-body");
  const nodes = [];
  const meta = _stEl("div", "cl-detail-meta");
  meta.append(
    _stMeta("Size", `${_stSize(d.size)} (${d.size.toLocaleString()} bytes)`),
    _stMeta("Share of total", _stPct(d.size, _stSummary.total.size)),
    _stMeta("Files", d.files.toLocaleString()),
    _stMeta("Average file", _stSize(d.average)),
    _stMeta("Newest", `${d.newest.path} · ${_stAgo(d.newest.modified)}`),
    _stMeta("Oldest", `${d.oldest.path} · ${_stDate(d.oldest.modified)}`)
  );
  nodes.push(meta);
  if (!isExt && d.exts.length) {
    const sec = _stSection("Extensions");
    sec.append(
      _stTable(
        ["Extension", "Files", "Size", "Share"],
        d.exts.map((e) => ["." + e.ext, e.files.toLocaleString(), _stSize(e.size), _stShareBar(e.size, d.size, _ST_COLORS[d.category], _stPct(e.size, d.size))]),
        (i) => _stOpen({ kind: "ext", name: d.exts[i].ext })
      )
    );
    nodes.push(sec);
  }
  const sec = _stSection(`Where they are (${d.folders.length} folder${d.folders.length === 1 ? "" : "s"})`);
  sec.append(
    _stTable(
      ["Folder", "Files", "Size", "Share"],
      d.folders.map((f) => [f.path + "/" + (f.label ? ` · ${f.label}` : ""), f.files.toLocaleString(), _stSize(f.size), _stShareBar(f.size, d.size, _ST_COLORS[d.category], _stPct(f.size, d.size))]),
      (i) => {
        _stRevealFolder(d.folders[i].path);
        _stSetView("folders");
        _stOpen({ kind: "folder", path: d.folders[i].path });
      }
    )
  );
  nodes.push(sec);
  const big = _stSection("Largest files");
  big.append(_stFileTable(d.largest, true));
  nodes.push(big);
  body.replaceChildren(...nodes);
}

// Expands every parent so a folder picked elsewhere shows in the tree.
function _stRevealFolder(path) {
  const parts = path.split("/");
  for (let i = 1; i < parts.length; i++) _stExpanded.add(parts.slice(0, i).join("/"));
}

function _stFileTable(files, showFolder, byDate) {
  return _stTable(
    ["File", byDate ? "Changed" : "Type", "Size"],
    files.map((f) => {
      const cell = _stEl("span", "st-file");
      cell.append(_stEl("span", "st-file-name", showFolder ? f.path : f.name));
      if (f.label) cell.append(_stEl("span", "st-row-label", f.label));
      cell.title = `${f.path}\nChanged ${_stDate(f.modified)}`;
      return [cell, byDate ? _stAgo(f.modified) : "." + f.ext, _stSize(f.size)];
    }),
    null
  );
}

function _stTable(heads, rows, onClick) {
  const table = _stEl("table", "st-table" + (onClick ? " st-clickable" : ""));
  const tr = _stEl("tr");
  heads.forEach((h, i) => tr.append(_stEl("th", i ? "st-num" : "", h)));
  const thead = _stEl("thead");
  thead.append(tr);
  const tbody = _stEl("tbody");
  rows.forEach((r, ri) => {
    const row = _stEl("tr");
    r.forEach((v, i) => {
      const td = _stEl("td", i ? "st-num" : "");
      typeof v === "string" ? (td.textContent = v) : td.append(v);
      row.append(td);
    });
    if (onClick) {
      row.tabIndex = 0;
      row.addEventListener("click", () => onClick(ri));
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter") onClick(ri);
      });
    }
    tbody.append(row);
  });
  table.append(thead, tbody);
  return table;
}

function _stSection(title) {
  const sec = _stEl("section", "st-section");
  sec.append(_stEl("h3", "st-section-title", title));
  return sec;
}

// ── Small helpers ──
function _stEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function _stTile(label, value, sub, title) {
  const tile = _stEl("div", "cl-tile");
  if (title) tile.title = title;
  tile.append(_stEl("div", "cl-tile-label", label), _stEl("div", "cl-tile-value st-tile-value", value), _stEl("div", "cl-tile-sub", sub));
  return tile;
}

function _stMeta(label, value) {
  const div = _stEl("div", "cl-meta-row");
  div.append(_stEl("span", "cl-meta-label", label), _stEl("span", "cl-meta-value", value));
  return div;
}

function _stFiles(n) {
  return `${n.toLocaleString()} file${n === 1 ? "" : "s"}`;
}

function _stSize(n) {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return (i === 0 ? String(v) : v >= 100 ? v.toFixed(0) : v.toFixed(1)) + " " + units[i];
}

function _stPct(part, whole) {
  if (!whole) return "0%";
  const p = (100 * part) / whole;
  return (p > 0 && p < 0.1 ? "<0.1" : p < 10 ? p.toFixed(1) : Math.round(p)) + "%";
}

function _stDate(iso) {
  return iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}

function _stTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
}

function _stAgo(iso) {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days < 60 ? `${days} d ago` : _stDate(iso).split(",")[0];
}
