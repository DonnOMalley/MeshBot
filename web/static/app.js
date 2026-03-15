'use strict';

// ── Shared state ─────────────────────────────────────────────────────────────

let _activeChannel = null;
let _lastNodes = [];
let _favorites = new Set();
let _sortCol = 'last_seen';
let _sortAsc = false;
let _nodeFilter = '';

// ── Trace state ───────────────────────────────────────────────────────────────
// Keyed by node_id: { status: 'pending'|'ok'|'timeout'|'error', data: {...}|null }

const _nodeTraces = new Map();
// Client-side abort guard: slightly longer than _WEB_TRACE_TIMEOUT_SECONDS (30s) on the server
const _TRACE_FETCH_TIMEOUT_MS = 35000;

// ── Nodes ─────────────────────────────────────────────────────────────────────

async function fetchNodes() {
    try {
        const res = await fetch('/api/nodes');
        if (!res.ok) return;
        renderNodes(await res.json());
    } catch (_) { /* network error — ignore */ }
}

function renderNodes(nodes) {
    _lastNodes = nodes;
    const filter = _nodeFilter.toLowerCase().trim();
    const filtered = filter ? nodes.filter(n => _matchesNodeFilter(n, filter)) : nodes;
    const sorted = sortAndGroup(filtered);
    const tbody = document.getElementById('node-tbody');
    const known = nodes.filter(n => n.long_name || n.short_name).length;
    const header = document.getElementById('node-panel-header');
    if (header) {
        const label = header.querySelector('.panel-header-text') || header;
        label.textContent = filter
            ? `Node List \u2014 ${filtered.length} of ${nodes.length} shown`
            : `Node List \u2014 ${nodes.length} total, ${known} known`;
    }
    if (!sorted.length) {
        tbody.innerHTML = filter
            ? '<tr><td colspan="7" class="empty">No nodes match the filter.</td></tr>'
            : '<tr><td colspan="7" class="empty">No nodes in database yet.</td></tr>';
        return;
    }
    tbody.innerHTML = sorted.map(n => {
        const isFav = _favorites.has(n.node_id);
        const star = isFav ? '\u2605' : '\u2606';
        const name = n.long_name
            ? (n.short_name ? `${esc(n.long_name)} (${esc(n.short_name)})` : esc(n.long_name))
            : (n.short_name ? esc(n.short_name) : '\u2014');
        const posCell = (n.latitude != null && n.longitude != null)
            ? `<a href="https://maps.google.com/?q=${n.latitude},${n.longitude}" target="_blank" rel="noopener noreferrer" title="${n.latitude.toFixed(5)}, ${n.longitude.toFixed(5)}" style="font-size:16px;text-decoration:none;">&#128205;</a>`
            : '\u2014';
        const traceState = _nodeTraces.get(n.node_id);
        let traceCell;
        if (!traceState) {
            traceCell = `<div class="trace-cell"><button class="trace-btn" onclick="requestTrace(this.closest('tr').title)">Trace</button></div>`;
        } else if (traceState.status === 'pending') {
            traceCell = '<div class="trace-cell"><span class="trace-spinner" title="Tracing\u2026"></span></div>';
        } else if (traceState.status === 'ok') {
            traceCell = `<div class="trace-cell"><div class="trace-result trace-ok"><span class="trace-icon">&#128225;</span><div class="trace-card">${buildTraceCard(traceState.data)}</div></div><button class="trace-btn trace-btn-refresh" onclick="requestTrace(this.closest('tr').title)" title="Refresh trace">&#8635;</button></div>`;
        } else {
            const errMsg = traceState.data && traceState.data.message
                ? esc(traceState.data.message)
                : 'Last trace failed to get a response.';
            traceCell = `<div class="trace-cell"><div class="trace-result trace-error"><span class="trace-icon">&#9888;</span><div class="trace-card"><p class="trace-card-err">${errMsg}</p></div></div><button class="trace-btn trace-btn-refresh" onclick="requestTrace(this.closest('tr').title)" title="Retry trace">&#8635;</button></div>`;
        }
        return `
        <tr title="${esc(n.node_id)}">
            <td class="fav-cell"><button class="fav-btn${isFav ? ' fav-active' : ''}" onclick="toggleFavorite(this.closest('tr').title, event)">${star}</button></td>
            <td>${name}</td>
            <td>${esc(n.role || '\u2014')}</td>
            <td>${esc(n.hardware_model || '\u2014')}</td>
            <td>${esc(fmtDate(n.last_seen))}${n.hops_away != null ? ` (${n.hops_away} ${n.hops_away === 1 ? 'hop' : 'hops'})` : ''}</td>
            <td style="text-align:center">${posCell}</td>
            <td>${traceCell}</td>
        </tr>`;
    }).join('');
}

function buildTraceCard(data) {
    const rows = [];
    if (data.direct) {
        rows.push('<div class="trace-card-row"><span class="trace-v">Direct connect \u2014 no relays</span></div>');
    } else {
        if (data.route && data.route.length)
            rows.push(`<div class="trace-card-row"><span class="trace-k">&#8594;&nbsp;Route</span><span class="trace-v">${data.route.map(esc).join(' &#8594; ')}</span></div>`);
        if (data.route_back && data.route_back.length)
            rows.push(`<div class="trace-card-row"><span class="trace-k">&#8592;&nbsp;Route</span><span class="trace-v">${data.route_back.map(esc).join(' &#8592; ')}</span></div>`);
        rows.push(`<div class="trace-card-row"><span class="trace-k">Relays</span><span class="trace-v">${data.relay_count}</span></div>`);
    }
    if (data.snr_towards && data.snr_towards.length)
        rows.push(`<div class="trace-card-row"><span class="trace-k">SNR&nbsp;&#8594;</span><span class="trace-v">${data.snr_towards.map(v => v.toFixed(1)).join(', ')}&nbsp;dB</span></div>`);
    if (data.snr_back && data.snr_back.length)
        rows.push(`<div class="trace-card-row"><span class="trace-k">SNR&nbsp;&#8592;</span><span class="trace-v">${data.snr_back.map(v => v.toFixed(1)).join(', ')}&nbsp;dB</span></div>`);
    rows.push(`<div class="trace-card-row"><span class="trace-k">Time</span><span class="trace-v">${data.elapsed}s</span></div>`);
    return rows.join('');
}

// ── Trace popup ──────────────────────────────────────────────────────────────

function _setupTracePopup() {
    const popup = document.getElementById('trace-popup');
    if (!popup) return;
    const tbody = document.getElementById('node-tbody');
    if (!tbody) return;

    tbody.addEventListener('mouseover', e => {
        const result = e.target.closest('.trace-result');
        if (!result) return;
        const card = result.querySelector('.trace-card');
        if (!card) return;
        popup.innerHTML = card.innerHTML;
        popup.style.visibility = 'hidden';
        popup.style.display = 'block';
        const rect = result.getBoundingClientRect();
        const pw = popup.offsetWidth;
        const ph = popup.offsetHeight;
        const left = rect.left - pw - 8;
        const top = rect.top + rect.height / 2 - ph / 2;
        popup.style.left = Math.max(4, left) + 'px';
        popup.style.top = Math.max(4, Math.min(window.innerHeight - ph - 4, top)) + 'px';
        popup.style.visibility = '';
    });

    tbody.addEventListener('mouseout', e => {
        const result = e.target.closest('.trace-result');
        if (!result) return;
        if (!result.contains(e.relatedTarget)) {
            popup.style.display = 'none';
        }
    });
}

// ── Node filter ───────────────────────────────────────────────────────────────

function _matchesNodeFilter(n, filter) {
    return (n.long_name || '').toLowerCase().includes(filter)
        || (n.short_name || '').toLowerCase().includes(filter)
        || (n.hardware_model || '').toLowerCase().includes(filter);
}

function applyNodeFilter(value) {
    _nodeFilter = value;
    renderNodes(_lastNodes);
    updateSortIndicators();
}

// ── Export ────────────────────────────────────────────────────────────────────

function exportNodesCsv() {
    const filter = _nodeFilter.toLowerCase().trim();
    const rows = filter ? _lastNodes.filter(n => _matchesNodeFilter(n, filter)) : _lastNodes;
    const headers = ['Node ID', 'Long Name', 'Short Name', 'Role', 'Device', 'Last Seen', 'Latitude', 'Longitude'];
    const csvRows = [
        headers.join(','),
        ...rows.map(n => [
            n.node_id,
            n.long_name || '',
            n.short_name || '',
            n.role || '',
            n.hardware_model || '',
            n.last_seen ? new Date(n.last_seen).toLocaleString() : '',
            n.latitude != null ? n.latitude : '',
            n.longitude != null ? n.longitude : '',
        ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')),
    ];
    const blob = new Blob([csvRows.join('\r\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'nodes.csv';
    a.click();
    URL.revokeObjectURL(url);
}

// ── Trace ─────────────────────────────────────────────────────────────────────

function _showTraceSpinner(nodeId) {
    const tbody = document.getElementById('node-tbody');
    if (!tbody) return;
    for (const row of tbody.querySelectorAll('tr')) {
        if (row.title === nodeId) {
            const cells = row.cells;
            if (cells.length > 0) {
                cells[cells.length - 1].innerHTML =
                    '<div class="trace-cell"><span class="trace-spinner" title="Tracing\u2026"></span></div>';
            }
            break;
        }
    }
}

async function requestTrace(nodeId) {
    _nodeTraces.set(nodeId, { status: 'pending', data: null });
    _showTraceSpinner(nodeId);
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), _TRACE_FETCH_TIMEOUT_MS);
    try {
        const res = await fetch('/api/trace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ node_id: nodeId }),
            signal: controller.signal,
        });
        clearTimeout(abortTimer);
        const data = await res.json();
        _nodeTraces.set(nodeId, { status: data.status, data });
    } catch (_) {
        clearTimeout(abortTimer);
        _nodeTraces.set(nodeId, { status: 'timeout', data: null });
    }
    renderNodes(_lastNodes);
    updateSortIndicators();
}

function sortAndGroup(nodes) {
    const favs = nodes.filter(n => _favorites.has(n.node_id));
    const rest = nodes.filter(n => !_favorites.has(n.node_id));
    const cmp = makeComparator();
    return [...favs.sort(cmp), ...rest.sort(cmp)];
}

function makeComparator() {
    return (a, b) => {
        let va, vb;
        if (_sortCol === 'long_name') {
            va = (a.long_name || a.short_name || '').toLowerCase();
            vb = (b.long_name || b.short_name || '').toLowerCase();
        } else {
            va = a.last_seen || '';
            vb = b.last_seen || '';
        }
        const cmp = va < vb ? -1 : va > vb ? 1 : 0;
        return _sortAsc ? cmp : -cmp;
    };
}

function handleSort(col) {
    if (_sortCol === col) {
        _sortAsc = !_sortAsc;
    } else {
        _sortCol = col;
        _sortAsc = true;
    }
    renderNodes(_lastNodes);
    updateSortIndicators();
}

function updateSortIndicators() {
    document.querySelectorAll('#node-table th[data-col]').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.col === _sortCol) {
            th.classList.add(_sortAsc ? 'sort-asc' : 'sort-desc');
        }
    });
}

// ── Collapsible node panel (dashboard only) ───────────────────────────────────

function toggleNodePanel() {
    const header = document.getElementById('node-panel-header');
    const body   = document.getElementById('node-panel-body');
    if (!header || !body) return;
    const collapsed = body.classList.toggle('collapsed');
    header.classList.toggle('collapsed', collapsed);
}

// ── Favourites ────────────────────────────────────────────────────────────────

async function fetchFavorites() {
    try {
        const res = await fetch('/api/favorites');
        if (res.ok) {
            _favorites = new Set(await res.json());
        }
    } catch (_) { /* ignore */ }
}

async function toggleFavorite(nodeId, event) {
    event.stopPropagation();
    try {
        const res = await fetch('/api/favorites', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ node_id: nodeId }),
        });
        if (res.ok) {
            _favorites = new Set(await res.json());
            renderNodes(_lastNodes);
            updateSortIndicators();
        }
    } catch (_) { /* ignore */ }
}

// ── Channel tabs ──────────────────────────────────────────────────────────────

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
        `<button class="tab-btn" data-ch="${esc(ch)}" onclick="selectChannel(this.dataset.ch)">${esc(ch)}</button>`
    ).join('');
}

function selectChannel(channel) {
    _activeChannel = channel;
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.ch === channel);
    });
    fetchHistory(channel);
}

// ── History ───────────────────────────────────────────────────────────────────

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

    // messages arrive newest-first from the API; reverse to chronological order
    const chrono = [...messages].reverse();

    // _CHAT_HISTORY_LINE_FORMAT: "[YYYY-MM-DD HH:MM:SS UTC] sender: text"
    const lineRe = /^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) UTC\] (.*)$/;

    let html = '';
    let lastDate = '';

    for (const raw of chrono) {
        const m = lineRe.exec(raw);
        if (m) {
            const [, datePart, timePart, rest] = m;
            // Convert UTC time to local
            const localDate = new Date(`${datePart}T${timePart}Z`);
            const localDateStr = localDate.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
            const localTimeStr = localDate.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });

            if (localDateStr !== lastDate) {
                html += `<div class="msg-date-sep">${esc(localDateStr)}</div>`;
                lastDate = localDateStr;
            }
            html += `<div class="message"><span class="msg-time">${esc(localTimeStr)}</span> ${esc(rest)}</div>`;
        } else {
            // fallback for lines that don't match the expected format
            html += `<div class="message">${esc(raw)}</div>`;
        }
    }

    box.innerHTML = html;
    box.scrollTop = box.scrollHeight;
}

// ── Refresh ───────────────────────────────────────────────────────────────────

function refreshAll() {
    if (document.getElementById('node-tbody')) fetchNodes();
    if (_activeChannel) fetchHistory(_activeChannel);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso) {
    if (!iso) return '\u2014';
    try {
        return new Date(iso).toLocaleString();
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
