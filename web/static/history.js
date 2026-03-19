// ── Today in History — calendar + events page ─────────────────────────────

"use strict";

const _MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// State
let _currentMonth = new Date().getMonth() + 1; // 1-based
let _selectedDay = null;
let _daysWithData = new Set();

// ── Initialisation ────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("tih-prev-btn").addEventListener("click", _prevMonth);
  document.getElementById("tih-next-btn").addEventListener("click", _nextMonth);
  _loadMonth(_currentMonth);
});

// ── Month navigation ──────────────────────────────────────────────────────

function _prevMonth() {
  _currentMonth = _currentMonth === 1 ? 12 : _currentMonth - 1;
  _selectedDay = null;
  _loadMonth(_currentMonth);
}

function _nextMonth() {
  _currentMonth = _currentMonth === 12 ? 1 : _currentMonth + 1;
  _selectedDay = null;
  _loadMonth(_currentMonth);
}

async function _loadMonth(month) {
  document.getElementById("tih-month-label").textContent = _MONTH_NAMES[month - 1];
  _daysWithData = new Set();

  try {
    const res = await fetch(`/api/history-calendar?month=${month}`);
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.days_with_data)) {
        data.days_with_data.forEach((d) => _daysWithData.add(d));
      }
    }
  } catch (_) {
    /* render calendar anyway */
  }

  _renderCalendar(month);

  // Restore or clear events panel
  if (_selectedDay !== null && _daysWithData.has(_selectedDay)) {
    _loadDayEvents(_currentMonth, _selectedDay);
  } else {
    _selectedDay = null;
    _clearEventsPanel();
  }
}

// ── Calendar rendering ────────────────────────────────────────────────────

function _renderCalendar(month) {
  const grid = document.querySelector(".tih-calendar-grid");

  // Remove all existing day cells (keep the 7 header cells)
  const headers = Array.from(grid.querySelectorAll(".tih-day-header"));
  grid.innerHTML = "";
  headers.forEach((h) => grid.appendChild(h));

  // First weekday of this month (year is arbitrary — only month matters for layout)
  // Use a fixed leap year (2000) so Feb has 29 days available in data
  const firstDay = new Date(2000, month - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(2000, month, 0).getDate();

  // Leading empty cells
  for (let i = 0; i < firstDay; i++) {
    const blank = document.createElement("div");
    blank.className = "tih-day-cell tih-day-empty";
    grid.appendChild(blank);
  }

  // Day cells
  for (let day = 1; day <= daysInMonth; day++) {
    const cell = document.createElement("div");
    const hasData = _daysWithData.has(day);
    cell.className = "tih-day-cell" + (hasData ? " has-data" : "");
    if (_selectedDay === day) cell.classList.add("selected");

    const numSpan = document.createElement("span");
    numSpan.className = "tih-day-num";
    numSpan.textContent = day;
    cell.appendChild(numSpan);

    if (hasData) {
      const dot = document.createElement("span");
      dot.className = "tih-day-dot";
      cell.appendChild(dot);
    }

    cell.addEventListener("click", () => _onDayClick(day, hasData));
    grid.appendChild(cell);
  }
}

// ── Day click ─────────────────────────────────────────────────────────────

function _onDayClick(day, hasData) {
  _selectedDay = day;

  // Update selected visual state
  document.querySelectorAll(".tih-day-cell.selected").forEach((c) => c.classList.remove("selected"));
  const cells = document.querySelectorAll(".tih-day-cell:not(.tih-day-empty)");
  const cell = cells[day - 1];
  if (cell) cell.classList.add("selected");

  if (hasData) {
    _loadDayEvents(_currentMonth, day);
  } else {
    _showNoDataPanel(day);
  }
}

// ── Events panel ──────────────────────────────────────────────────────────

function _clearEventsPanel() {
  document.getElementById("tih-events-header").textContent = "Select a date to see events";
  document.getElementById("tih-events-list").innerHTML = '<p class="tih-events-empty">&#128197; Pick a day on the calendar to explore historical events.</p>';
}

function _showNoDataPanel(day) {
  const label = `${_MONTH_NAMES[_currentMonth - 1]} ${day}`;
  document.getElementById("tih-events-header").textContent = label;
  document.getElementById("tih-events-list").innerHTML = '<p class="tih-events-empty">No events data for this date.</p>';
}

async function _loadDayEvents(month, day) {
  const label = `${_MONTH_NAMES[month - 1]} ${day}`;
  document.getElementById("tih-events-header").textContent = label;
  const list = document.getElementById("tih-events-list");
  list.innerHTML = '<p class="tih-events-empty tih-loading">Loading&#8230;</p>';

  try {
    const res = await fetch(`/api/history-day?month=${month}&day=${day}`);
    if (!res.ok) throw new Error("fetch failed");
    const data = await res.json();
    _renderEvents(data.events || []);
  } catch (_) {
    list.innerHTML = '<p class="tih-events-empty tih-error">Failed to load events.</p>';
  }
}

function _renderEvents(events) {
  const list = document.getElementById("tih-events-list");
  if (!events.length) {
    list.innerHTML = '<p class="tih-events-empty">No events data for this date.</p>';
    return;
  }

  list.innerHTML = "";
  events.forEach((ev) => {
    const card = document.createElement("div");
    const hasLink = ev.wikipedia && ev.wikipedia.trim() !== "";
    card.className = "tih-event-card" + (hasLink ? " has-link" : "");

    const year = document.createElement("span");
    year.className = "tih-event-year";
    year.textContent = ev.year || "?";

    const text = document.createElement("p");
    text.className = "tih-event-text";
    text.textContent = ev.text || "";

    card.appendChild(year);
    card.appendChild(text);

    if (hasLink) {
      const linkHint = document.createElement("span");
      linkHint.className = "tih-event-link-hint";
      linkHint.textContent = "Open on Wikipedia \u2197";
      card.appendChild(linkHint);

      card.addEventListener("click", () => {
        window.open(ev.wikipedia, "_blank", "noopener,noreferrer");
      });
    }

    list.appendChild(card);
  });
}
