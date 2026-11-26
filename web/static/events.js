// ── Events — calendar / agenda, event details, create & edit, photo uploads ──

"use strict";

const _EV_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const _EV_REFRESH_MS = 60_000;
const _EV_DEFAULT_IMAGE = "/images/event%20default.svg";
const _EV_VIEW_KEY = "meshbot.events.view";
const _EV_UPLOADER_KEY = "meshbot.events.uploader";
const _EV_FULL_MAX_DIM = 1600;
const _EV_THUMB_MAX_DIM = 400;
const _EV_URL_RE = /(https?:\/\/[^\s<>"']+)/gi;
const _EV_STATUS_LABELS = { upcoming: "Upcoming", active: "Happening now", past: "Past" };

// State
let _evEvents = [];
let _evYear = new Date().getFullYear();
let _evMonth = new Date().getMonth(); // 0-based
let _evSelectedKey = null; // "YYYY-MM-DD"
let _evView = "calendar";
let _evDetailId = null;
let _evDetailOcc = null; // {start, end} of the repeat date being shown, if picked from a card
let _evEditing = null; // event being edited, or null for a new one
let _evFormImage = null; // { full: Blob, thumb: Blob } chosen in the form
let _evFormRemoveImage = false;
let _evPreviewUrl = null;
let _evAuth = { enabled: false, editor: false };
let _evAfterSignIn = null; // action to run once the organizer signs in

// ── Initialisation ──────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const label = document.getElementById("refresh-label");
  if (label) label.textContent = "Auto-refresh: " + _EV_REFRESH_MS / 1000 + "s";

  document.getElementById("ev-prev-btn").addEventListener("click", () => _evShiftMonth(-1));
  document.getElementById("ev-next-btn").addEventListener("click", () => _evShiftMonth(1));
  document.getElementById("ev-agenda-prev-btn").addEventListener("click", () => _evShiftMonth(-1));
  document.getElementById("ev-agenda-next-btn").addEventListener("click", () => _evShiftMonth(1));
  document.getElementById("ev-today-btn").addEventListener("click", _evGoToday);
  document.getElementById("ev-view-calendar").addEventListener("click", () => _evSetView("calendar"));
  document.getElementById("ev-view-agenda").addEventListener("click", () => _evSetView("agenda"));
  document.getElementById("ev-new-btn").addEventListener("click", () => _evOpenForm(null));
  document.getElementById("ev-auth-btn").addEventListener("click", _evAuthButtonClick);
  document.getElementById("ev-auth-form").addEventListener("submit", _evSubmitSignIn);
  document.getElementById("ev-auth-reveal").addEventListener("click", () => {
    const input = document.getElementById("ev-auth-passcode");
    _evShowPasscode(input.type === "password");
    input.focus();
  });
  document.getElementById("ev-auth-dialog").addEventListener("close", () => {
    _evAfterSignIn = null;
  });

  document.querySelectorAll("dialog [data-close]").forEach((btn) => btn.addEventListener("click", () => btn.closest("dialog").close()));
  document.querySelectorAll("dialog.ev-dialog").forEach((dlg) => {
    // Click on the backdrop closes the dialog.
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg) dlg.close();
    });
  });
  document.getElementById("ev-detail-dialog").addEventListener("close", () => {
    _evDetailId = null;
  });

  _evInitForm();

  let savedView = null;
  try {
    savedView = localStorage.getItem(_EV_VIEW_KEY);
  } catch (_) {
    /* storage unavailable */
  }
  _evSetView(savedView === "agenda" ? "agenda" : "calendar");

  _evLoadAuth();
  // Open on today's events; a shared ?id= link jumps to that event instead.
  if (!new URLSearchParams(location.search).get("id")) _evSelectedKey = _evKey(new Date());
  _evLoad().then(() => {
    const wanted = new URLSearchParams(location.search).get("id");
    if (wanted) {
      const ev = _evEvents.find((e) => e.id === wanted);
      if (ev) {
        _evJumpTo(_evNextOccurrence(ev)._start);
        _evOpenDetail(ev.id);
      }
    }
  });
  setInterval(_evLoad, _EV_REFRESH_MS);
});

// Called by the header's Refresh button.
function refreshAll() {
  _evLoad();
}

// ── Organizer sign-in ───────────────────────────────────────────────────────

async function _evLoadAuth() {
  try {
    const res = await fetch("/api/events/auth");
    if (res.ok) _evAuth = await res.json();
  } catch (_) {
    /* keep current state */
  }
  _evApplyAuth();
}

function _evApplyAuth() {
  const authBtn = document.getElementById("ev-auth-btn");
  authBtn.hidden = !_evAuth.enabled;
  authBtn.textContent = _evAuth.editor ? "🔓 Organizer · Sign out" : "🔒 Organizer sign-in";
  authBtn.title = _evAuth.editor ? "Signed in as an organizer. Click to sign out." : "Sign in to add, edit or delete events.";
  // Visitors submit events for review; "Edit" asks them to sign in first.
  const newBtn = document.getElementById("ev-new-btn");
  newBtn.hidden = !_evAuth.enabled;
  newBtn.textContent = _evAuth.editor ? "＋ New Event" : "＋ Submit an Event";
  document.querySelectorAll("[data-editor-only]").forEach((el) => (el.hidden = !_evAuth.enabled));
}

async function _evAuthButtonClick() {
  if (_evAuth.editor) {
    try {
      const res = await fetch("/api/events/auth", { method: "DELETE" });
      if (res.ok) _evAuth = await res.json();
    } catch (_) {
      /* ignore */
    }
    _evApplyAuth();
    const dlg = document.getElementById("ev-detail-dialog");
    const openId = _evDetailId;
    await _evLoad();
    if (dlg.open && !_evFind(openId)) dlg.close();
  } else {
    _evRequireSignIn(null);
  }
}

// Runs action now if signed in; otherwise asks for the passcode and runs it after.
function _evRequireSignIn(action, message) {
  if (_evAuth.editor && action) {
    action();
    return;
  }
  const form = document.getElementById("ev-auth-form");
  form.reset();
  _evShowPasscode(false); // always start hidden
  const err = document.getElementById("ev-auth-error");
  err.hidden = !message;
  err.textContent = message || "";
  const dlg = document.getElementById("ev-auth-dialog");
  if (!dlg.open) dlg.showModal();
  _evAfterSignIn = action;
  form.elements.passcode.focus();
}

// Eye button on the sign-in passcode: show (true) or hide (false) what's typed.
function _evShowPasscode(show) {
  const input = document.getElementById("ev-auth-passcode");
  const btn = document.getElementById("ev-auth-reveal");
  input.type = show ? "text" : "password";
  const label = show ? "Hide passcode" : "Show passcode";
  btn.setAttribute("aria-pressed", String(show));
  btn.setAttribute("aria-label", label);
  btn.title = label;
  btn.classList.toggle("is-showing", show);
}

async function _evSubmitSignIn(e) {
  e.preventDefault();
  const form = e.target;
  const err = document.getElementById("ev-auth-error");
  const btn = document.getElementById("ev-auth-submit");
  btn.disabled = true;
  try {
    const res = await fetch("/api/events/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode: form.elements.passcode.value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Sign-in failed.");
    _evAuth = data;
    _evApplyAuth();
    const action = _evAfterSignIn;
    document.getElementById("ev-auth-dialog").close();
    await _evLoad();
    if (action) action();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
    form.elements.passcode.select();
  } finally {
    btn.disabled = false;
  }
}

// ── Data ────────────────────────────────────────────────────────────────────

async function _evLoad() {
  const errorBox = document.getElementById("ev-load-error");
  try {
    const res = await fetch("/api/events");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load events.");
    _evEvents = (data.events || []).map((e) => Object.assign(e, _evEventTimes(e)));
    errorBox.hidden = true;
    _evRenderReviewBar();
  } catch (err) {
    errorBox.textContent = "⚠ " + (err.message || "Could not load events.");
    errorBox.hidden = false;
  }
  _evRender();
}

// Organizers see a bar listing submissions that wait for review.
function _evRenderReviewBar() {
  const bar = document.getElementById("ev-review-bar");
  const pending = _evEvents.filter((e) => !_evIsApproved(e)).sort((a, b) => a._start - b._start);
  bar.innerHTML = "";
  bar.hidden = !pending.length;
  if (!pending.length) return;
  bar.appendChild(_el("span", { class: "ev-review-bar-label" }, `⏳ ${pending.length} event${pending.length === 1 ? "" : "s"} waiting for review:`));
  pending.forEach((ev) => {
    const b = _el("button", { type: "button", class: "ev-review-chip" }, `${ev.name} · ${_evFmtDate(ev._start, false)}`);
    b.addEventListener("click", () => {
      _evJumpTo(ev._start);
      _evOpenDetail(ev.id);
    });
    bar.appendChild(b);
  });
}

function _evIsApproved(ev) {
  return ev.approved !== false;
}

function _evShowNotice(message) {
  const box = document.getElementById("ev-notice");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(_evShowNotice._timer);
  _evShowNotice._timer = setTimeout(() => (box.hidden = true), 12_000);
}

function _evFind(id) {
  return _evEvents.find((e) => e.id === id) || null;
}

// ── Dates ───────────────────────────────────────────────────────────────────

function _evKey(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

function _evDateFromKey(key) {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

// ── Repeating events ────────────────────────────────────────────────────────

const _EV_REPEAT_LABELS = { weekly: "Weekly", biweekly: "Every other week", monthly: "Monthly", yearly: "Yearly" };
const _EV_RRULES = { weekly: "FREQ=WEEKLY", biweekly: "FREQ=WEEKLY;INTERVAL=2", monthly: "FREQ=MONTHLY", yearly: "FREQ=YEARLY" };
const _EV_MAX_OCCURRENCES = 2100;

function _evIsRepeating(ev) {
  return !!_EV_RRULES[ev.recurrence];
}

// The n-th repeat start of a series (local wall-clock time), or null when that
// month/year has no such day (the 31st skips short months, Feb 29 non-leap years).
function _evShiftStart(base, recurrence, n) {
  const y = base.getFullYear(), m = base.getMonth(), d = base.getDate(), h = base.getHours(), mi = base.getMinutes();
  if (recurrence === "weekly") return new Date(y, m, d + 7 * n, h, mi);
  if (recurrence === "biweekly") return new Date(y, m, d + 14 * n, h, mi);
  const months = recurrence === "monthly" ? n : 12 * n;
  const t = new Date(y, m + months, d, h, mi);
  return t.getDate() === d ? t : null;
}

function _evOccStatus(start, end) {
  const now = new Date();
  if (end <= now) return "past";
  return start <= now ? "active" : "upcoming";
}

// Occurrences of ev that overlap [from, to). Each is a copy of the event with
// its own _start/_end and status. One-off events return themselves.
function _evOccurrences(ev, from, to) {
  const overlaps = (s, e) => s < to && (e > from || (+s === +e && s >= from));
  if (!_evIsRepeating(ev)) return overlaps(ev._start, ev._end) ? [ev] : [];
  const result = [];
  const duration = ev._end - ev._start;
  const spanDays = ev.all_day ? Math.round(duration / 86400_000) : 0;
  const until = ev.repeat_until || null;
  const skipped = new Set(ev.skip_dates || []);
  for (let n = 0; n < _EV_MAX_OCCURRENCES; n++) {
    const s = _evShiftStart(ev._start, ev.recurrence, n);
    if (!s) continue;
    if (until && _evKey(s) > until) break;
    if (s >= to) break;
    if (skipped.has(_evKey(s))) continue; // a single date removed from the series
    const e = ev.all_day ? new Date(s.getFullYear(), s.getMonth(), s.getDate() + spanDays) : new Date(s.getTime() + duration);
    if (overlaps(s, e)) result.push(Object.assign({}, ev, { _start: s, _end: e, _occ: true, status: _evOccStatus(s, e) }));
  }
  return result;
}

// The date that matters now: happening, else next, else the last one.
function _evNextOccurrence(ev) {
  if (!_evIsRepeating(ev)) return ev;
  const now = new Date();
  const duration = ev._end - ev._start;
  const spanDays = ev.all_day ? Math.round(duration / 86400_000) : 0;
  let last = null;
  const skipped = new Set(ev.skip_dates || []);
  for (let n = 0; n < _EV_MAX_OCCURRENCES; n++) {
    const s = _evShiftStart(ev._start, ev.recurrence, n);
    if (!s) continue;
    if (ev.repeat_until && _evKey(s) > ev.repeat_until) break;
    if (skipped.has(_evKey(s))) continue;
    const e = ev.all_day ? new Date(s.getFullYear(), s.getMonth(), s.getDate() + spanDays) : new Date(s.getTime() + duration);
    const occ = { _start: s, _end: e };
    if (e > now) {
      last = occ;
      break;
    }
    last = occ;
  }
  return last ? Object.assign({}, ev, last, { _occ: true, status: _evOccStatus(last._start, last._end) }) : ev;
}

// "Every week on Thursday · until Mar 1, 2027"
function _evRepeatText(ev) {
  const s = ev._start;
  const weekday = s.toLocaleDateString(undefined, { weekday: "long" });
  const day = s.getDate();
  const suffix = day % 10 === 1 && day !== 11 ? "st" : day % 10 === 2 && day !== 12 ? "nd" : day % 10 === 3 && day !== 13 ? "rd" : "th";
  let text = {
    weekly: `Every week on ${weekday}`,
    biweekly: `Every other week on ${weekday}`,
    monthly: `Every month on the ${day}${suffix}`,
    yearly: `Every year on ${s.toLocaleDateString(undefined, { month: "long", day: "numeric" })}`,
  }[ev.recurrence] || "";
  if (text && ev.repeat_until) text += ` · until ${_evFmtDate(_evDateFromKey(ev.repeat_until), true)}`;
  return text;
}

// Events (with repeats expanded) that overlap the local calendar day starting at dayStart.
function _evEventsOnDay(dayStart) {
  const dayEnd = new Date(dayStart.getFullYear(), dayStart.getMonth(), dayStart.getDate() + 1);
  return _evEvents.flatMap((e) => _evOccurrences(e, dayStart, dayEnd)).sort((a, b) => a._start - b._start);
}

function _evEventsInMonth(year, month) {
  const monthStart = new Date(year, month, 1);
  const monthEnd = new Date(year, month + 1, 1);
  return _evEvents.flatMap((e) => _evOccurrences(e, monthStart, monthEnd)).sort((a, b) => a._start - b._start);
}

function _evFmtDate(date, withYear) {
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: withYear ? "numeric" : undefined });
}

function _evFmtTime(date) {
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

// All-day events run from local midnight on start_day to local midnight after
// end_day (their dates are kept, so they land on the same days everywhere).
function _evEventTimes(e) {
  if (e.all_day && e.start_day && e.end_day) {
    const first = _evDateFromKey(e.start_day);
    const last = _evDateFromKey(e.end_day);
    return { _start: first, _end: new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1) };
  }
  return { _start: new Date(e.start), _end: new Date(e.end) };
}

// Last day of an all-day event (its _end is the following midnight).
function _evLastDay(ev) {
  return new Date(ev._end.getFullYear(), ev._end.getMonth(), ev._end.getDate() - 1);
}

function _evFmtRange(ev) {
  const s = ev._start;
  const e = ev._end;
  if (ev.all_day) {
    const last = _evLastDay(ev);
    if (_evKey(s) === _evKey(last)) return `${_evFmtDate(s, true)} · All day`;
    return `${_evFmtDate(s, s.getFullYear() !== last.getFullYear())} – ${_evFmtDate(last, true)} · All day`;
  }
  if (_evKey(s) === _evKey(e)) return `${_evFmtDate(s, true)} · ${_evFmtTime(s)} – ${_evFmtTime(e)}`;
  return `${_evFmtDate(s, true)} ${_evFmtTime(s)} – ${_evFmtDate(e, true)} ${_evFmtTime(e)}`;
}

// "datetime-local" input value for a Date, in local time.
function _evLocalInputValue(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}`;
}

// ── View switching / navigation ─────────────────────────────────────────────

function _evSetView(view) {
  _evView = view;
  try {
    localStorage.setItem(_EV_VIEW_KEY, view);
  } catch (_) {
    /* storage unavailable */
  }
  document.getElementById("ev-calendar-view").hidden = view !== "calendar";
  document.getElementById("ev-agenda-view").hidden = view !== "agenda";
  const calBtn = document.getElementById("ev-view-calendar");
  const agBtn = document.getElementById("ev-view-agenda");
  calBtn.classList.toggle("active", view === "calendar");
  agBtn.classList.toggle("active", view === "agenda");
  calBtn.setAttribute("aria-pressed", String(view === "calendar"));
  agBtn.setAttribute("aria-pressed", String(view === "agenda"));
  _evRender();
}

function _evShiftMonth(delta) {
  const d = new Date(_evYear, _evMonth + delta, 1);
  _evYear = d.getFullYear();
  _evMonth = d.getMonth();
  _evSelectedKey = null;
  _evRender();
}

function _evJumpTo(date) {
  _evYear = date.getFullYear();
  _evMonth = date.getMonth();
  _evSelectedKey = _evKey(date);
  _evRender();
}

function _evGoToday() {
  _evJumpTo(new Date());
}

function _evRender() {
  const label = `${_EV_MONTHS[_evMonth]} ${_evYear}`;
  document.getElementById("ev-month-label").textContent = label;
  document.getElementById("ev-agenda-label").textContent = label;
  if (_evView === "calendar") {
    _evRenderCalendar();
    _evRenderDay();
  } else {
    _evRenderAgenda();
  }
}

// ── Calendar ────────────────────────────────────────────────────────────────

function _evRenderCalendar() {
  const grid = document.getElementById("ev-calendar-grid");
  const headers = Array.from(grid.querySelectorAll(".tih-day-header"));
  grid.innerHTML = "";
  headers.forEach((h) => grid.appendChild(h));

  const firstDay = new Date(_evYear, _evMonth, 1).getDay();
  const daysInMonth = new Date(_evYear, _evMonth + 1, 0).getDate();
  const todayKey = _evKey(new Date());

  for (let i = 0; i < firstDay; i++) grid.appendChild(_el("div", { class: "tih-day-cell tih-day-empty" }));

  for (let day = 1; day <= daysInMonth; day++) {
    const date = new Date(_evYear, _evMonth, day);
    const key = _evKey(date);
    const dayEvents = _evEventsOnDay(date);
    const cell = _el("button", { type: "button", class: "tih-day-cell ev-day-cell" });
    if (dayEvents.length) cell.classList.add("has-data");
    if (dayEvents.some((e) => e.status === "active")) cell.classList.add("has-active");
    if (dayEvents.some((e) => !_evIsApproved(e))) cell.classList.add("has-pending");
    if (key === todayKey) cell.classList.add("is-today");
    if (key === _evSelectedKey) cell.classList.add("selected");
    cell.appendChild(_el("span", { class: "tih-day-num" }, String(day)));
    if (dayEvents.length) {
      const count = dayEvents.length > 1 ? String(dayEvents.length) : "";
      cell.appendChild(_el("span", { class: "ev-day-badge" }, [_el("span", { class: "tih-day-dot" }), count]));
      cell.title = dayEvents.map((e) => e.name).join("\n");
    }
    cell.addEventListener("click", () => {
      _evSelectedKey = key;
      _evRenderCalendar();
      _evRenderDay();
    });
    grid.appendChild(cell);
  }
}

function _evRenderDay() {
  const header = document.getElementById("ev-day-header");
  const list = document.getElementById("ev-day-list");
  if (!_evSelectedKey) {
    const monthCount = _evEventsInMonth(_evYear, _evMonth).length;
    header.textContent = "Select a date to see events";
    list.innerHTML = "";
    list.appendChild(
      _el(
        "p",
        { class: "tih-events-empty" },
        monthCount ? `🎉 ${monthCount} event${monthCount === 1 ? "" : "s"} this month — days with a dot have events.` : "No events this month yet. Use the button above to add one."
      )
    );
    return;
  }
  const date = _evDateFromKey(_evSelectedKey);
  header.textContent = date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const dayEvents = _evEventsOnDay(date);
  list.innerHTML = "";
  if (!dayEvents.length) {
    list.appendChild(_el("p", { class: "tih-events-empty" }, "No events on this day."));
    const add = _el("button", { type: "button", class: "ev-link-btn", "data-editor-only": "" }, "+ Add an event on this day");
    add.hidden = !_evAuth.enabled;
    add.addEventListener("click", () => _evOpenForm(null, date));
    list.appendChild(add);
    return;
  }
  dayEvents.forEach((ev) => list.appendChild(_evCard(ev)));
}

// ── Agenda ──────────────────────────────────────────────────────────────────

function _evRenderAgenda() {
  const list = document.getElementById("ev-agenda-list");
  list.innerHTML = "";
  const monthStart = new Date(_evYear, _evMonth, 1);
  const monthEvents = _evEventsInMonth(_evYear, _evMonth);
  if (!monthEvents.length) {
    list.appendChild(_el("p", { class: "tih-events-empty" }, "No events this month."));
    return;
  }
  let lastKey = null;
  let group = null;
  monthEvents.forEach((ev) => {
    // Events that began last month are listed under the 1st.
    const anchor = ev._start < monthStart ? monthStart : ev._start;
    const key = _evKey(anchor);
    if (key !== lastKey) {
      lastKey = key;
      const isToday = key === _evKey(new Date());
      group = _el("div", { class: "ev-agenda-group" }, [_el("div", { class: "ev-agenda-date" + (isToday ? " is-today" : "") }, _evFmtDate(anchor, false) + (isToday ? " · Today" : ""))]);
      list.appendChild(group);
    }
    group.appendChild(_evCard(ev));
  });
}

// ── Event card (list item) ──────────────────────────────────────────────────

function _evThumbUrl(ev) {
  return ev.has_image ? `/events/${ev.id}/image/cover_thumb?v=${encodeURIComponent(ev.updated_at || "")}` : _EV_DEFAULT_IMAGE;
}

function _evImageUrl(ev) {
  return ev.has_image ? `/events/${ev.id}/image/cover?v=${encodeURIComponent(ev.updated_at || "")}` : _EV_DEFAULT_IMAGE;
}

function _evLocationText(ev) {
  const loc = ev.location || {};
  return loc.type === "online" ? "💻 Online" : "📍 " + (loc.address || "");
}

function _evStatusBadge(ev) {
  if (!_evIsApproved(ev)) return _el("span", { class: "ev-status ev-status-pending" }, "Pending review");
  return _el("span", { class: "ev-status ev-status-" + ev.status }, _EV_STATUS_LABELS[ev.status] || ev.status);
}

function _evCard(ev) {
  const card = _el("button", { type: "button", class: "ev-card ev-card-" + ev.status + (_evIsApproved(ev) ? "" : " ev-card-pending") }, [
    _el("img", { class: "ev-card-thumb", src: _evThumbUrl(ev), alt: "", loading: "lazy" }),
    _el("div", { class: "ev-card-body" }, [
      _el("div", { class: "ev-card-title-row" }, [_el("span", { class: "ev-card-title" }, ev.name), _evStatusBadge(ev)]),
      _el("div", { class: "ev-card-meta" }, _evFmtRange(ev) + (_evIsRepeating(ev) ? ` · ↻ ${_EV_REPEAT_LABELS[ev.recurrence]}` : "")),
      _el("div", { class: "ev-card-meta" }, _evLocationText(ev)),
    ]),
  ]);
  // A repeat's card opens the event showing that date.
  card.addEventListener("click", () => _evOpenDetail(ev.id, ev._occ ? ev : null));
  return card;
}

// ── Detail dialog ───────────────────────────────────────────────────────────

// occ: the particular date of a repeating event to show (default: the next one).
function _evOpenDetail(id, occ) {
  const ev = _evFind(id);
  if (!ev) return;
  _evDetailId = id;
  _evDetailOcc = occ ? { start: +occ._start, end: +occ._end } : null;
  _evRenderDetail(ev);
  const dlg = document.getElementById("ev-detail-dialog");
  if (!dlg.open) dlg.showModal();
}

function _evMapsUrl(address) {
  return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(address);
}

function _evRenderDetail(ev) {
  const body = document.getElementById("ev-detail-body");
  body.innerHTML = "";

  const hero = _el("a", { href: _evImageUrl(ev), target: "_blank", rel: "noopener", class: "ev-detail-hero" + (ev.has_image ? "" : " is-default") }, [_el("img", { src: _evImageUrl(ev), alt: ev.name })]);
  body.appendChild(hero);

  body.appendChild(_el("div", { class: "ev-detail-title-row" }, [_el("h2", { class: "ev-detail-title" }, ev.name), _evStatusBadge(ev)]));
  if (!_evIsApproved(ev)) body.appendChild(_evReviewPanel(ev));

  const rows = _el("dl", { class: "ev-detail-rows" });
  const addRow = (label, content) => {
    rows.appendChild(_el("dt", {}, label));
    rows.appendChild(_el("dd", {}, content));
  };
  if (_evIsRepeating(ev)) {
    const picked = _evDetailId === ev.id && _evDetailOcc ? Object.assign({}, ev, { _start: new Date(_evDetailOcc.start), _end: new Date(_evDetailOcc.end) }) : _evNextOccurrence(ev);
    const upcomingLabel = picked._end <= new Date() ? "Last" : picked._start <= new Date() ? "Now" : "When";
    const whenParts = [_el("span", {}, _evFmtRange(picked))];
    if (picked !== ev) {
      // Organizers can remove just this one date from the series.
      const skipBtn = _el("button", { type: "button", class: "ev-skip-btn", "data-editor-only": "" }, "🗑 Delete this date only");
      skipBtn.hidden = !_evAuth.enabled;
      skipBtn.addEventListener("click", () => _evRequireSignIn(() => _evSkipDate(ev, picked)));
      whenParts.push(skipBtn);
    }
    addRow(upcomingLabel, whenParts);
    addRow("Repeats", "↻ " + _evRepeatText(ev));
    const skips = (ev.skip_dates || []).slice().sort();
    if (skips.length) {
      addRow(
        "Skipped",
        _el(
          "span",
          { class: "ev-skips" },
          skips.map((day) => {
            const chip = _el("span", { class: "ev-skip-chip" }, [_el("span", { class: "ev-skip-day" }, "not on " + _evFmtDate(_evDateFromKey(day), true))]);
            const restore = _el("button", { type: "button", class: "ev-link-btn ev-restore-btn", "data-editor-only": "" }, "Restore");
            restore.hidden = !_evAuth.enabled;
            restore.addEventListener("click", () => _evRequireSignIn(() => _evRestoreDate(ev, day)));
            chip.appendChild(restore);
            return chip;
          })
        )
      );
    }
  } else {
    addRow("When", _evFmtRange(ev));
  }

  const loc = ev.location || {};
  if (loc.type === "online") {
    addRow("Where", [_el("span", {}, "Online — "), _evLink(loc.link, loc.link)]);
  } else {
    addRow("Where", _evLink(_evMapsUrl(loc.address || ""), loc.address || "", "Open in maps"));
  }
  if (ev.website) addRow("Website", _evLink(ev.website, ev.website));

  const c = ev.contact || {};
  const contactParts = [];
  if (c.name) contactParts.push(_el("div", {}, c.name));
  if (c.signal) {
    const sig = c.signal.trim();
    const sigPhone = sig.replace(/[^\d+]/g, "");
    const signalNode = /^\+?\d{7,15}$/.test(sigPhone) && !/[a-z]/i.test(sig) ? _evLink("https://signal.me/#p/" + (sigPhone.startsWith("+") ? sigPhone : "+1" + sigPhone), sig) : _el("span", { class: "ev-mono" }, sig);
    contactParts.push(_el("div", {}, ["Signal: ", signalNode]));
  }
  if (c.phone) {
    const digits = c.phone.replace(/[^\d+]/g, "");
    const phoneLine = _el("div", {}, ["Phone: ", _evLink("tel:" + digits, c.phone)]);
    if (c.phone_texts) {
      phoneLine.appendChild(document.createTextNode(" · "));
      phoneLine.appendChild(_evLink("sms:" + digits, "Send a text"));
    } else {
      phoneLine.appendChild(_el("span", { class: "ev-muted" }, " (calls only)"));
    }
    contactParts.push(phoneLine);
  }
  if (contactParts.length) addRow("Organizer", contactParts);
  body.appendChild(rows);

  if (ev.description) body.appendChild(_el("p", { class: "ev-detail-description" }, _evLinkify(ev.description)));

  // Photos
  const photos = ev.photos || [];
  const photoSection = _el("section", { class: "ev-photos" }, [_el("h3", {}, `Photos (${photos.length})`)]);
  if (ev.status === "active" && _evIsApproved(ev)) photoSection.appendChild(_evUploadBox(ev));
  else if (ev.status === "upcoming") photoSection.appendChild(_el("p", { class: "ev-muted" }, "Participants can add photos here while the event is happening."));
  if (photos.length) {
    const gallery = _el("div", { class: "ev-gallery" });
    photos
      .slice()
      .reverse()
      .forEach((p) => {
        const when = new Date(p.uploaded_at);
        const title = (p.uploader ? p.uploader + " · " : "") + _evFmtDate(when, false) + " " + _evFmtTime(when);
        gallery.appendChild(_el("a", { href: `/events/${ev.id}/image/${p.id}`, target: "_blank", rel: "noopener", title }, [_el("img", { src: `/events/${ev.id}/image/${p.id}_thumb`, alt: title, loading: "lazy" })]));
      });
    photoSection.appendChild(gallery);
  } else if (ev.status !== "upcoming") {
    photoSection.appendChild(_el("p", { class: "ev-muted" }, "No photos yet."));
  }
  body.appendChild(photoSection);

  const actions = _el("div", { class: "ev-form-actions" });
  const share = _el("button", { type: "button", class: "ev-secondary-btn" }, "🔗 Copy link");
  share.addEventListener("click", async () => {
    const url = `${location.origin}/events?id=${ev.id}`;
    try {
      await navigator.clipboard.writeText(url);
      share.textContent = "✓ Link copied";
    } catch (_) {
      prompt("Copy this link:", url);
    }
  });
  const edit = _el("button", { type: "button", class: "ev-primary-btn", "data-editor-only": "" }, "✎ Edit event");
  edit.hidden = !_evAuth.enabled;
  edit.addEventListener("click", () =>
    _evRequireSignIn(() => {
      document.getElementById("ev-detail-dialog").close();
      _evOpenForm(ev);
    })
  );
  actions.appendChild(share);
  // Offer "Add to calendar" for published events that haven't ended.
  if (_evIsApproved(ev) && ev.status !== "past") actions.appendChild(_evCalendarMenu(ev));
  actions.appendChild(_el("span", { class: "ev-spacer" }));
  actions.appendChild(edit);
  body.appendChild(actions);
}

// ── Add to calendar ─────────────────────────────────────────────────────────

function _evCalStamp(date) {
  // 20261126T190000Z (UTC), the format Google Calendar expects.
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function _evCalDetails(ev) {
  const loc = ev.location || {};
  const parts = [];
  if (ev.description) parts.push(ev.description);
  if (loc.type === "online" && loc.link) parts.push("Join online: " + loc.link);
  if (ev.website) parts.push("Website: " + ev.website);
  parts.push("Event page: " + `${location.origin}/events?id=${ev.id}`);
  return parts.join("\n\n").slice(0, 1500);
}

function _evCalLocation(ev) {
  const loc = ev.location || {};
  return loc.type === "online" ? loc.link || "Online" : loc.address || "";
}

function _evGoogleCalendarUrl(ev) {
  const p = new URLSearchParams({
    action: "TEMPLATE",
    text: ev.name,
    // All-day: dates only, end = the day after the last day.
    dates: ev.all_day ? `${_evKey(ev._start).replace(/-/g, "")}/${_evKey(ev._end).replace(/-/g, "")}` : `${_evCalStamp(ev._start)}/${_evCalStamp(ev._end)}`,
    details: _evCalDetails(ev),
    location: _evCalLocation(ev),
  });
  if (_evIsRepeating(ev)) {
    // The whole series: first date + RRULE (+ the event's time zone so repeats keep their local time).
    let rule = "RRULE:" + _EV_RRULES[ev.recurrence];
    if (ev.repeat_until) {
      const u = _evDateFromKey(ev.repeat_until);
      rule += ";UNTIL=" + (ev.all_day ? ev.repeat_until.replace(/-/g, "") : _evCalStamp(new Date(u.getFullYear(), u.getMonth(), u.getDate(), 23, 59, 59)));
    }
    p.set("recur", rule);
    if (ev.tz) p.set("ctz", ev.tz);
  }
  return "https://calendar.google.com/calendar/render?" + p.toString();
}

// host: outlook.live.com (personal) or outlook.office.com (work/school).
// Outlook's link can't carry repeats, so a repeating event adds its next date.
function _evOutlookUrl(series, host) {
  const ev = _evNextOccurrence(series);
  const p = new URLSearchParams({
    path: "/calendar/action/compose",
    rru: "addevent",
    subject: ev.name,
    startdt: ev.all_day ? _evKey(ev._start) : ev._start.toISOString(),
    enddt: ev.all_day ? _evKey(ev._end) : ev._end.toISOString(),
    body: _evCalDetails(ev),
    location: _evCalLocation(ev),
  });
  if (ev.all_day) p.set("allday", "true");
  return `https://${host}/calendar/0/action/compose?` + p.toString();
}

function _evCalendarMenu(ev) {
  const item = (href, label, download) => {
    const attrs = { href, class: "ev-cal-item", role: "menuitem" };
    if (download) attrs.download = "";
    else Object.assign(attrs, { target: "_blank", rel: "noopener noreferrer" });
    return _el("a", attrs, label);
  };
  const menu = _el("details", { class: "ev-cal" }, [
    _el("summary", { class: "ev-secondary-btn" }, "📅 Add to calendar"),
    _el("div", { class: "ev-cal-menu", role: "menu" }, [
      item(_evGoogleCalendarUrl(ev), "Google Calendar"),
      item(`/events/${ev.id}/calendar.ics`, "Apple Calendar / iPhone", true),
      item(_evOutlookUrl(ev, "outlook.live.com"), "Outlook.com" + (_evIsRepeating(ev) ? " (next date only)" : "")),
      item(_evOutlookUrl(ev, "outlook.office.com"), "Outlook (work or school)" + (_evIsRepeating(ev) ? " (next date only)" : "")),
      item(`/events/${ev.id}/calendar.ics`, "Other calendar app (.ics file)", true),
    ]),
  ]);
  // Close the menu after picking a calendar.
  menu.querySelectorAll(".ev-cal-item").forEach((a) => a.addEventListener("click", () => (menu.open = false)));
  return menu;
}

function _evReviewPanel(ev) {
  const error = _el("p", { class: "ev-error-text", hidden: "" });
  const approve = _el("button", { type: "button", class: "ev-primary-btn" }, "✓ Approve & publish");
  const reject = _el("button", { type: "button", class: "ev-danger-btn" }, "✕ Reject");
  approve.addEventListener("click", async () => {
    approve.disabled = true;
    try {
      const res = await fetch(`/api/events/${ev.id}/approve`, { method: "POST" });
      const result = await res.json().catch(() => ({}));
      if (res.status === 403 && result.auth_required) {
        _evAuth.editor = false;
        _evApplyAuth();
        _evRequireSignIn(() => approve.click(), result.error);
        return;
      }
      if (!res.ok) throw new Error(result.error || "Could not approve the event.");
      await _evLoad();
      const fresh = _evFind(ev.id);
      if (fresh) _evRenderDetail(fresh);
      _evShowNotice(`✓ “${ev.name}” is now published.`);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      approve.disabled = false;
    }
  });
  reject.addEventListener("click", async () => {
    if (!confirm(`Reject “${ev.name}”? The submission and its picture will be deleted.`)) return;
    try {
      const res = await fetch(`/api/events/${ev.id}`, { method: "DELETE" });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.error || "Could not reject the event.");
      document.getElementById("ev-detail-dialog").close();
      await _evLoad();
      _evShowNotice(`“${ev.name}” was rejected and deleted.`);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });
  return _el("div", { class: "ev-review-panel" }, [
    _el("p", {}, "⏳ Submitted for review — only organizers can see this event. Check the details (use Edit to fix anything), then approve it to publish it."),
    _el("div", { class: "ev-upload-buttons" }, [approve, reject]),
    error,
  ]);
}

function _evUploadBox(ev) {
  const status = _el("p", { class: "ev-upload-status", role: "status" });
  let savedName = "";
  try {
    savedName = localStorage.getItem(_EV_UPLOADER_KEY) || "";
  } catch (_) {
    /* storage unavailable */
  }
  const nameInput = _el("input", { type: "text", maxlength: "40", placeholder: "Your name (optional)", value: savedName, class: "ev-upload-name" });
  const camera = _el("input", { type: "file", accept: "image/*", capture: "environment", hidden: "" });
  const files = _el("input", { type: "file", accept: "image/*", multiple: "", hidden: "" });
  const onPick = (input) => async () => {
    const picked = Array.from(input.files || []);
    input.value = "";
    if (!picked.length) return;
    try {
      localStorage.setItem(_EV_UPLOADER_KEY, nameInput.value.trim());
    } catch (_) {
      /* storage unavailable */
    }
    await _evUploadPhotos(ev.id, picked, nameInput.value.trim(), status);
  };
  camera.addEventListener("change", onPick(camera));
  files.addEventListener("change", onPick(files));
  return _el("div", { class: "ev-upload" }, [
    _el("p", { class: "ev-upload-intro" }, "📸 This event is happening now — share your photos!"),
    nameInput,
    _el("div", { class: "ev-upload-buttons" }, [
      _el("label", { class: "ev-primary-btn" }, ["📷 Take a photo", camera]),
      _el("label", { class: "ev-secondary-btn" }, ["🖼 Upload photos", files]),
    ]),
    status,
  ]);
}

async function _evUploadPhotos(eventId, files, uploader, status) {
  let done = 0;
  let failed = 0;
  let lastError = "";
  for (const file of files) {
    status.textContent = `Uploading ${done + failed + 1} of ${files.length}…`;
    try {
      const { full, thumb } = await _evPrepareImage(file);
      const form = new FormData();
      form.append("uploader", uploader);
      form.append("photo", full, "photo.jpg");
      form.append("thumb", thumb, "thumb.jpg");
      const res = await fetch(`/api/events/${eventId}/photos`, { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Upload failed.");
      done++;
    } catch (err) {
      failed++;
      lastError = err.message || "Upload failed.";
    }
  }
  status.textContent = failed ? `${done} uploaded, ${failed} failed: ${lastError}` : `✓ ${done} photo${done === 1 ? "" : "s"} uploaded. Thanks!`;
  status.classList.toggle("ev-error-text", failed > 0);
  await _evLoad();
  const ev = _evFind(eventId);
  if (ev && _evDetailId === eventId) {
    const message = status.textContent;
    const isError = failed > 0;
    _evRenderDetail(ev);
    const fresh = document.querySelector("#ev-detail-body .ev-upload-status");
    if (fresh) {
      fresh.textContent = message;
      fresh.classList.toggle("ev-error-text", isError);
    }
  }
}

// ── Image preparation (resize in the browser; also strips GPS/EXIF data) ────

function _evLoadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file isn’t an image this browser can read."));
    };
    img.src = url;
  });
}

function _evScaleToJpeg(img, maxDim, quality) {
  const w = img.naturalWidth;
  const h = img.naturalHeight;
  const scale = Math.min(1, maxDim / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(w * scale));
  canvas.height = Math.max(1, Math.round(h * scale));
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Could not process image."))), "image/jpeg", quality));
}

async function _evPrepareImage(file) {
  const img = await _evLoadImage(file);
  const full = await _evScaleToJpeg(img, _EV_FULL_MAX_DIM, 0.85);
  const thumb = await _evScaleToJpeg(img, _EV_THUMB_MAX_DIM, 0.8);
  return { full, thumb };
}

// ── Create / edit form ──────────────────────────────────────────────────────

function _evInitForm() {
  const form = document.getElementById("ev-form");
  form.querySelectorAll('input[name="location_type"]').forEach((r) => r.addEventListener("change", _evSyncLocationFields));
  form.addEventListener("submit", _evSubmitForm);

  document.getElementById("ev-form-image").addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    _evFieldError("image", "");
    try {
      _evFormImage = await _evPrepareImage(file);
      _evFormRemoveImage = false;
      _evSetPreview(URL.createObjectURL(_evFormImage.thumb), true);
    } catch (err) {
      _evFieldError("image", err.message);
    }
  });
  document.getElementById("ev-form-image-remove").addEventListener("click", () => {
    _evFormImage = null;
    _evFormRemoveImage = true;
    _evSetPreview(_EV_DEFAULT_IMAGE, false);
  });
  document.getElementById("ev-form-delete").addEventListener("click", _evDeleteEvent);

  form.elements.all_day.addEventListener("change", () => {
    _evSetAllDay(form.elements.all_day.checked);
    _evSyncRepeatFields();
  });
  form.elements.recurrence.addEventListener("change", _evSyncRepeatFields);
  form.elements.start_local.addEventListener("change", _evSyncRepeatFields);

  // Keep the end after the start when the start moves.
  form.elements.start_local.addEventListener("change", () => {
    if (form.elements.all_day.checked) {
      const sv = form.elements.start_local.value;
      if (sv && (!form.elements.end_local.value || form.elements.end_local.value < sv)) form.elements.end_local.value = sv;
      return;
    }
    const s = new Date(form.elements.start_local.value);
    const e = new Date(form.elements.end_local.value);
    if (!isNaN(s) && (isNaN(e) || e <= s)) form.elements.end_local.value = _evLocalInputValue(new Date(s.getTime() + 2 * 3600_000));
  });
}

// Switches the start/end inputs between date+time and date only, keeping
// the dates (and remembering the times so unticking brings them back).
function _evSetAllDay(on) {
  const form = document.getElementById("ev-form");
  const start = form.elements.start_local;
  const end = form.elements.end_local;
  if (on && start.type !== "date") {
    form.dataset.startTime = (start.value.split("T")[1] || "").slice(0, 5);
    form.dataset.endTime = (end.value.split("T")[1] || "").slice(0, 5);
    const sDay = start.value.slice(0, 10);
    let eDay = end.value.slice(0, 10);
    // A timed event ending exactly at midnight ends on the previous day.
    if (eDay && end.value.slice(11, 16) === "00:00" && eDay > sDay) eDay = _evKey(new Date(_evDateFromKey(eDay).getTime() - 86400_000));
    start.type = "date";
    end.type = "date";
    start.value = sDay;
    end.value = eDay || sDay;
  } else if (!on && start.type !== "datetime-local") {
    const sDay = start.value;
    const eDay = end.value || sDay;
    start.type = "datetime-local";
    end.type = "datetime-local";
    if (sDay) start.value = `${sDay}T${form.dataset.startTime || "18:00"}`;
    if (eDay) end.value = `${eDay}T${form.dataset.endTime || "20:00"}`;
  }
  form.elements.all_day.checked = on;
}

function _evSetPreview(src, removable) {
  if (_evPreviewUrl && _evPreviewUrl !== src) URL.revokeObjectURL(_evPreviewUrl);
  _evPreviewUrl = src.startsWith("blob:") ? src : null;
  document.getElementById("ev-form-image-preview").src = src;
  document.getElementById("ev-form-image-remove").hidden = !removable;
}

// Shows "Until" and a plain-English summary only when the event repeats.
function _evSyncRepeatFields() {
  const form = document.getElementById("ev-form");
  const recurrence = form.elements.recurrence.value;
  form.querySelectorAll("[data-repeat-only]").forEach((el) => (el.hidden = !recurrence));
  const hint = form.querySelector(".ev-repeat-hint");
  const sv = form.elements.start_local.value;
  const start = !sv ? null : form.elements.all_day.checked ? _evDateFromKey(sv) : new Date(sv);
  hint.textContent = recurrence && start && !isNaN(start) ? "↻ " + _evRepeatText({ _start: start, recurrence, repeat_until: form.elements.repeat_until.value }) : "";
}

function _evSyncLocationFields() {
  const form = document.getElementById("ev-form");
  const type = form.elements.location_type.value;
  form.querySelectorAll("[data-location]").forEach((el) => {
    el.hidden = el.dataset.location !== type;
  });
}

function _evFieldError(name, message) {
  const slot = document.querySelector(`#ev-form .ev-field-error[data-for="${name}"]`);
  if (slot) slot.textContent = message || "";
}

function _evClearErrors() {
  document.querySelectorAll("#ev-form .ev-field-error").forEach((s) => (s.textContent = ""));
  const box = document.getElementById("ev-form-error");
  box.hidden = true;
  box.textContent = "";
}

function _evOpenForm(ev, onDate) {
  const form = document.getElementById("ev-form");
  form.reset();
  _evSetAllDay(false);
  delete form.dataset.startTime;
  delete form.dataset.endTime;
  _evClearErrors();
  _evEditing = ev;
  _evFormImage = null;
  _evFormRemoveImage = false;
  const submitting = !ev && !_evAuth.editor;
  document.getElementById("ev-form-title").textContent = ev ? "Edit Event" : submitting ? "Submit an Event" : "New Event";
  document.getElementById("ev-form-review-note").hidden = !submitting;
  document.getElementById("ev-form-save").textContent = submitting ? "Submit for review" : "Save";
  document.getElementById("ev-form-delete").hidden = !ev;
  document.getElementById("ev-form-save").disabled = false;

  if (ev) {
    const loc = ev.location || {};
    const c = ev.contact || {};
    form.elements.name.value = ev.name || "";
    form.elements.description.value = ev.description || "";
    if (ev.all_day) {
      _evSetAllDay(true);
      form.elements.start_local.value = _evKey(ev._start);
      form.elements.end_local.value = _evKey(_evLastDay(ev));
    } else {
      form.elements.start_local.value = _evLocalInputValue(ev._start);
      form.elements.end_local.value = _evLocalInputValue(ev._end);
    }
    form.elements.location_type.value = loc.type === "online" ? "online" : "physical";
    form.elements.location_address.value = loc.address || "";
    form.elements.location_link.value = loc.link || "";
    form.elements.website.value = ev.website || "";
    form.elements.contact_name.value = c.name || "";
    form.elements.contact_signal.value = c.signal || "";
    form.elements.contact_phone.value = c.phone || "";
    form.elements.contact_phone_texts.checked = !!c.phone_texts;
    form.elements.recurrence.value = _EV_RRULES[ev.recurrence] ? ev.recurrence : "";
    form.elements.repeat_until.value = ev.repeat_until || "";
    _evSetPreview(_evThumbUrl(ev), !!ev.has_image);
  } else {
    // Default: the chosen day (or the next whole hour today), two hours long.
    const now = new Date();
    let start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1);
    if (onDate) start = new Date(onDate.getFullYear(), onDate.getMonth(), onDate.getDate(), 18);
    form.elements.start_local.value = _evLocalInputValue(start);
    form.elements.end_local.value = _evLocalInputValue(new Date(start.getTime() + 2 * 3600_000));
    _evSetPreview(_EV_DEFAULT_IMAGE, false);
  }
  _evSyncLocationFields();
  _evSyncRepeatFields();
  document.getElementById("ev-form-dialog").showModal();
  form.elements.name.focus();
}

async function _evSubmitForm(e) {
  e.preventDefault();
  const form = e.target;
  _evClearErrors();

  const allDay = form.elements.all_day.checked;
  let start;
  let end;
  const data = new FormData();
  if (allDay) {
    // Local midnight at the start of the first day to midnight after the last day.
    const sDay = form.elements.start_local.value;
    const eDay = form.elements.end_local.value;
    start = sDay ? _evDateFromKey(sDay) : new Date(NaN);
    const last = eDay ? _evDateFromKey(eDay) : new Date(NaN);
    end = new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1);
    data.append("all_day", "1");
    data.append("start_day", sDay);
    data.append("end_day", eDay);
  } else {
    start = new Date(form.elements.start_local.value);
    end = new Date(form.elements.end_local.value);
  }
  ["name", "description", "location_type", "location_address", "location_link", "website", "contact_name", "contact_signal", "contact_phone"].forEach((n) => data.append(n, form.elements[n].value.trim()));
  data.append("contact_phone_texts", form.elements.contact_phone_texts.checked ? "1" : "");
  data.append("recurrence", form.elements.recurrence.value);
  data.append("repeat_until", form.elements.recurrence.value ? form.elements.repeat_until.value : "");
  // Repeats keep their local time in this time zone (e.g. 7 PM across daylight saving).
  try {
    data.append("tz", Intl.DateTimeFormat().resolvedOptions().timeZone || "");
  } catch (_) {
    data.append("tz", "");
  }
  data.append("start", isNaN(start) ? "" : start.toISOString());
  data.append("end", isNaN(end) ? "" : end.toISOString());
  if (_evFormImage) {
    data.append("image", _evFormImage.full, "image.jpg");
    data.append("image_thumb", _evFormImage.thumb, "thumb.jpg");
  } else if (_evFormRemoveImage) {
    data.append("remove_image", "1");
  }

  const saveBtn = document.getElementById("ev-form-save");
  const saveLabel = saveBtn.textContent;
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";
  try {
    const url = _evEditing ? `/api/events/${_evEditing.id}` : "/api/events";
    const res = await fetch(url, { method: _evEditing ? "PUT" : "POST", body: data });
    const result = await res.json().catch(() => ({}));
    if (res.status === 403 && result.auth_required) {
      _evAuth.editor = false;
      _evApplyAuth();
      // Keep the form open; once signed in, save again automatically.
      _evRequireSignIn(() => document.getElementById("ev-form").requestSubmit(), result.error);
      throw new Error(result.error);
    }
    if (!res.ok) {
      Object.entries(result.fields || {}).forEach(([field, msg]) => _evFieldError(field, msg));
      throw new Error(result.error || "Could not save the event.");
    }
    document.getElementById("ev-form-dialog").close();
    if (result.pending) {
      _evShowNotice(`✓ Thanks! “${result.name}” was sent to the organizers. It will appear on the calendar once it's approved.`);
      return;
    }
    await _evLoad();
    const saved = _evFind(result.id);
    if (saved) {
      _evJumpTo(_evNextOccurrence(saved)._start);
      _evOpenDetail(saved.id);
    }
  } catch (err) {
    const box = document.getElementById("ev-form-error");
    box.textContent = err.message;
    box.hidden = false;
    box.scrollIntoView({ block: "nearest" });
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = saveLabel;
  }
}

// ── Remove / restore a single date of a repeating event ─────────────────────

async function _evSkipDate(ev, occ) {
  const day = _evKey(occ._start);
  const label = _evFmtDate(occ._start, true);
  if (!confirm(`Remove ${label} from “${ev.name}”?\n\nOnly this date is removed; the other dates stay. You can restore it later from the event's details.`)) return;
  await _evSkipRequest(ev, `/api/events/${ev.id}/skip`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: day }) }, `${label} was removed from “${ev.name}”.`);
}

async function _evRestoreDate(ev, day) {
  const label = _evFmtDate(_evDateFromKey(day), true);
  await _evSkipRequest(ev, `/api/events/${ev.id}/skip/${day}`, { method: "DELETE" }, `${label} is back on “${ev.name}”.`);
}

async function _evSkipRequest(ev, url, options, doneMessage) {
  try {
    const res = await fetch(url, options);
    const result = await res.json().catch(() => ({}));
    if (res.status === 403 && result.auth_required) {
      _evAuth.editor = false;
      _evApplyAuth();
      _evRequireSignIn(null, result.error);
      return;
    }
    if (!res.ok) throw new Error(result.error || "Could not change the event.");
    await _evLoad();
    // Show the event again (its next date, now that this one may be gone).
    _evDetailOcc = null;
    const fresh = _evFind(ev.id);
    if (fresh && document.getElementById("ev-detail-dialog").open) _evRenderDetail(fresh);
    _evShowNotice("✓ " + doneMessage);
  } catch (err) {
    _evShowNotice("⚠ " + err.message);
  }
}

async function _evDeleteEvent() {
  if (!_evEditing) return;
  const whole = _evIsRepeating(_evEditing) ? " — every date of this repeating event —" : "";
  const tip = _evIsRepeating(_evEditing) ? "\n\nTo remove just one date, open that date and use “Delete this date only” instead." : "";
  if (!confirm(`Delete “${_evEditing.name}”${whole} and all of its photos? This cannot be undone.${tip}`)) return;
  try {
    const res = await fetch(`/api/events/${_evEditing.id}`, { method: "DELETE" });
    const result = await res.json().catch(() => ({}));
    if (res.status === 403 && result.auth_required) {
      _evAuth.editor = false;
      _evApplyAuth();
      _evRequireSignIn(null, result.error);
    }
    if (!res.ok) throw new Error(result.error || "Could not delete the event.");
    document.getElementById("ev-form-dialog").close();
    await _evLoad();
  } catch (err) {
    const box = document.getElementById("ev-form-error");
    box.textContent = err.message;
    box.hidden = false;
  }
}

// ── DOM helpers ─────────────────────────────────────────────────────────────

// Builds an element; text children are added as text nodes (never as HTML).
function _el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  });
  const list = children === undefined || children === null ? [] : Array.isArray(children) ? children : [children];
  list.forEach((c) => node.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
  return node;
}

// Only http(s), tel: and sms: links are ever rendered as links.
function _evLink(href, text, title) {
  if (!/^(https?:\/\/|tel:|sms:)/i.test(href || "")) return _el("span", {}, text || "");
  const external = /^https?:/i.test(href);
  const attrs = { href, class: "ev-link" };
  if (external) Object.assign(attrs, { target: "_blank", rel: "noopener noreferrer" });
  if (title) attrs.title = title;
  return _el("a", attrs, text || href);
}

function _evLinkify(text) {
  const parts = [];
  let last = 0;
  text.replace(_EV_URL_RE, (match, _url, offset) => {
    // Leave trailing punctuation outside the link.
    const trimmed = match.replace(/[.,;:!?)\]]+$/, "");
    if (offset > last) parts.push(text.slice(last, offset));
    parts.push(_evLink(trimmed, trimmed));
    last = offset + trimmed.length;
    return match;
  });
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
