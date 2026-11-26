// ── Joy page — affirmations, quotes, jokes, and past events with their photos ──

"use strict";

const _JOY_THUMBS = 6; // photo thumbnails shown per past event
const _JOY_EVENTS_REFRESH_MS = 60_000;

document.addEventListener("DOMContentLoaded", () => {
  const label = document.getElementById("refresh-label");
  if (label) label.textContent = "";
  ["affirmation", "quote", "joke"].forEach((kind) => {
    document.getElementById(_JOY_PANELS[kind].button).addEventListener("click", (e) => _joySpin(e.currentTarget, () => _joyLoadRandom(kind)));
  });
  _joyLoadRandom("all");
  _joyLoadPastEvents();
  // Keep the "happening now" banner (and past list) current.
  setInterval(_joyLoadPastEvents, _JOY_EVENTS_REFRESH_MS);
});

// Header "Refresh" button: a new random affirmation, quote and joke, and reload past events.
function refreshAll() {
  _joyLoadRandom("all");
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

// Each panel shows one random item; its 🎲 button swaps in another.
const _JOY_PANELS = {
  affirmation: {
    list: "joy-affirmations-list",
    button: "joy-affirmations-random",
    pick: (data) => data.affirmation,
    key: (a) => a,
    render: (a) => [_joyEl("p", "joy-line", a)],
    empty: "No affirmations yet.",
  },
  quote: {
    list: "joy-quotes-list",
    button: "joy-quotes-random",
    pick: (data) => data.zen_quote,
    key: (q) => q.quote,
    render: (q) => [_joyEl("p", "joy-line joy-quote", `“${q.quote}”`), q.author ? _joyEl("p", "joy-author", `— ${q.author}`) : null],
    empty: "No quotes yet.",
  },
  joke: {
    list: "joy-jokes-list",
    button: "joy-jokes-random",
    pick: (data) => data.joke,
    key: (j) => j,
    render: (j) => [_joyEl("p", "joy-line joy-joke", j)],
    empty: "No jokes yet.",
  },
};
const _JOY_SHOWN = {}; // kind -> key of the item currently on screen
const _JOY_RETRIES = 3; // re-rolls to avoid showing the same item twice in a row

async function _joyFetchRandom() {
  const res = await fetch("/api/joy", { cache: "no-store" });
  if (!res.ok) throw new Error("load failed");
  return res.json();
}

// kind: "all", "affirmation", "quote" or "joke" (only that panel is redrawn).
async function _joyLoadRandom(kind) {
  const kinds = kind === "all" ? Object.keys(_JOY_PANELS) : [kind];
  try {
    let data = await _joyFetchRandom();
    if (kind !== "all") {
      const panel = _JOY_PANELS[kind];
      for (let i = 0; i < _JOY_RETRIES; i++) {
        const item = panel.pick(data);
        if (!item || panel.key(item) !== _JOY_SHOWN[kind]) break;
        data = await _joyFetchRandom();
      }
    }
    kinds.forEach((k) => {
      const panel = _JOY_PANELS[k];
      const item = panel.pick(data);
      _JOY_SHOWN[k] = item ? panel.key(item) : undefined;
      _joyFill(panel.list, item ? [item] : [], panel.render, panel.empty);
    });
  } catch (_) {
    kinds.forEach((k) => {
      const list = document.getElementById(_JOY_PANELS[k].list);
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
    _joyRenderLive(published.filter((e) => e.status === "active"));
    // Finished events, plus repeating events still going that already have photos.
    const past = published.filter((e) => e.status === "past" || (e.recurrence && (e.photos || []).length));
    past.sort((a, b) => _joyLastDate(b) - _joyLastDate(a));
    _joyRenderPast(past);
  } catch (_) {
    box.innerHTML = '<p class="joy-empty">Couldn’t load past events.</p>';
  }
}

// ── "Happening now" banner ──────────────────────────────────────────────────

// One banner per event happening now. With a picture: shown large and whole,
// over a blurred copy of itself; without one: a compact banner.
function _joyRenderLive(events) {
  const box = document.getElementById("joy-live");
  // Don't rebuild (and re-load the big picture) every minute if nothing changed.
  const signature = events.map((e) => `${e.id}:${e.updated_at}:${e.occurrence_end}`).join("|");
  if (box.dataset.signature === signature) return;
  box.dataset.signature = signature;
  box.innerHTML = "";
  box.hidden = !events.length;
  events
    .slice()
    // Events with a picture first (they draw the eye), then whichever ends soonest.
    .sort((a, b) => (b.has_image ? 1 : 0) - (a.has_image ? 1 : 0) || String(a.occurrence_end || a.end).localeCompare(String(b.occurrence_end || b.end)))
    .forEach((e) => box.appendChild(_joyLiveBanner(e)));
}

function _joyLiveBanner(e) {
  const url = `/events?id=${encodeURIComponent(e.id)}`;
  const banner = _joyEl("section", "joy-live-banner" + (e.has_image ? " has-image" : ""));
  banner.setAttribute("aria-label", `Happening now: ${e.name}`);

  if (e.has_image) {
    const src = `/events/${encodeURIComponent(e.id)}/image/cover?v=${encodeURIComponent(e.updated_at || "")}`;
    const backdrop = _joyEl("div", "joy-live-backdrop");
    backdrop.style.backgroundImage = `url("${src}")`;
    banner.appendChild(backdrop);
    const pic = document.createElement("a");
    pic.className = "joy-live-picture";
    pic.href = url;
    const img = document.createElement("img");
    img.src = src;
    img.alt = e.name;
    pic.appendChild(img);
    banner.appendChild(pic);
  }

  const info = _joyEl("div", "joy-live-info");
  info.appendChild(_joyEl("span", "joy-live-badge", "🎉 Happening now"));
  const title = _joyEl("a", "joy-live-title", e.name);
  title.href = url;
  info.appendChild(title);
  const loc = e.location || {};
  const where = loc.type === "online" ? "Online" : loc.address || "";
  info.appendChild(_joyEl("p", "joy-live-meta", [_joyUntil(e), where].filter(Boolean).join(" · ")));
  const actions = _joyEl("div", "joy-live-actions");
  const share = _joyEl("a", "joy-live-btn is-primary", "📸 Share photos");
  share.href = url;
  const details = _joyEl("a", "joy-live-btn", "Details");
  details.href = url;
  actions.appendChild(share);
  actions.appendChild(details);
  info.appendChild(actions);
  banner.appendChild(info);
  return banner;
}

// "Until 9:00 PM", "Until Sat, Dec 6", "All day" or "Through Sun, Dec 6".
function _joyUntil(e) {
  const end = new Date(e.occurrence_end || e.end);
  if (isNaN(end)) return "";
  const today = new Date();
  const sameDay = (d) => d.toDateString() === today.toDateString();
  const dayLabel = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  if (e.all_day) {
    let last;
    if (!e.recurrence && e.end_day) {
      const [y, m, d] = e.end_day.split("-").map(Number);
      last = new Date(y, m - 1, d);
    } else {
      last = new Date(end.getTime() - 1);
    }
    return sameDay(last) ? "All day" : `Through ${dayLabel(last)}`;
  }
  return sameDay(end) ? `Until ${end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` : `Until ${dayLabel(end)}`;
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
