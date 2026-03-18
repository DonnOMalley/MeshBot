"use strict";

// ── Collapsible send panel ────────────────────────────────────────────────────
function toggleSendPanel() {
  const header = document.getElementById("send-panel-header");
  const body = document.getElementById("send-panel-body");
  if (!header || !body) return;
  const collapsed = body.classList.toggle("collapsed");
  header.classList.toggle("collapsed", collapsed);
}

// Page init for /chat
document.addEventListener("DOMContentLoaded", async () => {
  fetchChannels();
  setInterval(refreshAll, REFRESH_INTERVAL_MS);

  // ── Web user identity ────────────────────────────────────────────────
  const userDisplay = document.getElementById("web-user-display");
  const editBtn = document.getElementById("web-user-edit-btn");
  const editForm = document.getElementById("web-user-edit-form");
  const longInput = document.getElementById("wu-long-name");
  const shortInput = document.getElementById("wu-short-name");
  const saveBtn = document.getElementById("wu-save-btn");
  const cancelBtn = document.getElementById("wu-cancel-btn");

  let _webUser = null;

  async function loadWebUser() {
    try {
      const res = await fetch("/api/web-user");
      if (res.ok) {
        _webUser = await res.json();
        userDisplay.textContent = _webUser.display_name;
        const hint = document.getElementById("send-panel-user");
        if (hint) hint.textContent = _webUser.display_name;
      }
    } catch (_) {
      /* non-fatal */
    }
  }

  function showEditForm(visible) {
    editBtn.style.display = visible ? "none" : "";
    editForm.style.display = visible ? "" : "none";
  }

  editBtn.addEventListener("click", () => {
    longInput.value = _webUser ? _webUser.long_name : "";
    // strip the leading 'W' since the prefix badge shows it
    const currentShort = _webUser ? _webUser.short_name : "";
    shortInput.value = currentShort.startsWith("W") ? currentShort.slice(1) : currentShort;
    longInput.style.borderColor = "";
    shortInput.style.borderColor = "";
    const wrap = shortInput.closest(".wu-short-wrap");
    if (wrap) wrap.style.borderColor = "";
    showEditForm(true);
    longInput.focus();
  });

  cancelBtn.addEventListener("click", () => {
    showEditForm(false);
  });

  async function doSaveUser() {
    const long = longInput.value.trim();
    const suffix = shortInput.value.trim().toUpperCase();
    const short = "W" + suffix;
    if (!long || !suffix) return;
    saveBtn.disabled = true;
    try {
      const res = await fetch("/api/web-user", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ long_name: long, short_name: short })
      });
      if (res.ok) {
        _webUser = await res.json();
        userDisplay.textContent = _webUser.display_name;
        const hint = document.getElementById("send-panel-user");
        if (hint) hint.textContent = _webUser.display_name;
        showEditForm(false);
      } else {
        longInput.style.borderColor = "var(--error)";
        const wrap = shortInput.closest(".wu-short-wrap");
        if (wrap) wrap.style.borderColor = "var(--error)";
        setTimeout(() => {
          longInput.style.borderColor = "";
          if (wrap) wrap.style.borderColor = "";
        }, 2000);
      }
    } catch (_) {
      /* network error — leave form open */
    } finally {
      saveBtn.disabled = false;
    }
  }

  saveBtn.addEventListener("click", doSaveUser);
  shortInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSaveUser();
  });
  longInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSaveUser();
  });

  loadWebUser();

  // ── Send message ─────────────────────────────────────────────────────
  const input = document.getElementById("send-text");
  const btn = document.getElementById("send-btn");
  const status = document.getElementById("send-status");

  async function doSend() {
    const text = input.value.trim();
    if (!text) return;
    btn.disabled = true;
    status.textContent = "Sending\u2026";
    status.className = "";
    try {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      if (res.ok) {
        input.value = "";
        status.textContent = "\u2713 Sent!";
        status.className = "status-ok";
        setTimeout(() => {
          status.textContent = "";
        }, 3000);
        setTimeout(() => {
          if (_activeChannel) fetchHistory(_activeChannel);
        }, 2500);
      } else {
        status.textContent = "\u2717 Send failed.";
        status.className = "status-err";
      }
    } catch (_) {
      status.textContent = "\u2717 Network error.";
      status.className = "status-err";
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener("click", doSend);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSend();
  });
});
