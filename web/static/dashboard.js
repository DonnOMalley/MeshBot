// dashboard.js — Happening-now banner + Joy panel + upcoming Events + Today in History

"use strict";

// Month name lookup for the TIH panel header
const _MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// ── Events panel: agenda of what's coming up ───────────────────────────────

const _DASH_EVENTS_REFRESH_MS = 60_000;
const _DASH_EVENTS_DAYS = 30;
const _DASH_EVENTS_LIMIT = 8;
// The rail shows only the next few; its height sets the height of the Joy row.
const _DASH_EVENTS_SHOWN = 3;

async function _fetchUpcomingEvents() {
  const body = document.getElementById("dash-events-body");
  if (!body) return;
  try {
    // The server returns every happening-now date plus up to `limit` upcoming ones.
    const res = await fetch(`/api/events/upcoming?days=${_DASH_EVENTS_DAYS}&limit=${_DASH_EVENTS_LIMIT}`, { cache: "no-store" });
    if (!res.ok) throw new Error("load failed");
    const data = await res.json();
    const items = data.events || [];
    // Happening-now events go in the banner; the panel lists only what's next.
    _renderNowBanner(items.filter((o) => o.status === "active"));
    _renderUpcomingEvents(items.filter((o) => o.status !== "active").slice(0, _DASH_EVENTS_SHOWN));
  } catch (_) {
    if (!body.querySelector(".home-ev-list")) body.innerHTML = '<p class="home-empty">Events couldn’t load. They’ll retry in a minute, or use the refresh button.</p>';
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

// Full-width banner at the top: one clickable card per event that is on
// right now (with its picture when it has one). Hidden when nothing is on.
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
      const thumb = o.has_image ? `<img class="home-now-thumb" src="${_dashThumbSrc(o)}" alt="" />` : "";
      const where = _dashWhere(o);
      return `<a class="home-now-item" href="${_dashEventHref(o)}">
        ${thumb}
        <span class="home-now-text">
          <span class="home-now-label">&#127881; Happening now</span>
          <span class="home-now-name">${_escapeHtml(o.name)}</span>
          <span class="home-now-meta">${_escapeHtml(_dashWhen(o))}${where ? `<br />${_escapeHtml(where)}` : ""}</span>
        </span>
        <span class="home-now-open">View event</span>
      </a>`;
    })
    .join("");
  banner.hidden = false;
}

// The rail beside Joy: one picture card per upcoming date, soonest first.
function _renderUpcomingEvents(items) {
  const body = document.getElementById("dash-events-body");
  if (!items.length) {
    body.innerHTML = `<p class="home-empty">Nothing scheduled in the next ${_DASH_EVENTS_DAYS} days.<br /><a href="/events">Add an event</a></p>`;
    return;
  }
  body.innerHTML = `<ul class="home-ev-list">${items
    .map((o) => {
      const day = _dashDayLabel(o.all_day ? _dashDay(o.first_day) : new Date(o.start));
      const where = _dashWhere(o);
      const repeats = o.recurrence ? o.recurrence_label || "Repeats" : "";
      const pic = o.has_image
        ? `<img class="home-ev-pic" src="${_dashThumbSrc(o)}" alt="" loading="lazy" />`
        : `<span class="home-ev-pic home-ev-pic-blank" aria-hidden="true">&#127881;</span>`;
      return `<li><a class="home-ev-card" href="${_dashEventHref(o)}">
        ${pic}
        <span class="home-ev-text">
          <span class="home-ev-when">${_escapeHtml(day)}, ${_escapeHtml(_dashWhen(o))}</span>
          <span class="home-ev-name">${_escapeHtml(o.name)}</span>
          ${where ? `<span class="home-ev-where">${_escapeHtml(where)}</span>` : ""}
          ${repeats ? `<span class="home-ev-where">&#x21bb; ${_escapeHtml(repeats)}</span>` : ""}
        </span>
      </a></li>`;
    })
    .join("")}</ul>`;
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

// Joy reads as the page's headline: the affirmation large, then the quote
// with its author, then the joke. No labels; the type tells them apart.
function _renderJoy(data) {
  const body = document.getElementById("dash-joy-body");
  if (!body) return;

  const parts = [];
  if (data.affirmation) {
    parts.push(`<p class="home-joy-affirmation">${_escapeHtml(data.affirmation)}</p>`);
  }
  if (data.zen_quote && data.zen_quote.quote) {
    const author = data.zen_quote.author ? `<figcaption class="home-joy-author">${_escapeHtml(data.zen_quote.author)}</figcaption>` : "";
    parts.push(`<figure class="home-joy-quote"><blockquote>&ldquo;${_escapeHtml(data.zen_quote.quote)}&rdquo;</blockquote>${author}</figure>`);
  }
  if (data.joke) {
    parts.push(`<p class="home-joy-joke">${_escapeHtml(data.joke)}</p>`);
  }
  body.innerHTML = parts.length ? parts.join("") : '<p class="home-empty">Joy couldn’t load right now. Try the refresh button.</p>';
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
    titleEl.textContent = `\u{1F4C5} Today in history, ${monthName} ${day}`;
  }

  if (!events.length) {
    body.innerHTML = "";
    return;
  }

  body.innerHTML = `<ol class="home-tih-list">${events
    .map((e) => {
      const year = `<span class="home-tih-year">${_escapeHtml(e.year || "")}</span>`;
      const wiki = e.wikipedia ? ` <a class="home-tih-wiki" href="${_escapeHtml(e.wikipedia)}" target="_blank" rel="noopener" title="Read on Wikipedia">Wikipedia</a>` : "";
      return `<li>${year}<span class="home-tih-text">${_escapeHtml(e.text)}${wiki}</span></li>`;
    })
    .join("")}</ol>`;
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
