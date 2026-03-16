'use strict';

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    setInterval(refreshAll, 30_000);
});

// Override app.js refreshAll for this page.
function refreshAll() { loadSettings(); }

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.error) {
            showSettingsError(data.error);
            return;
        }
        renderLora(data.lora || {});
        renderDevice(data.device || {});
        renderUser(data.user || {});
        renderChannels(data.channels || [], data.monitored_channel || '');
    } catch (e) {
        showSettingsError(e.message || 'Failed to load settings.');
    }
}

function showSettingsError(msg) {
    document.querySelectorAll('.settings-loading').forEach(el => {
        el.textContent = '\u26A0 ' + msg;
        el.style.color = 'var(--error)';
    });
}

function settingsRow(key, val) {
    const display = (val === null || val === undefined || val === '') ? '\u2014' : String(val);
    return `<div class="settings-row"><span class="setting-key">${esc(key)}</span><span class="setting-val">${esc(display)}</span></div>`;
}

function formatEnumName(s) {
    if (!s) return '\u2014';
    return String(s).replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function renderLora(lora) {
    const body = document.getElementById('settings-lora-body');
    if (!body) return;
    const rows = [
        ['Region', formatEnumName(lora.region)],
        ['Use Preset', lora.use_preset ? 'Yes' : 'No'],
    ];
    if (lora.use_preset) {
        rows.push(['Modem Preset', formatEnumName(lora.modem_preset)]);
    } else {
        rows.push(['Bandwidth (kHz)', lora.bandwidth || '\u2014']);
        rows.push(['Spread Factor', lora.spread_factor || '\u2014']);
        rows.push(['Coding Rate', lora.coding_rate || '\u2014']);
    }
    if (lora.override_frequency) {
        rows.push(['Override Frequency (MHz)', Number(lora.override_frequency).toFixed(3)]);
    }
    if (lora.frequency_offset) {
        rows.push(['Frequency Offset (Hz)', lora.frequency_offset]);
    }
    rows.push(
        ['Hop Limit', lora.hop_limit ?? '\u2014'],
        ['TX Enabled', lora.tx_enabled ? 'Yes' : 'No'],
        ['TX Power (dBm)', lora.tx_power || '\u2014'],
        ['Channel Number', lora.channel_num || '\u2014'],
        ['Ignore MQTT', lora.ignore_mqtt ? 'Yes' : 'No'],
        ['Config OK to MQTT', lora.config_ok_to_mqtt ? 'Yes' : 'No'],
    );
    body.innerHTML = rows.map(([k, v]) => settingsRow(k, v)).join('');
}

function renderDevice(device) {
    const body = document.getElementById('settings-device-body');
    if (!body) return;
    const rows = [
        ['Role', formatEnumName(device.role)],
        ['Serial Enabled', device.serial_enabled ? 'Yes' : 'No'],
        ['Rebroadcast Mode', formatEnumName(device.rebroadcast_mode)],
        ['Node Info Broadcast', formatBroadcastInterval(device.node_info_broadcast_secs)],
        ['Double Tap as Button', device.double_tap_as_button_press ? 'Yes' : 'No'],
        ['Is Managed', device.is_managed ? 'Yes' : 'No'],
        ['Timezone', device.tzdef || '\u2014'],
        ['LED Heartbeat Disabled', device.led_heartbeat_disabled ? 'Yes' : 'No'],
    ];
    body.innerHTML = rows.map(([k, v]) => settingsRow(k, v)).join('');
}

function formatBroadcastInterval(secs) {
    if (secs === null || secs === undefined || secs === '') return '\u2014';
    const hrs = secs / 3600;
    const display = Number.isInteger(hrs) ? hrs : hrs.toFixed(2).replace(/\.?0+$/, '');
    return `${display} hr${hrs === 1 ? '' : 's'}`;
}

function renderUser(user) {
    const body = document.getElementById('settings-user-body');
    if (!body) return;
    const rows = [
        ['Node ID', user.node_id || '\u2014'],
        ['Long Name', user.long_name || '\u2014'],
        ['Short Name', user.short_name || '\u2014'],
        ['Hardware Model', formatEnumName(user.hw_model)],
        ['Licensed HAM', user.is_licensed ? 'Yes' : 'No'],
        ['Role', formatEnumName(user.role)],
    ];
    body.innerHTML = rows.map(([k, v]) => settingsRow(k, v)).join('');
}

function renderChannels(channels, monitoredChannel) {
    const body = document.getElementById('settings-channels-body');
    if (!body) return;
    if (!channels.length) {
        body.innerHTML = '<p class="empty" style="padding:14px">No channels found.</p>';
        return;
    }
    const monLower = (monitoredChannel || '').toLowerCase();
    const rows = channels.map(ch => {
        const roleLower = (ch.role || '').toLowerCase();
        const isPrimary   = ch.index === 0;
        const isMonitored = monLower && (ch.name || '').toLowerCase() === monLower;
        const visible = isPrimary || isMonitored;
        if (visible) {
            const up   = ch.uplink_enabled   ? '<span class="badge badge-yes">On</span>'  : '<span class="badge badge-no">Off</span>';
            const down = ch.downlink_enabled ? '<span class="badge badge-yes">On</span>'  : '<span class="badge badge-no">Off</span>';
            return `<tr>
                <td>${ch.index}</td>
                <td>${esc(ch.name || '\u2014')}</td>
                <td><span class="role-badge role-${roleLower}">${esc(ch.role)}</span></td>
                <td style="text-align:center">${up}</td>
                <td style="text-align:center">${down}</td>
            </tr>`;
        }
        return `<tr class="channel-masked">
            <td>${ch.index}</td>
            <td style="color:var(--muted);font-style:italic;letter-spacing:2px">&bull;&bull;&bull;&bull;&bull;</td>
            <td><span class="role-badge role-${roleLower}">${esc(ch.role)}</span></td>
            <td style="text-align:center;color:var(--muted)">&mdash;</td>
            <td style="text-align:center;color:var(--muted)">&mdash;</td>
        </tr>`;
    }).join('');
    body.innerHTML = `<table class="settings-channel-table">
        <thead><tr><th>#</th><th>Name</th><th>Role</th><th>Uplink</th><th>Downlink</th></tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}
