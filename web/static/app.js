'use strict';

let _activeChannel = null;

// ── Nodes ───────────────────────────────────────────────────────────────────

async function fetchNodes() {
    try {
        const res = await fetch('/api/nodes');
        if (!res.ok) return;
        renderNodes(await res.json());
    } catch (_) { /* network error — ignore */ }
}

function renderNodes(nodes) {
    const tbody = document.getElementById('node-tbody');
    if (!nodes.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty">No nodes in database yet.</td></tr>';
        return;
    }
    tbody.innerHTML = nodes.map(n => `
        <tr>
            <td>${esc(n.node_id)}</td>
            <td>${esc(n.long_name)}</td>
            <td>${esc(n.short_name)}</td>
            <td>${esc(fmtDate(n.last_seen))}</td>
            <td>${esc(n.last_update_delta || '\u2014')}</td>
        </tr>
    `).join('');
}

// ── Channel tabs ─────────────────────────────────────────────────────────────

async function fetchChannels() {
    try {
        const res = await fetch('/api/channels');
        if (!res.ok) return;
        const channels = await res.json();
        renderChannelTabs(channels);
        if (channels.length > 0) selectChannel(channels[0]);
    } catch (_) { /* ignore */ }
}

function renderChannelTabs(channels) {
    const bar = document.getElementById('channel-tabs');
    if (!channels.length) {
        bar.innerHTML = '<span class="tab-empty">No channel history found.</span>';
        return;
    }
    bar.innerHTML = channels.map(ch =>
        `<button class="tab-btn" data-ch="${esc(ch)}" onclick="selectChannel(${JSON.stringify(ch)})">${esc(ch)}</button>`
    ).join('');
}

function selectChannel(channel) {
    _activeChannel = channel;
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.ch === channel);
    });
    fetchHistory(channel);
}

// ── History ──────────────────────────────────────────────────────────────────

async function fetchHistory(channel) {
    const box = document.getElementById('chat-messages');
    try {
        const res = await fetch('/api/history/' + encodeURIComponent(channel));
        if (!res.ok) {
            box.innerHTML = '<p class="empty">Failed to load history.</p>';
            return;
        }
        renderMessages(await res.json());
    } catch (_) {
        box.innerHTML = '<p class="empty">Network error.</p>';
    }
}

function renderMessages(messages) {
    const box = document.getElementById('chat-messages');
    if (!messages.length) {
        box.innerHTML = '<p class="empty">No messages recorded for this channel.</p>';
        return;
    }
    box.innerHTML = messages.map(m => `<div class="message">${esc(m)}</div>`).join('');
    box.scrollTop = box.scrollHeight;
}

// ── Refresh ──────────────────────────────────────────────────────────────────

function refreshAll() {
    fetchNodes();
    if (_activeChannel) fetchHistory(_activeChannel);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
    if (!iso) return '\u2014';
    try {
        return new Date(iso).toUTCString().replace(' GMT', ' UTC');
    } catch (_) { return iso; }
}

function esc(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#x27;');
}

// ── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Populate the bot's active channel name in the send form
    fetch('/api/channel')
        .then(r => r.json())
        .then(d => {
            document.getElementById('send-channel-name').textContent = d.name || 'primary';
        })
        .catch(() => {
            document.getElementById('send-channel-name').textContent = '(unavailable)';
        });

    fetchNodes();
    fetchChannels();
    setInterval(refreshAll, 30_000);

    document.getElementById('send-form').addEventListener('submit', async e => {
        e.preventDefault();
        const input = document.getElementById('send-text');
        const text = input.value.trim();
        if (!text) return;

        const btn = document.getElementById('send-btn');
        const status = document.getElementById('send-status');
        btn.disabled = true;
        status.textContent = 'Sending\u2026';
        status.className = '';

        try {
            const res = await fetch('/api/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            if (res.ok) {
                input.value = '';
                status.textContent = '\u2713 Sent!';
                status.className = 'status-ok';
                setTimeout(() => { status.textContent = ''; }, 3000);
                // Refresh active channel after a short delay so message appears
                setTimeout(() => { if (_activeChannel) fetchHistory(_activeChannel); }, 2500);
            } else {
                status.textContent = '\u2717 Send failed.';
                status.className = 'status-err';
            }
        } catch (_) {
            status.textContent = '\u2717 Network error.';
            status.className = 'status-err';
        } finally {
            btn.disabled = false;
        }
    });
});
