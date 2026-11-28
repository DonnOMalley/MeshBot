"""Read-only sizes of the folders the bot writes to (normally ``data/`` and ``log/``).

The scanner only looks at names, sizes and modified times; it never opens a file.
Folder and type lookups from the web page are matched against the last scan, so
a request can never name a path outside the scanned folders.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from datetime import datetime, timezone

from common.constants import (
    _STORAGE_CACHE_SECONDS,
    _STORAGE_CATEGORIES,
    _STORAGE_FOLDER_FILES_MAX,
    _STORAGE_LABELS,
    _STORAGE_OTHER_CATEGORY,
    _STORAGE_TOP_FILES,
)

_EXT_TO_CATEGORY: dict[str, str] = {ext: cat for cat, exts in _STORAGE_CATEGORIES.items() for ext in exts}
_CATEGORY_ORDER: list[str] = list(_STORAGE_CATEGORIES) + [_STORAGE_OTHER_CATEGORY]
_NO_EXT: str = "(none)"


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def file_ext(name: str) -> str:
    """Lower-case extension without the dot; ``(none)`` for names like ``README`` or ``.env``."""
    stem, dot, ext = name.rpartition(".")
    return ext.lower() if dot and stem else _NO_EXT


def category_of(ext: str) -> str:
    return _EXT_TO_CATEGORY.get(ext, _STORAGE_OTHER_CATEGORY)


class StorageScanner:
    """Scans *roots* (display name -> folder) and answers summary/folder/type questions."""

    def __init__(self, roots: dict[str, str], cache_seconds: float = _STORAGE_CACHE_SECONDS) -> None:
        self._roots: dict[str, str] = {name: os.path.abspath(path) for name, path in roots.items()}
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._snap: dict | None = None
        self._snap_time: float = 0.0

    # region Public
    def summary(self) -> dict:
        """Totals, disk space, the folder tree (sizes only) and the file-type groups."""
        snap: dict = self._snapshot()
        folders: dict[str, dict] = snap["folders"]
        files: list[dict] = snap["files"]
        newest: dict | None = max(files, key=lambda f: f["mtime"], default=None)
        return {
            "scanned_at": _iso(snap["time"]),
            "scan_ms": snap["scan_ms"],
            "disk": snap["disk"],
            "total": {
                "size": sum(folders[r]["size"] for r in snap["roots"]),
                "files": len(files),
                "folders": len(folders),
                "newest_file": self._file_out(newest) if newest else None,
            },
            "tree": [self._tree(folders, r) for r in snap["roots"]],
            "categories": self._categories(files),
        }

    def folder(self, path: str) -> dict | None:
        """One folder: its stats, subfolders, own files, and largest/newest files below it."""
        snap: dict = self._snapshot()
        node: dict | None = snap["folders"].get(path)
        if node is None:
            return None
        below: list[dict] = [f for f in snap["files"] if f["folder"] == path or f["folder"].startswith(path + "/")]
        own: list[dict] = sorted((f for f in below if f["folder"] == path), key=lambda f: -f["size"])
        return {
            "folder": self._folder_out(node),
            "types": self._categories(below),
            "subfolders": sorted((self._folder_out(snap["folders"][c]) for c in node["children"]), key=lambda f: -f["size"]),
            "files": [self._file_out(f) for f in own[:_STORAGE_FOLDER_FILES_MAX]],
            "files_omitted": max(0, len(own) - _STORAGE_FOLDER_FILES_MAX),
            "largest": [self._file_out(f) for f in sorted(below, key=lambda f: -f["size"])[:_STORAGE_TOP_FILES]],
            "newest": [self._file_out(f) for f in sorted(below, key=lambda f: -f["mtime"])[:_STORAGE_TOP_FILES]],
        }

    def file_type(self, category: str | None = None, ext: str | None = None) -> dict | None:
        """One type group (a category, or a single extension): where it lives and its biggest files."""
        snap: dict = self._snapshot()
        if ext is not None:
            picked: list[dict] = [f for f in snap["files"] if f["ext"] == ext]
            name: str = ext
        elif category in _CATEGORY_ORDER:
            picked = [f for f in snap["files"] if f["category"] == category]
            name = category
        else:
            return None
        if not picked:
            return None
        by_folder: dict[str, dict] = {}
        for f in picked:
            entry: dict = by_folder.setdefault(f["folder"], {"files": 0, "size": 0})
            entry["files"] += 1
            entry["size"] += f["size"]
        size: int = sum(f["size"] for f in picked)
        oldest: dict = min(picked, key=lambda f: f["mtime"])
        newest: dict = max(picked, key=lambda f: f["mtime"])
        return {
            "name": name,
            "kind": "ext" if ext is not None else "category",
            "category": picked[0]["category"] if ext is not None else category,
            "size": size,
            "files": len(picked),
            "average": size // len(picked),
            "oldest": self._file_out(oldest),
            "newest": self._file_out(newest),
            "exts": self._categories(picked)[0]["exts"] if ext is None else [],
            "folders": sorted(
                ({"path": p, "label": self._label(p), **v} for p, v in by_folder.items()),
                key=lambda f: -f["size"],
            ),
            "largest": [self._file_out(f) for f in sorted(picked, key=lambda f: -f["size"])[:_STORAGE_TOP_FILES]],
        }
    # endregion Public

    # region Scanning
    def _snapshot(self) -> dict:
        with self._lock:
            if self._snap is None or time.monotonic() - self._snap_time > self._cache_seconds:
                self._snap = self._scan()
                self._snap_time = time.monotonic()
            return self._snap

    def _scan(self) -> dict:
        started: float = time.perf_counter()
        folders: dict[str, dict] = {}
        files: list[dict] = []
        roots: list[str] = []
        for name, top in self._roots.items():
            if os.path.islink(top) or not os.path.isdir(top):
                continue  # a symlinked root would lead the scan outside the configured folder
            roots.append(name)
            self._walk(top, name, None, folders, files)
        disk: dict | None = None
        for name in roots:  # only accepted roots, so a rejected symlink is never consulted
            top: str = self._roots[name]
            try:
                usage = shutil.disk_usage(top)
                disk = {"total": usage.total, "used": usage.used, "free": usage.free}
                break
            except OSError:
                continue
        return {
            "time": time.time(),
            "scan_ms": round((time.perf_counter() - started) * 1000),
            "roots": roots,
            "folders": folders,
            "files": files,
            "disk": disk,
        }

    def _walk(self, abs_dir: str, rel: str, parent: str | None, folders: dict[str, dict], files: list[dict]) -> dict:
        """Adds *abs_dir* and everything below it; symlinks are skipped, never followed."""
        node: dict = {"path": rel, "name": rel.rsplit("/", 1)[-1], "parent": parent, "children": [],
                      "size": 0, "files": 0, "folders": 0, "mtime": 0.0}
        folders[rel] = node
        try:
            entries: list[os.DirEntry] = sorted(os.scandir(abs_dir), key=lambda e: e.name)
        except OSError:
            return node
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    child: dict = self._walk(entry.path, rel + "/" + entry.name, rel, folders, files)
                    node["children"].append(child["path"])
                    node["size"] += child["size"]
                    node["files"] += child["files"]
                    node["folders"] += child["folders"] + 1
                    node["mtime"] = max(node["mtime"], child["mtime"])
                elif entry.is_file(follow_symlinks=False):
                    st: os.stat_result = entry.stat(follow_symlinks=False)
                    ext: str = file_ext(entry.name)
                    files.append({"name": entry.name, "folder": rel, "size": st.st_size, "mtime": st.st_mtime,
                                  "ext": ext, "category": category_of(ext)})
                    node["size"] += st.st_size
                    node["files"] += 1
                    node["mtime"] = max(node["mtime"], st.st_mtime)
            except OSError:
                continue  # vanished or unreadable mid-scan
        return node
    # endregion Scanning

    # region Shaping
    @staticmethod
    def _label(path: str) -> str | None:
        if path in _STORAGE_LABELS:
            return _STORAGE_LABELS[path]
        if path.startswith("data/") and path.count("/") == 1 and path.endswith(".txt"):
            return "Chat history (encrypted)"
        if path.startswith("data/tiles/") and path.count("/") == 2:
            return "Zoom level " + path.rsplit("/", 1)[-1]
        return None

    def _folder_out(self, node: dict) -> dict:
        return {"path": node["path"], "name": node["name"], "label": self._label(node["path"]),
                "size": node["size"], "files": node["files"], "folders": node["folders"],
                "modified": _iso(node["mtime"])}

    def _tree(self, folders: dict[str, dict], path: str) -> dict:
        node: dict = folders[path]
        out: dict = self._folder_out(node)
        out["children"] = sorted((self._tree(folders, c) for c in node["children"]), key=lambda f: -f["size"])
        return out

    def _file_out(self, f: dict) -> dict:
        path: str = f["folder"] + "/" + f["name"]
        return {"name": f["name"], "path": path, "folder": f["folder"], "label": self._label(path),
                "size": f["size"], "modified": _iso(f["mtime"]), "ext": f["ext"], "category": f["category"]}

    @staticmethod
    def _categories(files: list[dict]) -> list[dict]:
        """Files grouped by category (fixed order, empty ones left out), each with its extensions."""
        groups: dict[str, dict] = {}
        for f in files:
            g: dict = groups.setdefault(f["category"], {"name": f["category"], "size": 0, "files": 0, "exts": {}})
            g["size"] += f["size"]
            g["files"] += 1
            e: dict = g["exts"].setdefault(f["ext"], {"ext": f["ext"], "size": 0, "files": 0})
            e["size"] += f["size"]
            e["files"] += 1
        result: list[dict] = []
        for name in _CATEGORY_ORDER:
            if name in groups:
                g = groups[name]
                g["exts"] = sorted(g["exts"].values(), key=lambda e: -e["size"])
                result.append(g)
        return result
    # endregion Shaping
