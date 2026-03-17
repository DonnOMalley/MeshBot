"use strict";

// Page init for /nodes
document.addEventListener("DOMContentLoaded", async () => {
  await fetchFavorites();
  fetchNodes();
  setInterval(refreshAll, REFRESH_INTERVAL_MS);
  updateSortIndicators();
});
