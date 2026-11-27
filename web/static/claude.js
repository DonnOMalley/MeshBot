// ── Claude page — read-only list of the Claude Code sessions on this computer ──
// Everything here needs the ClaudePasscode sign-in; the server returns 403 otherwise.

"use strict";

const _CL_REFRESH_MS = 30_000;
let _clSessions = [];
let _clSelected = null;
let _clTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  const label = document.getElementById("refresh-label");
  if (label) label.textContent = "";
  document.getElementById("cl-auth-form").addEventListener("submit", _clSignIn);
  document.getElementById("cl-signout").addEventListener("click", _clSignOut);
  document.getElementById("cl-filter").addEventListener("input", _clRenderList);
  document.getElementById("cl-show-tools").addEventListener("change", (e) => {
    document.getElementById("cl-messages").classList.toggle("cl-hide-tools", !e.target.checked);
  });
  document.getElementById("cl-back").addEventListener("click", () => document.body.classList.remove("cl-reading"));
  _clCheckAuth();
});

// Header "Refresh" button.
function refreshAll() {
  _clLoadList();
  if (_clSelected) _clOpen(_clSelected, true);
}

async function _clCheckAuth() {
  let auth = { enabled: false, viewer: false };
  try {
    auth = await (await fetch("/api/claude/auth")).json();
  } catch (_) {
    /* shown as signed out */
  }
  _clShow(auth);
}

function _clShow(auth) {
  document.getElementById("cl-signin").hidden = auth.viewer;
  document.getElementById("cl-app").hidden = !auth.viewer;
  const form = document.getElementById("cl-auth-form");
  if (!auth.enabled) {
    document.getElementById("cl-signin-text").textContent = "The Claude page is turned off. Set ClaudePasscode in meshbot.config to turn it on.";
    Array.from(form.elements).forEach((el) => (el.disabled = true));
  }
  clearInterval(_clTimer);
  if (auth.viewer) {
    _clLoadList();
    _clTimer = setInterval(_clLoadList, _CL_REFRESH_MS);
  } else {
    form.elements.passcode.focus();
  }
}

async function _clSignIn(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const err = document.getElementById("cl-auth-error");
  const btn = document.getElementById("cl-auth-submit");
  err.hidden = true;
  btn.disabled = true;
  try {
    const res = await fetch("/api/claude/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode: form.elements.passcode.value }),
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || "Sign-in failed.");
    form.reset();
    _clShow(result);
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
    form.elements.passcode.select();
  } finally {
    btn.disabled = false;
  }
}

async function _clSignOut() {
  await fetch("/api/claude/auth", { method: "DELETE" }).catch(() => {});
  _clSessions = [];
  _clSelected = null;
  document.getElementById("cl-messages").replaceChildren(_clEl("p", "cl-muted", "Pick a session to read it."));
  _clShow({ enabled: true, viewer: false });
}

// Fetches JSON; a 403 means the sign-in lapsed (passcode changed), so go back to the form.
async function _clFetch(url) {
  const res = await fetch(url);
  const result = await res.json();
  if (res.status === 403 && result.auth_required) {
    _clShow({ enabled: true, viewer: false });
    throw new Error(result.error);
  }
  if (!res.ok) throw new Error(result.error || "Request failed.");
  return result;
}

async function _clLoadList() {
  try {
    _clSessions = (await _clFetch("/api/claude/sessions")).sessions;
    _clRenderList();
  } catch (ex) {
    document.getElementById("cl-list").replaceChildren(_clEl("li", "cl-error", ex.message));
  }
}

function _clRenderList() {
  const query = document.getElementById("cl-filter").value.trim().toLowerCase();
  const shown = _clSessions.filter((s) => !query || [s.title, s.cwd, s.first_prompt].some((v) => (v || "").toLowerCase().includes(query)));
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
