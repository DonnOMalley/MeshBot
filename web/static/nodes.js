'use strict';

// Page init for /nodes
document.addEventListener('DOMContentLoaded', async () => {
    await fetchFavorites();
    fetchNodes();
    setInterval(refreshAll, 30_000);
    updateSortIndicators();
});
