"use strict";

// ── Page-level state ──────────────────────────────────────────────────────────

let _dmWebUser = null;

// ── Collapsible command panel ─────────────────────────────────────────────────

function toggleDmCmdPanel() {
  const header = document.getElementById("dm-cmd-header");
  const body = document.getElementById("dm-cmd-body");
  if (!header || !body) return;
  const collapsed = body.classList.toggle("collapsed");
  header.classList.toggle("collapsed", collapsed);
}

// Override app.js refreshAll — no auto-refresh needed on the DM page.
function refreshAll() {
  /* no-op */
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  await _loadWebUserIntoOnboarding();
  _loadChannelsIntoDatalist();
  _loadNodesIntoTraceDropdown();

  // Onboarding form wiring
  const startBtn = document.getElementById("dm-start-btn");
  const longInput = document.getElementById("dm-long-name");
  const shortInput = document.getElementById("dm-short-name");
  startBtn.addEventListener("click", _doOnboardingSave);
  longInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") _doOnboardingSave();
  });
  shortInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") _doOnboardingSave();
  });

  // Command button wiring
  document.querySelectorAll(".dm-cmd-btn").forEach((btn) => {
    btn.addEventListener("click", () => _handleCommandBtn(btn.dataset.cmd));
  });

  // !last params wiring
  document.getElementById("dm-last-send").addEventListener("click", _sendLastCommand);
  document.getElementById("dm-last-cancel").addEventListener("click", _hideLast);

  // !range params wiring
  document.getElementById("dm-range-send").addEventListener("click", _sendRangeCommand);
  document.getElementById("dm-range-cancel").addEventListener("click", _hideRange);

  // !trace params wiring
  document.getElementById("dm-trace-send").addEventListener("click", _sendTraceCommand);
  document.getElementById("dm-trace-cancel").addEventListener("click", _hideTrace);

  // DM input wiring
  const sendBtn = document.getElementById("dm-send-btn");
  const textInput = document.getElementById("dm-text-input");
  sendBtn.addEventListener("click", _doSendDm);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") _doSendDm();
  });

  // In-interface identity edit
  _setupInlineEditForm();
});

// ── Onboarding ────────────────────────────────────────────────────────────────

async function _loadWebUserIntoOnboarding() {
  try {
    const res = await fetch("/api/web-user");
    if (res.ok) {
      _dmWebUser = await res.json();
      document.getElementById("dm-long-name").value = _dmWebUser.long_name;
      const s = _dmWebUser.short_name;
      document.getElementById("dm-short-name").value = s.startsWith("W") ? s.slice(1) : s;
    }
  } catch (_) {
    /* non-fatal — leave fields blank */
  }
}

async function _doOnboardingSave() {
  const longName = document.getElementById("dm-long-name").value.trim();
  const suffix = document.getElementById("dm-short-name").value.trim().toUpperCase();
  const shortName = "W" + suffix;
  const errEl = document.getElementById("dm-onboarding-error");

  errEl.textContent = "";

  if (!longName) {
    errEl.textContent = "Long name is required.";
    return;
  }
  if (!suffix || suffix.length > 3 || !/^[A-Z0-9]+$/.test(suffix)) {
    errEl.textContent = "Short suffix must be 1\u20133 alphanumeric characters (W is added automatically).";
    return;
  }

  const startBtn = document.getElementById("dm-start-btn");
  startBtn.disabled = true;

  try {
    const res = await fetch("/api/web-user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ long_name: longName, short_name: shortName })
    });
    if (res.ok) {
      _dmWebUser = await res.json();
      _showDmInterface();
    } else {
      const data = await res.json().catch(() => ({}));
      const fields = data.fields || {};
      const msgs = Object.values(fields);
      errEl.textContent = msgs.length ? msgs.join(" ") : "Could not save identity. Please check inputs.";
    }
  } catch (_) {
    errEl.textContent = "Network error. Please try again.";
  } finally {
    startBtn.disabled = false;
  }
}

function _showDmInterface() {
  document.getElementById("dm-onboarding").style.display = "none";
  document.getElementById("dm-interface").style.display = "";
  _updateCurrentUserLabel();
  document.getElementById("dm-text-input").focus();
}

function _updateCurrentUserLabel() {
  const el = document.getElementById("dm-current-user");
  if (el && _dmWebUser) el.textContent = _dmWebUser.display_name;
}

// ── Inline identity edit (inside the DM interface) ───────────────────────────

function _setupInlineEditForm() {
  const editBtn = document.getElementById("dm-change-user-btn");
  const editForm = document.getElementById("dm-edit-form");
  const longInput = document.getElementById("dm-edit-long");
  const shortInput = document.getElementById("dm-edit-short");
  const saveBtn = document.getElementById("dm-edit-save");
  const cancelBtn = document.getElementById("dm-edit-cancel");

  editBtn.addEventListener("click", () => {
    if (_dmWebUser) {
      longInput.value = _dmWebUser.long_name;
      const s = _dmWebUser.short_name;
      shortInput.value = s.startsWith("W") ? s.slice(1) : s;
    }
    editBtn.style.display = "none";
    editForm.style.display = "";
    longInput.focus();
  });

  cancelBtn.addEventListener("click", () => {
    editForm.style.display = "none";
    editBtn.style.display = "";
  });

  async function doSave() {
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
        _dmWebUser = await res.json();
        _updateCurrentUserLabel();
        editForm.style.display = "none";
        editBtn.style.display = "";
      }
    } catch (_) {
      /* leave form open */
    } finally {
      saveBtn.disabled = false;
    }
  }

  saveBtn.addEventListener("click", doSave);
  shortInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSave();
  });
  longInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSave();
  });
}

// ── Channel datalist ──────────────────────────────────────────────────────────

async function _loadChannelsIntoDatalist() {
  try {
    const res = await fetch("/api/channels");
    if (!res.ok) return;
    const channels = await res.json();
    const dl = document.getElementById("dm-channel-datalist");
    if (dl) {
      dl.innerHTML = channels.map((ch) => `<option value="${esc(ch)}">`).join("");
    }
    const input = document.getElementById("dm-last-channel");
    if (input && !input.value && channels.length > 0) {
      input.value = channels[0];
    }
  } catch (_) {
    /* non-fatal */
  }
}

// ── Command buttons ───────────────────────────────────────────────────────────

function _handleCommandBtn(cmd) {
  if (cmd === "last") {
    _toggleLastParams();
    return;
  }
  if (cmd === "range") {
    _toggleRangeParams();
    return;
  }
  if (cmd === "trace") {
    _toggleTraceParams();
    return;
  }
  const btn = document.querySelector(`.dm-cmd-btn[data-cmd="${cmd}"]`);
  const label = btn ? btn.querySelector(".dm-cmd-label").textContent.trim() : cmd;
  const desc = btn ? btn.querySelector(".dm-cmd-desc").textContent.trim() : "";
  const displayText = desc ? `${desc} (!${cmd})` : `Sending ${label} (!${cmd})`;
  _sendDmText("!" + cmd, displayText);
}

function _toggleLastParams() {
  const params = document.getElementById("dm-last-params");
  const btn = document.querySelector('.dm-cmd-btn[data-cmd="last"]');
  const visible = params.style.display !== "none";
  params.style.display = visible ? "none" : "";
  if (btn) btn.classList.toggle("dm-cmd-btn--active", !visible);
  if (!visible) {
    document.getElementById("dm-last-channel").focus();
  }
}

function _hideLast() {
  const params = document.getElementById("dm-last-params");
  const btn = document.querySelector('.dm-cmd-btn[data-cmd="last"]');
  params.style.display = "none";
  if (btn) btn.classList.remove("dm-cmd-btn--active");
}
function _toggleRangeParams() {
  const params = document.getElementById("dm-range-params");
  const btn = document.querySelector('.dm-cmd-btn[data-cmd="range"]');
  const visible = params.style.display !== "none";
  _hideLast();
  params.style.display = visible ? "none" : "";
  if (btn) btn.classList.toggle("dm-cmd-btn--active", !visible);
  if (!visible) {
    document.getElementById("dm-range-requests").focus();
  }
}

function _hideRange() {
  const params = document.getElementById("dm-range-params");
  const btn = document.querySelector('.dm-cmd-btn[data-cmd="range"]');
  params.style.display = "none";
  if (btn) btn.classList.remove("dm-cmd-btn--active");
}

function _sendRangeCommand() {
  const reqVal = parseInt(document.getElementById("dm-range-requests").value, 10);
  const delayVal = parseInt(document.getElementById("dm-range-delay").value, 10);
  const requests = Number.isFinite(reqVal) && reqVal >= 1 && reqVal <= 10 ? reqVal : 5;
  const delay = Number.isFinite(delayVal) && delayVal >= 1 && delayVal <= 10 ? delayVal : 1;
  _hideRange();
  const cmdText = `!range ${requests} ${delay}`;
  _sendDmText(cmdText, `Range Test (!range ${requests} msg, ${delay} min apart)`);
}
function _sendLastCommand() {
  const countVal = parseInt(document.getElementById("dm-last-count").value, 10);
  const count = Number.isFinite(countVal) && countVal > 0 ? countVal : 5;
  const channelInp = document.getElementById("dm-last-channel");
  const channel = channelInp.value.trim();

  if (!channel) {
    channelInp.style.borderColor = "var(--error)";
    setTimeout(() => {
      channelInp.style.borderColor = "";
    }, 2000);
    return;
  }

  _hideLast();
  const cmdText = `!last ${count} ${channel}`;
  _sendDmText(cmdText, `Recent Messages (!last ${count} ${channel})`);
}

// ── DM send ───────────────────────────────────────────────────────────────────

async function _doSendDm() {
  const input = document.getElementById("dm-text-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  await _sendDmText(text, `DM Message Sent: ${text}`);
}

async function _sendDmText(text, displayText) {
  _setInputEnabled(false);
  _appendUserMessage(displayText !== undefined ? displayText : text);
  const pendingEl = _appendBotPending();

  try {
    const res = await fetch("/api/dm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    if (res.ok) {
      const data = await res.json();
      _resolvePending(pendingEl, data.response || null);
    } else {
      _resolvePending(pendingEl, null, true);
    }
  } catch (_) {
    _resolvePending(pendingEl, null, true);
  } finally {
    _setInputEnabled(true);
  }
}

function _setInputEnabled(enabled) {
  const inputEl = document.getElementById("dm-text-input");
  const sendBtn = document.getElementById("dm-send-btn");
  const cmdBtns = document.querySelectorAll(".dm-cmd-btn");
  inputEl.disabled = !enabled;
  sendBtn.disabled = !enabled;
  cmdBtns.forEach((b) => {
    b.disabled = !enabled;
  });
}

// ── Chat window rendering ─────────────────────────────────────────────────────

function _appendUserMessage(text) {
  const box = _getChatBox();
  const timeStr = _nowTimeStr();
  const who = _dmWebUser ? esc(_dmWebUser.display_name) : "You";
  const div = document.createElement("div");
  div.className = "dm-message dm-message--user";
  div.innerHTML = `
        <div class="dm-msg-meta">
            <span class="dm-msg-sender">${who}</span>
            <span class="dm-msg-time">${timeStr}</span>
        </div>
        <div class="dm-msg-body">${esc(text)}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function _appendBotPending() {
  const box = _getChatBox();
  const div = document.createElement("div");
  div.className = "dm-message dm-message--bot dm-message--pending";
  div.innerHTML = `
        <div class="dm-msg-meta">
            <span class="dm-msg-sender dm-msg-sender--bot">BOT</span>
            <span class="dm-msg-time">${_nowTimeStr()}</span>
        </div>
        <div class="dm-msg-body"><span class="dm-typing-dots"><span></span><span></span><span></span></span></div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

function _resolvePending(el, response, failed, isHtml) {
  el.classList.remove("dm-message--pending");
  const body = el.querySelector(".dm-msg-body");
  if (!body) return;
  if (failed) {
    el.classList.add("dm-message--error");
    body.innerHTML = '<span class="dm-msg-error">&#9888;&nbsp;Failed to reach the bot. Please try again.</span>';
  } else if (response === null) {
    el.classList.add("dm-message--pending-static");
    body.innerHTML = '<span class="dm-msg-pending-note">Sent. Waiting for bot response&hellip;</span>';
  } else {
    body.innerHTML = isHtml ? response : esc(response);
  }
  const box = document.getElementById("dm-chat-window");
  if (box) box.scrollTop = box.scrollHeight;
}

function _getChatBox() {
  const box = document.getElementById("dm-chat-window");
  const empty = box.querySelector(".dm-empty-hint");
  if (empty) empty.remove();
  return box;
}

function _nowTimeStr() {
  return new Date().toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

// ── Trace params panel ────────────────────────────────────────────────────────

let _traceNodes = [];

function _traceNodeLabel(node) {
  return `${node.long_name} (${node.short_name}) - ${node.node_id}`;
}

async function _loadNodesIntoTraceDropdown() {
  try {
    const res = await fetch("/api/nodes");
    if (!res.ok) return;
    _traceNodes = await res.json();
    const dl = document.getElementById("dm-trace-datalist");
    if (dl) {
      dl.innerHTML = _traceNodes.map((n) => `<option value="${esc(_traceNodeLabel(n))}">`).join("");
    }
  } catch (_) {
    /* non-fatal */
  }
}

function _toggleTraceParams() {
  const params = document.getElementById("dm-trace-params");
  const btn = document.querySelector('.dm-cmd-btn[data-cmd="trace"]');
  const visible = params.style.display !== "none";
  params.style.display = visible ? "none" : "";
  if (btn) btn.classList.toggle("dm-cmd-btn--active", !visible);
  if (!visible) {
    document.getElementById("dm-trace-node").focus();
  }
}

function _hideTrace() {
  const params = document.getElementById("dm-trace-params");
  const btn = document.querySelector('.dm-cmd-btn[data-cmd="trace"]');
  params.style.display = "none";
  if (btn) btn.classList.remove("dm-cmd-btn--active");
}

async function _sendTraceCommand() {
  const input = document.getElementById("dm-trace-node");
  const label = input.value.trim();
  const node = _traceNodes.find((n) => _traceNodeLabel(n) === label);
  if (!node) {
    input.style.borderColor = "var(--error)";
    setTimeout(() => {
      input.style.borderColor = "";
    }, 2000);
    return;
  }
  _hideTrace();

  const displayText = `Traceroute to ${node.long_name} (${node.short_name}) (!trace)`;
  _setInputEnabled(false);
  _appendUserMessage(displayText);
  const pendingEl = _appendBotPending();

  try {
    const res = await fetch("/api/trace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: node.node_id })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const initial = await res.json();
    if (initial.status !== "pending") {
      _resolvePending(pendingEl, _formatTraceResult(initial), initial.status !== "ok", true);
      _setInputEnabled(true);
      return;
    }
  } catch (_) {
    _resolvePending(pendingEl, null, true);
    _setInputEnabled(true);
    return;
  }

  const POLL_INTERVAL_MS = 1500;
  const TIMEOUT_MS = 90_000;
  const deadline = Date.now() + TIMEOUT_MS;

  const poll = async () => {
    if (Date.now() > deadline) {
      _resolvePending(pendingEl, null, true);
      _setInputEnabled(true);
      return;
    }
    try {
      const res = await fetch(`/api/trace/${encodeURIComponent(node.node_id)}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (data.status === "pending") {
        setTimeout(poll, POLL_INTERVAL_MS);
      } else {
        _resolvePending(pendingEl, _formatTraceResult(data), data.status !== "ok", true);
        _setInputEnabled(true);
      }
    } catch (_) {
      _resolvePending(pendingEl, null, true);
      _setInputEnabled(true);
    }
  };
  setTimeout(poll, POLL_INTERVAL_MS);
}

function _formatTraceResult(data) {
  if (data.status !== "ok") {
    return `<span class="dm-msg-error">&#9888;&nbsp;Trace failed: ${esc(data.message || "Unknown error")}</span>`;
  }
  const lines = [];
  lines.push(`<strong>Traceroute</strong> &mdash; ${esc(data.node_id)} &mdash; ${data.elapsed}s`);
  if (data.direct) {
    lines.push("Direct connection &mdash; no relays");
  } else {
    if (data.route && data.route.length) {
      lines.push(`&#8594;&nbsp;Route: ${data.route.map(esc).join(" &#8594; ")}`);
    }
    if (data.route_back && data.route_back.length) {
      lines.push(`&#8592;&nbsp;Route: ${data.route_back.map(esc).join(" &#8592; ")}`);
    }
    lines.push(`Relays: ${data.relay_count}`);
  }
  if (data.snr_towards && data.snr_towards.length) {
    lines.push(`SNR &#8594;: ${data.snr_towards.map((v) => v.toFixed(1)).join(", ")} dB`);
  }
  if (data.snr_back && data.snr_back.length) {
    lines.push(`SNR &#8592;: ${data.snr_back.map((v) => v.toFixed(1)).join(", ")} dB`);
  }
  return lines.join("<br>");
}
