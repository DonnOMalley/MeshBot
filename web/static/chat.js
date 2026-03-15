'use strict';

// Page init for /chat
document.addEventListener('DOMContentLoaded', async () => {
    fetch('/api/channel')
        .then(r => r.json())
        .then(d => {
            document.getElementById('send-channel-name').textContent = d.name || 'primary';
        })
        .catch(() => {
            document.getElementById('send-channel-name').textContent = '(unavailable)';
        });

    fetchChannels();
    setInterval(refreshAll, 30_000);

    // ── Web user identity ────────────────────────────────────────────────
    const userDisplay = document.getElementById('web-user-display');
    const editBtn     = document.getElementById('web-user-edit-btn');
    const editForm    = document.getElementById('web-user-edit-form');
    const longInput   = document.getElementById('wu-long-name');
    const shortInput  = document.getElementById('wu-short-name');
    const saveBtn     = document.getElementById('wu-save-btn');
    const cancelBtn   = document.getElementById('wu-cancel-btn');

    async function loadWebUser() {
        try {
            const res = await fetch('/api/web-user');
            if (res.ok) {
                const u = await res.json();
                userDisplay.textContent = u.display_name;
            }
        } catch (_) { /* non-fatal */ }
    }

    function showEditForm(visible) {
        editBtn.style.display  = visible ? 'none' : '';
        editForm.style.display = visible ? ''     : 'none';
    }

    editBtn.addEventListener('click', () => {
        longInput.value  = '';
        shortInput.value = '';
        showEditForm(true);
        longInput.focus();
    });

    cancelBtn.addEventListener('click', () => { showEditForm(false); });

    async function doSaveUser() {
        const long  = longInput.value.trim();
        const short = shortInput.value.trim().toUpperCase();
        if (!long || !short) return;
        saveBtn.disabled = true;
        try {
            const res = await fetch('/api/web-user', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ long_name: long, short_name: short }),
            });
            if (res.ok) {
                const u = await res.json();
                userDisplay.textContent = u.display_name;
                showEditForm(false);
            } else {
                shortInput.style.borderColor = 'var(--danger, #e55)';
                longInput.style.borderColor  = 'var(--danger, #e55)';
                setTimeout(() => {
                    shortInput.style.borderColor = '';
                    longInput.style.borderColor  = '';
                }, 2000);
            }
        } catch (_) { /* network error — leave form open */ }
        finally {
            saveBtn.disabled = false;
        }
    }

    saveBtn.addEventListener('click', doSaveUser);
    shortInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSaveUser(); });
    longInput.addEventListener('keydown',  e => { if (e.key === 'Enter') doSaveUser(); });

    loadWebUser();

    // ── Send message ─────────────────────────────────────────────────────
    const input  = document.getElementById('send-text');
    const btn    = document.getElementById('send-btn');
    const status = document.getElementById('send-status');

    async function doSend() {
        const text = input.value.trim();
        if (!text) return;
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
    }

    btn.addEventListener('click', doSend);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doSend(); });
});
