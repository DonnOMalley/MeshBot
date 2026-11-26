// dashboard.js — Happening-now banner + Joy panel + upcoming Events + Today in History

"use strict";

// Month name lookup for the TIH panel header
const _MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// ── Events panel: agenda of what's happening now and coming up ─────────────

const _DASH_EVENTS_REFRESH_MS = 60_000;
const _DASH_EVENTS_DAYS = 30;

async function _fetchUpcomingEvents() {
  const body = document.getElementById("dash-events-body");
  if (!body) return;
  try {
    const res = await fetch(`/api/events/upcoming?days=${_DASH_EVENTS_DAYS}&limit=8`, { cache: "no-store" });
    if (!res.ok) throw new Error("load failed");
    const data = await res.json();
    const items = data.events || [];
    _renderNowBanner(items.filter((o) => o.status === "active"));
    _renderUpcomingEvents(items);
  } catch (_) {
    if (!body.querySelector(".dash-ev-group")) body.innerHTML = '<p class="dash-events-empty">Couldn’t load events.</p>';
  }
}

function _dashDay(key) {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function _dashKey(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

// "Today", "Tomorrow", or "Wed, Dec 2".
function _dashDayLabel(date) {
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  if (_dashKey(date) === _dashKey(today)) return "Today";
  if (_dashKey(date) === _dashKey(tomorrow)) return "Tomorrow";
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function _dashTime(date) {
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

// Time text for one date: "7:00 PM – 9:00 PM", "All day", "Through Sun, Dec 6",
// or for one happening now "Until 9:00 PM".
function _dashWhen(o) {
  if (o.all_day) {
    const last = _dashDay(o.last_day);
    if (o.status === "active") return o.first_day === o.last_day ? "All day" : `Through ${_dashDayLabel(last)}`;
    return o.first_day === o.last_day ? "All day" : `All day, through ${_dashDayLabel(last)}`;
  }
  const s = new Date(o.start);
  const e = new Date(o.end);
  const endText = _dashKey(s) === _dashKey(e) ? _dashTime(e) : `${_dashDayLabel(e)} ${_dashTime(e)}`;
  return o.status === "active" ? `Until ${endText}` : `${_dashTime(s)} – ${endText}`;
}

function _dashEventHref(o) {
  return `/events?id=${encodeURIComponent(o.id)}`;
}

function _dashThumbSrc(o) {
  return `/events/${encodeURIComponent(o.id)}/image/cover_thumb?v=${encodeURIComponent(o.updated_at || "")}`;
}

function _dashWhere(o) {
  const loc = o.location || {};
  return loc.type === "online" ? "Online" : loc.address || "";
}

// Full-width banner above Joy + Events: one clickable card per event that is
// on right now (thumbnail when it has a picture). Hidden when nothing is on.
function _renderNowBanner(active) {
  const banner = document.getElementById("dash-now-banner");
  if (!banner) return;
  if (!active.length) {
    banner.hidden = true;
    banner.innerHTML = "";
    return;
  }
  banner.innerHTML = active
    .map((o) => {
      const thumb = o.has_image ? `<img class="dash-now-thumb" src="${_dashThumbSrc(o)}" alt="" />` : "";
      const meta = [_dashWhen(o), _dashWhere(o)].filter(Boolean).join(" · ");
      return `<a class="dash-now-item" href="${_dashEventHref(o)}" title="Open ${_escapeHtml(o.name)}">
        ${thumb}
        <span class="dash-now-text">
          <span class="dash-now-label">&#127881; Happening now</span>
          <span class="dash-now-name">${_escapeHtml(o.name)}</span>
          <span class="dash-now-meta">${_escapeHtml(meta)}</span>
        </span>
        <span class="dash-now-open" aria-hidden="true">Open &rarr;</span>
      </a>`;
    })
    .join("");
  banner.hidden = false;
}

function _renderUpcomingEvents(items) {
  const body = document.getElementById("dash-events-body");
  if (!items.length) {
    body.innerHTML = `<p class="dash-events-empty">No events in the next ${_DASH_EVENTS_DAYS} days.<br /><a href="/events">Open the Events page &rarr;</a></p>`;
    return;
  }
  // Group: happening now first, then by day.
  const groups = [];
  items.forEach((o) => {
    const label = o.status === "active" ? "Happening now" : _dashDayLabel(o.all_day ? _dashDay(o.first_day) : new Date(o.start));
    let group = groups.find((g) => g.label === label);
    if (!group) groups.push((group = { label, now: o.status === "active", rows: [] }));
    group.rows.push(o);
  });
  body.innerHTML = groups
    .map(
      (g) => `<div class="dash-ev-group${g.now ? " is-now" : ""}">
        <div class="dash-ev-day">${g.now ? "&#127881; " : ""}${_escapeHtml(g.label)}</div>
        <ul class="dash-ev-list">${g.rows
          .map((o) => {
            const meta = [_dashWhen(o), _dashWhere(o)].filter(Boolean).join(" · ") + (o.recurrence ? " · ↻" : "");
            const href = _dashEventHref(o);
            // Small thumbnail (half the Events page's) when the event has a picture.
            const thumb = o.has_image
              ? `<a class="dash-ev-thumb" href="${href}" tabindex="-1" aria-hidden="true"><img src="${_dashThumbSrc(o)}" alt="" loading="lazy" /></a>`
              : "";
            return `<li>${thumb}<div class="dash-ev-text"><a class="dash-ev-link" href="${href}">${_escapeHtml(o.name)}</a><span class="dash-ev-meta">${_escapeHtml(meta)}</span></div></li>`;
          })
          .join("")}</ul>
      </div>`
    )
    .join("");
}

// ── Joy panel ──────────────────────────────────────────────────────────────

async function _fetchJoy() {
  try {
    const res = await fetch("/api/joy", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    _renderJoy(data);
  } catch (_) {}
}

// Events ↻: reload the agenda now; spin the icon while loading.
async function _onEventsRefreshClick() {
  const btn = document.getElementById("dash-events-refresh");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    await _fetchUpcomingEvents();
  } finally {
    btn.classList.remove("spinning");
    btn.disabled = false;
  }
}

// Refresh button: fetch a new random set; spin the icon while loading and
// ignore extra clicks until the request finishes.
async function _onJoyRefreshClick() {
  const btn = document.getElementById("dash-joy-refresh");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    await _fetchJoy();
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

// ── Public API ─────────────────────────────────────────────────────────────

function dashboardInit() {
  _fetchJoy();
  _fetchUpcomingEvents();
  setInterval(_fetchUpcomingEvents, _DASH_EVENTS_REFRESH_MS);
  const eventsRefreshBtn = document.getElementById("dash-events-refresh");
  if (eventsRefreshBtn) eventsRefreshBtn.addEventListener("click", _onEventsRefreshClick);
  const joyRefreshBtn = document.getElementById("dash-joy-refresh");
  if (joyRefreshBtn) joyRefreshBtn.addEventListener("click", _onJoyRefreshClick);
  _fetchTodayInHistory();
}
