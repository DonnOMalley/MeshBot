"use strict";

(function () {
  const POLL_MS = 2000;
  const MAX_DOM_LINES = 500;

  const output = document.getElementById("terminal-output");

  let seq = -1;
  let autoScroll = true;

  // Track whether the user has scrolled away from the bottom
  output.addEventListener("scroll", () => {
    const nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
    autoScroll = nearBottom;
  });

  function esc(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function appendLines(lines) {
    if (!lines.length) return;
    const frag = document.createDocumentFragment();
    for (const raw of lines) {
      const div = document.createElement("div");
      div.className = "terminal-line";
      div.innerHTML = esc(raw) || "&nbsp;";
      frag.appendChild(div);
    }
    output.appendChild(frag);

    // Trim old lines from the top to cap DOM size
    const all = output.querySelectorAll(".terminal-line");
    const excess = all.length - MAX_DOM_LINES;
    if (excess > 0) {
      for (let i = 0; i < excess; i++) {
        output.removeChild(all[i]);
      }
    }

    if (autoScroll) {
      output.scrollTop = output.scrollHeight;
    }
  }

  let failCount = 0;

  async function poll() {
    try {
      const url = "/api/console?after=" + seq;
      const res = await fetch(url);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      failCount = 0;
      if (data.lines && data.lines.length > 0) {
        appendLines(data.lines);
      }
      seq = data.seq;
    } catch (_) {
      failCount++;
    }
  }

  // Initial load then periodic polling
  poll();
  setInterval(poll, POLL_MS);
})();
