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
