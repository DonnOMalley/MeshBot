// ── Joy page — affirmations, quotes, jokes, and past events with their photos ──

"use strict";

const _JOY_QUOTES = 10;
const _JOY_JOKES = 5;
const _JOY_THUMBS = 6; // photo thumbnails shown per past event

document.addEventListener("DOMContentLoaded", () => {
  const label = document.getElementById("refresh-label");
  if (label) label.textContent = "";
  document.getElementById("joy-quotes-refresh").addEventListener("click", (e) => _joySpin(e.currentTarget, () => _joyLoadLists("quotes")));
  document.getElementById("joy-jokes-refresh").addEventListener("click", (e) => _joySpin(e.currentTarget, () => _joyLoadLists("jokes")));
  _joyLoadLists("all");
  _joyLoadPastEvents();
});

// Header "Refresh" button: new quotes and jokes, and reload past events.
function refreshAll() {
  _joyLoadLists("all");
  _joyLoadPastEvents();
}

// Spins a ↻ button while its load runs; ignores extra clicks meanwhile.
async function _joySpin(btn, load) {
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    await load();
  } finally {
    btn.classList.remove("spinning");
    btn.disabled = false;
  }
}

// ── Affirmations, quotes, jokes ─────────────────────────────────────────────

// which: "all", "quotes" or "jokes" (only that panel is redrawn).
async function _joyLoadLists(which) {
  try {
    const res = await fetch(`/api/joy/lists?quotes=${_JOY_QUOTES}&jokes=${_JOY_JOKES}`, { cache: "no-store" });
    if (!res.ok) throw new Error("load failed");
    const data = await res.json();
    if (which === "all") _joyFill("joy-affirmations-list", data.affirmations || [], (a) => [_joyEl("p", "joy-line", a)], "No affirmations yet.");
    if (which === "all" || which === "quotes")
      _joyFill(
        "joy-quotes-list",
        data.quotes || [],
        (q) => [_joyEl("p", "joy-line joy-quote", `“${q.quote}”`), q.author ? _joyEl("p", "joy-author", `— ${q.author}`) : null],
        "No quotes yet."
      );
    if (which === "all" || which === "jokes") _joyFill("joy-jokes-list", data.jokes || [], (j) => [_joyEl("p", "joy-line joy-joke", j)], "No jokes yet.");
  } catch (_) {
    ["joy-affirmations-list", "joy-quotes-list", "joy-jokes-list"].forEach((id) => {
      const list = document.getElementById(id);
      if (!list.querySelector(".joy-line")) list.innerHTML = '<li class="joy-empty">Couldn’t load.</li>';
    });
  }
}

function _joyFill(listId, items, render, emptyText) {
  const list = document.getElementById(listId);
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(_joyEl("li", "joy-empty", emptyText));
    return;
  }
  items.forEach((item) => {
    const li = document.createElement("li");
    render(item)
      .filter(Boolean)
      .forEach((node) => li.appendChild(node));
    list.appendChild(li);
  });
}

// ── Past events and their photo albums ──────────────────────────────────────

async function _joyLoadPastEvents() {
  const box = document.getElementById("joy-past-list");
  try {
    const res = await fetch("/api/events", { cache: "no-store" });
    if (!res.ok) throw new Error("load failed");
    const data = await res.json();
    const published = (data.events || []).filter((e) => e.approved !== false);
    // Finished events, plus repeating events still going that already have photos.
    const past = published.filter((e) => e.status === "past" || (e.recurrence && (e.photos || []).length));
    past.sort((a, b) => _joyLastDate(b) - _joyLastDate(a));
    _joyRenderPast(past);
  } catch (_) {
    box.innerHTML = '<p class="joy-empty">Couldn’t load past events.</p>';
  }
}

// The date that best represents an event looking back: its (last) date, or
// for a repeating event that's still going, its newest photo.
function _joyLastDate(e) {
  if (e.status === "past") return new Date(e.occurrence_start || e.start);
  const photos = e.photos || [];
  return photos.length ? new Date(photos[photos.length - 1].uploaded_at) : new Date(e.start);
}

function _joyRenderPast(events) {
  const box = document.getElementById("joy-past-list");
  box.innerHTML = "";
  if (!events.length) {
    box.appendChild(_joyEl("p", "joy-empty", "No past events yet. Photos people share during events will show up here."));
    return;
  }
  events.forEach((e) => {
    const photos = (e.photos || []).slice().reverse(); // newest first
    const albumUrl = `/events?id=${encodeURIComponent(e.id)}`;
    const when = _joyLastDate(e).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
    const metaParts = [e.status === "past" ? when : `Ongoing · latest photo ${when}`];
    const loc = e.location || {};
    if (loc.type === "online") metaParts.push("Online");
    else if (loc.address) metaParts.push(loc.address);
    if (e.recurrence) metaParts.push("↻ Repeating");

    const card = _joyEl("article", "joy-past-card");
    const head = _joyEl("div", "joy-past-head");
    const title = _joyEl("a", "joy-past-title", e.name);
    title.href = albumUrl;
    head.appendChild(title);
    head.appendChild(_joyEl("span", "joy-past-count" + (photos.length ? "" : " is-empty"), photos.length ? `📷 ${photos.length} photo${photos.length === 1 ? "" : "s"}` : "No photos"));
    card.appendChild(head);
    card.appendChild(_joyEl("p", "joy-past-meta", metaParts.join(" · ")));

    if (photos.length) {
      const strip = _joyEl("div", "joy-thumbs");
      photos.slice(0, _JOY_THUMBS).forEach((p) => {
        const a = document.createElement("a");
        a.href = albumUrl;
        a.title = (p.uploader ? p.uploader + " · " : "") + new Date(p.uploaded_at).toLocaleString();
        const img = document.createElement("img");
        img.src = `/events/${encodeURIComponent(e.id)}/image/${encodeURIComponent(p.id)}_thumb`;
        img.alt = a.title;
        img.loading = "lazy";
        a.appendChild(img);
        strip.appendChild(a);
      });
      if (photos.length > _JOY_THUMBS) {
        const more = _joyEl("a", "joy-thumbs-more", `+${photos.length - _JOY_THUMBS}`);
        more.href = albumUrl;
        more.title = "See all photos";
        strip.appendChild(more);
      }
      card.appendChild(strip);
      const open = _joyEl("a", "joy-album-link", "Open photo album →");
      open.href = albumUrl;
      card.appendChild(open);
    }
    box.appendChild(card);
  });
}

// ── helpers ─────────────────────────────────────────────────────────────────

// Element with a class and plain-text content (never parsed as HTML).
function _joyEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
