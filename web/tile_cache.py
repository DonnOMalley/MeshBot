"""Tile-caching proxy for offline map support."""

import os
import threading
import time
import urllib.request

from common.constants import (
    _TILE_BASE_URL,
    _TILE_CACHE_DIR,
    _TILE_CONNECT_TIMEOUT,
    _TILE_CONNECTIVITY_URL,
    _TILE_FETCH_TIMEOUT,
    _TILE_INTERNET_AVAILABLE,
    _TILE_INTERNET_UNAVAILABLE,
    _TILE_REFRESH_DONE,
    _TILE_REFRESH_FAILED,
    _TILE_REFRESH_INTERVAL_SECONDS,
    _TILE_SUBDOMAINS,
    _TILE_TTL_SECONDS,
    _TILE_USER_AGENT,
)


class TileCache:
    """Proxies Leaflet map tiles through a local disk cache.

    Tiles are fetched from the OpenTopoMap CDN on cache miss and saved to disk
    so the map continues to work when the network is unavailable.  A background
    daemon thread re-downloads all previously cached tiles every 24 hours to
    keep them reasonably fresh.
    """

    # region Private Variables
    _cache_dir: str
    _ttl_seconds: float
    _refresh_interval_seconds: float
    _subdomain_index: int
    _lock: threading.Lock
    # endregion Private Variables

    # region Constructor
    def __init__(
        self,
        cache_dir: str = _TILE_CACHE_DIR,
        ttl_seconds: float = _TILE_TTL_SECONDS,
        refresh_interval_seconds: float = _TILE_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        """Initialises the tile cache and creates the on-disk cache directory.

        Args:
            cache_dir: Directory where tile PNG files are stored.
            ttl_seconds: Seconds before a cached tile is considered stale and
                         eligible for re-download.
            refresh_interval_seconds: How often the background thread re-downloads
                                      all cached tiles.
        """
        self._cache_dir = cache_dir
        self._ttl_seconds = ttl_seconds
        self._refresh_interval_seconds = refresh_interval_seconds
        self._subdomain_index = 0
        self._lock = threading.Lock()
        os.makedirs(cache_dir, exist_ok=True)
    # endregion Constructor

    # region Public Functions
    def start(self) -> None:
        """Starts the background tile refresh daemon thread.

        On the first iteration the thread immediately checks internet
        connectivity and refreshes any tiles already in the cache.  Subsequent
        refreshes occur every ``refresh_interval_seconds``.
        """
        t: threading.Thread = threading.Thread(target=self._refresh_loop, daemon=True)
        t.start()

    def get_tile(self, z: int, x: int, y: int) -> bytes | None:
        """Returns PNG image bytes for the requested tile coordinates.

        Serves a fresh cached tile when one exists.  Otherwise fetches the tile
        from the OpenTopoMap CDN, saves it, and returns it.  If the network is
        unavailable but a stale cached copy exists, the stale copy is returned
        as a fallback.

        Args:
            z: Zoom level (0–17).
            x: Tile column index.
            y: Tile row index.

        Returns:
            Raw PNG bytes, or None if the tile cannot be served.
        """
        path: str = self._tile_path(z, x, y)
        result: bytes | None = None
        if self._is_fresh(path):
            result = self._read_file(path)
        else:
            fetched: bytes | None = self._fetch_tile(z, x, y)
            if fetched is not None:
                self._save_tile(path, fetched)
                result = fetched
            elif os.path.isfile(path):
                result = self._read_file(path)
        return result

    def is_internet_available(self) -> bool:
        """Returns True if the OpenTopoMap tile CDN is reachable.

        Returns:
            True if a test request to the CDN succeeds, False on any error.
        """
        available: bool = False
        try:
            req: urllib.request.Request = urllib.request.Request(
                _TILE_CONNECTIVITY_URL,
                headers={"User-Agent": _TILE_USER_AGENT},
            )
            urllib.request.urlopen(req, timeout=_TILE_CONNECT_TIMEOUT)
            available = True
        except Exception:
            pass
        return available

    def refresh_cached_tiles(self) -> int:
        """Re-downloads every tile currently stored in the local cache.

        Returns:
            The number of tiles successfully refreshed.
        """
        count: int = 0
        for z_name in os.listdir(self._cache_dir):
            z_path: str = os.path.join(self._cache_dir, z_name)
            if os.path.isdir(z_path) and z_name.isdigit():
                for x_name in os.listdir(z_path):
                    x_path: str = os.path.join(z_path, x_name)
                    if os.path.isdir(x_path) and x_name.isdigit():
                        for y_file in os.listdir(x_path):
                            if y_file.endswith(".png") and y_file[:-4].isdigit():
                                count += self._refresh_single_tile(
                                    int(z_name), int(x_name), int(y_file[:-4])
                                )
        return count
    # endregion Public Functions

    # region Private Functions
    def _refresh_loop(self) -> None:
        """Background thread body: checks internet, refreshes the cache, then sleeps."""
        while True:
            if self.is_internet_available():
                print(_TILE_INTERNET_AVAILABLE)
                count: int = self.refresh_cached_tiles()
                if count > 0:
                    print(_TILE_REFRESH_DONE.format(count=count))
            else:
                print(_TILE_INTERNET_UNAVAILABLE)
            time.sleep(self._refresh_interval_seconds)

    def _refresh_single_tile(self, z: int, x: int, y: int) -> int:
        """Fetches one tile from the CDN and overwrites the cached copy.

        Args:
            z: Zoom level.
            x: Tile column index.
            y: Tile row index.

        Returns:
            1 if the tile was successfully refreshed, 0 otherwise.
        """
        result: int = 0
        path: str = self._tile_path(z, x, y)
        try:
            data: bytes | None = self._fetch_tile(z, x, y)
            if data is not None:
                self._save_tile(path, data)
                result = 1
        except Exception as error:
            print(_TILE_REFRESH_FAILED.format(z=z, x=x, y=y, error=error))
        return result

    def _tile_path(self, z: int, x: int, y: int) -> str:
        """Returns the local filesystem path for a tile file.

        Args:
            z: Zoom level.
            x: Tile column index.
            y: Tile row index.

        Returns:
            Absolute (or relative-to-cwd) path string for the tile PNG.
        """
        return os.path.join(self._cache_dir, str(z), str(x), f"{y}.png")

    def _is_fresh(self, path: str) -> bool:
        """Returns True if the cached tile exists and is within the TTL.

        Args:
            path: Filesystem path to the cached tile.

        Returns:
            True when the file is present and younger than ``_ttl_seconds``.
        """
        result: bool = False
        if os.path.isfile(path):
            age: float = time.time() - os.path.getmtime(path)
            result = age < self._ttl_seconds
        return result

    def _fetch_tile(self, z: int, x: int, y: int) -> bytes | None:
        """Downloads a tile from the OpenTopoMap CDN, rotating through subdomains.

        Args:
            z: Zoom level.
            x: Tile column index.
            y: Tile row index.

        Returns:
            Raw PNG bytes on success, or None on any network or HTTP error.
        """
        with self._lock:
            sub: str = _TILE_SUBDOMAINS[self._subdomain_index % len(_TILE_SUBDOMAINS)]
            self._subdomain_index += 1
        url: str = _TILE_BASE_URL.format(sub=sub, z=z, x=x, y=y)
        result: bytes | None = None
        try:
            req: urllib.request.Request = urllib.request.Request(
                url, headers={"User-Agent": _TILE_USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=_TILE_FETCH_TIMEOUT) as resp:
                result = resp.read()
        except Exception:
            pass
        return result

    def _save_tile(self, path: str, data: bytes) -> None:
        """Writes tile bytes to disk, creating any missing parent directories.

        Args:
            path: Destination file path.
            data: Raw PNG bytes to write.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def _read_file(self, path: str) -> bytes | None:
        """Reads and returns the raw bytes of a cached tile file.

        Args:
            path: Path to the cached tile file.

        Returns:
            File contents as bytes, or None if reading fails.
        """
        result: bytes | None = None
        try:
            with open(path, "rb") as f:
                result = f.read()
        except OSError:
            pass
        return result
    # endregion Private Functions
