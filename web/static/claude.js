// ── Claude page — read-only list of the Claude Code sessions on this computer ──
// Admin only: the server returns 403 to anyone not signed in as admin.

"use strict";

const _CL_REFRESH_MS = 30_000;
let _clSessions = [];
let _clSelected = null;
let _clTimer = null;
let _clDatesTouched = false; // false: the date range follows the data as it grows

document.addEventListener("DOMContentLoaded", () => {
  const label = document.getElementById("refresh-label");
  if (label) label.textContent = "";
  document.getElementById("cl-filter").addEventListener("input", _clRenderList);
  ["cl-date-from", "cl-date-to"].forEach((id) =>
    document.getElementById(id).addEventListener("change", () => {
      _clDatesTouched = true;
      _clRenderList();
    })
  );
  document.getElementById("cl-date-reset").addEventListener("click", () => {
    _clDatesTouched = false;
    _clSyncDateRange();
    _clRenderList();
  });
  document.getElementById("cl-show-tools").addEventListener("change", (e) => {
    document.getElementById("cl-messages").classList.toggle("cl-hide-tools", !e.target.checked);
  });
  document.getElementById("cl-back").addEventListener("click", () => document.body.classList.remove("cl-reading"));
  _clLoadList();
  _clTimer = setInterval(_clLoadList, _CL_REFRESH_MS);
});

// Header "Refresh" button.
function refreshAll() {
  _clLoadList();
  if (_clSelected) _clOpen(_clSelected, true);
}

// Fetches JSON; a 403 means the admin sign-in lapsed (login changed or signed
// out in another tab), so go to the sign-in page and come back here after.
async function _clFetch(url) {
  const res = await fetch(url);
  const result = await res.json();
  if (res.status === 403 && result.auth_required) {
    clearInterval(_clTimer);
    window.location.href = "/admin/login?next=" + encodeURIComponent("/claude");
    throw new Error(result.error);
  }
  if (!res.ok) throw new Error(result.error || "Request failed.");
  return result;
}

async function _clLoadList() {
  try {
    _clSessions = (await _clFetch("/api/claude/sessions")).sessions;
    _clRenderSummary();
    _clSyncDateRange();
    _clRenderList();
  } catch (ex) {
    document.getElementById("cl-list").replaceChildren(_clEl("li", "cl-error", ex.message));
  }
}

// Sets the date pickers' limits to the first and last day in the history. Until
// the user picks dates, the range follows the data (new sessions extend it).
function _clSyncDateRange() {
  const days = _clSessions.flatMap((s) => [s.started, s.updated]).filter(Boolean).map(_clYmd).sort();
  const fromEl = document.getElementById("cl-date-from");
  const toEl = document.getElementById("cl-date-to");
  const min = days[0] || "";
  const max = days[days.length - 1] || "";
  [fromEl, toEl].forEach((el) => {
    el.min = min;
    el.max = max;
  });
  if (!_clDatesTouched) {
    fromEl.value = min;
    toEl.value = max;
  }
  document.getElementById("cl-date-reset").disabled = !_clDatesTouched;
}

// Local calendar day of an ISO time, as "YYYY-MM-DD" (what <input type=date> uses).
function _clYmd(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Totals across every stored session (ignores the filter box), subagents included.
function _clRenderSummary() {
  const grid = document.getElementById("cl-summary-grid");
  const all = _clSessions;
  if (!all.length) {
    grid.replaceChildren(_clEl("p", "cl-muted", "No Claude sessions found."));
    document.getElementById("cl-summary-range").textContent = "";
    return;
  }
  const sum = (key) => all.reduce((n, s) => n + (s.tokens[key] || 0), 0);
  const fresh = sum("input_tokens");
  const writes = sum("cache_creation_input_tokens");
  const reads = sum("cache_read_input_tokens");
  const out = sum("output_tokens");
  const priced = all.filter((s) => s.cost_usd != null);
  const cost = priced.reduce((n, s) => n + s.cost_usd, 0);
  const starts = all.map((s) => s.started).filter(Boolean).sort();
  const ends = all.map((s) => s.updated).filter(Boolean).sort();
  const first = starts[0];
  const last = ends[ends.length - 1];
  const days = first && last ? Math.max(1, Math.ceil((new Date(last) - new Date(first)) / 86400000)) : 0;

  document.getElementById("cl-summary-range").textContent = `${all.length} session${all.length === 1 ? "" : "s"}`;
  grid.replaceChildren(
    _clTile("Recorded cost", `$${cost.toFixed(2)}`, `from ${priced.length} of ${all.length} sessions`, "Claude Code writes a cost only for some sessions, so the real total is higher."),
    _clTile("Tokens in", _clNum(fresh + writes), `${_clNum(fresh)} new · ${_clNum(writes)} cache writes`, _clExact(fresh + writes)),
    _clTile("Cache reads", _clNum(reads), "re-read context, billed cheaply", _clExact(reads)),
    _clTile("Tokens out", _clNum(out), "Claude's replies and tool calls", _clExact(out)),
    _clTile("Date range", first ? _clDayRange(first, last) : "—", first ? `${_clDate(first)} → ${_clDate(last)} · ${days} day${days === 1 ? "" : "s"}` : "", "")
  );
  grid.lastElementChild.classList.add("cl-tile-wide");
}

function _clTile(label, value, sub, title) {
  const tile = _clEl("div", "cl-tile");
  if (title) tile.title = title;
  tile.append(_clEl("div", "cl-tile-label", label), _clEl("div", "cl-tile-value", value), _clEl("div", "cl-tile-sub", sub));
  return tile;
}

function _clExact(n) {
  return n.toLocaleString() + " tokens";
}

// "Nov 24 – Nov 26, 2026"; the first year shows only when the range crosses a year.
function _clDayRange(fromIso, toIso) {
  const from = new Date(fromIso);
  const to = new Date(toIso);
  const sameYear = from.getFullYear() === to.getFullYear();
  const start = from.toLocaleDateString([], sameYear ? { month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "numeric" });
  return `${start} – ${to.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`;
}

function _clRenderList() {
  const query = document.getElementById("cl-filter").value.trim().toLowerCase();
  const from = document.getElementById("cl-date-from").value; // "YYYY-MM-DD" or ""
  const to = document.getElementById("cl-date-to").value;
  const shown = _clSessions.filter(
    (s) =>
      (!query || [s.title, s.cwd, s.first_prompt].some((v) => (v || "").toLowerCase().includes(query))) &&
      // A session counts when its activity overlaps the range (it may span days).
      (!from || !s.updated || _clYmd(s.updated) >= from) &&
      (!to || !s.started || _clYmd(s.started) <= to)
  );
  document.getElementById("cl-count").textContent = `${shown.length} of ${_clSessions.length}`;
  const total = shown.reduce((sum, s) => sum + _clTotalTokens(s), 0);
  const cost = shown.reduce((sum, s) => sum + (s.cost_usd || 0), 0);
  document.getElementById("cl-totals").textContent = `${_clNum(total)} tokens` + (cost ? ` · $${cost.toFixed(2)} recorded cost` : "");

  const list = document.getElementById("cl-list");
  if (!shown.length) {
    list.replaceChildren(_clEl("li", "cl-muted", _clSessions.length ? "No sessions match." : "No Claude sessions found."));
    return;
  }
  list.replaceChildren(
    ...shown.map((s) => {
      const li = _clEl("li", "cl-item" + (s.id === _clSelected ? " selected" : ""));
      const btn = _clEl("button", "cl-item-btn");
      btn.type = "button";
      btn.addEventListener("click", () => _clOpen(s.id));
      const top = _clEl("div", "cl-item-top");
      top.append(_clEl("span", "cl-item-title", s.title || s.first_prompt || "Untitled session"));
      if (s.live) top.append(_clEl("span", "cl-live cl-live-" + s.live, s.live === "busy" ? "● working" : "● open"));
      btn.append(top);
      btn.append(_clEl("div", "cl-item-folder", _clShortPath(s.cwd)));
      btn.append(_clEl("div", "cl-item-stats", `${_clAgo(s.updated)} · ${s.turns} turns · ${_clNum(_clTotalTokens(s))} tokens` + (s.subagents ? ` · ${s.subagents} subagent${s.subagents > 1 ? "s" : ""}` : "")));
      li.append(btn);
      return li;
    })
  );
}

async function _clOpen(id, quiet) {
  _clSelected = id;
  _clRenderList();
  document.body.classList.add("cl-reading");
  const box = document.getElementById("cl-messages");
  if (!quiet) box.replaceChildren(_clEl("p", "cl-muted", "Loading…"));
  try {
    const detail = await _clFetch("/api/claude/sessions/" + encodeURIComponent(id));
    if (_clSelected !== id) return; // another session was picked meanwhile
    _clRenderDetail(detail);
  } catch (ex) {
    box.replaceChildren(_clEl("p", "cl-error", ex.message));
  }
}

function _clRenderDetail(detail) {
  const s = detail.session;
  document.getElementById("cl-detail-title").textContent = s.title || "Untitled session";
  const t = s.tokens;
  const models = Object.entries(s.models).map(([m, n]) => `${m.replace(/^claude-/, "")} ×${n}`).join(", ");
  const meta = document.getElementById("cl-detail-meta");
  meta.replaceChildren(
    _clMeta("Folder", s.cwd || "—"),
    _clMeta("Started", _clDate(s.started)),
    _clMeta("Last active", _clDate(s.updated) + (s.live ? ` (${s.live === "busy" ? "working now" : "open now"})` : "")),
    _clMeta("Models", models || "—"),
    _clMeta("Tokens", `${_clNum(t.input_tokens + t.cache_creation_input_tokens)} in · ${_clNum(t.cache_read_input_tokens)} cache reads · ${_clNum(t.output_tokens)} out`),
    _clMeta("Session ID", s.id)
  );
  if (s.cost_usd != null) meta.append(_clMeta("Recorded cost", `$${s.cost_usd.toFixed(2)}`));

  const box = document.getElementById("cl-messages");
  const wasAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const nodes = [];
  if (detail.omitted) nodes.push(_clEl("p", "cl-muted", `${detail.omitted} earlier entries not shown.`));
  detail.messages.forEach((m) => {
    if (m.role === "tool") {
      const row = _clEl("div", "cl-msg cl-msg-tool");
      row.append(_clEl("span", "cl-tool-name", m.tool), _clEl("span", "cl-tool-text", m.text));
      nodes.push(row);
    } else {
      const row = _clEl("div", "cl-msg cl-msg-" + m.role);
      row.append(_clEl("div", "cl-msg-who", (m.role === "user" ? "You" : "Claude") + " · " + _clTime(m.ts)));
      row.append(_clEl("div", "cl-msg-text", m.text));
      nodes.push(row);
    }
  });
  if (!detail.messages.length) nodes.push(_clEl("p", "cl-muted", "No messages in this session."));
  box.replaceChildren(...nodes);
  if (wasAtBottom || !box.dataset.session || box.dataset.session !== s.id) box.scrollTop = box.scrollHeight;
  box.dataset.session = s.id;
}

// ── Small helpers ──
function _clEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text; // always text, never HTML: transcripts are untrusted
  return el;
}

function _clMeta(label, value) {
  const div = _clEl("div", "cl-meta-row");
  div.append(_clEl("span", "cl-meta-label", label), _clEl("span", "cl-meta-value", value));
  return div;
}

function _clTotalTokens(s) {
  const t = s.tokens;
  return t.input_tokens + t.cache_creation_input_tokens + t.cache_read_input_tokens + t.output_tokens;
}

function _clNum(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return Math.round(n / 1e3) + "k";
  return String(n);
}

function _clShortPath(p) {
  return (p || "").replace(/^\/home\/[^/]+/, "~") || "—";
}

function _clDate(iso) {
  return iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}

function _clTime(iso) {
  return iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
}

function _clAgo(iso) {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
