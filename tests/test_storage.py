"""Tests for the Storage page (/storage): the scanner and the admin-only API."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock
from unittest.mock import MagicMock

from meshtastic import channel_pb2

from web.web_server import WebServer  # first: it reloads web.storage_scanner on import
from web.storage_scanner import StorageScanner, file_ext

USERNAME: str = "donn"
PASSWORD: str = "admin only"


def _write(path: str, size: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)


def _make_tree(root: str) -> tuple[str, str]:
    data: str = os.path.join(root, "data")
    log: str = os.path.join(root, "log")
    _write(os.path.join(data, "nodes.json"), 300)
    _write(os.path.join(data, "primary.txt"), 200)
    _write(os.path.join(data, "tiles", "13", "1", "2.png"), 1000)
    _write(os.path.join(data, "tiles", "13", "1", "3.png"), 500)
    _write(os.path.join(data, "Events", "images", "abc", "clip.mp4"), 700)
    _write(os.path.join(data, "README"), 5)
    _write(os.path.join(log, "console_1.log"), 50)
    os.makedirs(os.path.join(data, "empty"))
    return data, log


class StorageScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()
        data, log = _make_tree(self.dir)
        self.outside: str = os.path.join(self.dir, "outside")
        _write(os.path.join(self.outside, "secret.txt"), 9999)
        os.symlink(self.outside, os.path.join(data, "link"))  # never followed
        self.scanner = StorageScanner({"data": data, "log": log}, cache_seconds=0)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_file_ext(self) -> None:
        self.assertEqual(file_ext("a.PNG"), "png")
        self.assertEqual(file_ext("p1_exif.json"), "json")
        self.assertEqual(file_ext("README"), "(none)")
        self.assertEqual(file_ext(".env"), "(none)")

    def test_summary_totals_and_tree(self) -> None:
        s: dict = self.scanner.summary()
        self.assertEqual(s["total"]["size"], 2755)
        self.assertEqual(s["total"]["files"], 7)
        self.assertEqual([r["path"] for r in s["tree"]], ["data", "log"])
        data: dict = s["tree"][0]
        self.assertEqual(data["label"], "Bot data")
        self.assertEqual(data["children"][0]["path"], "data/tiles", "children are biggest first")
        self.assertEqual(data["children"][0]["label"], "Map tile cache")
        self.assertNotIn("data/link", [c["path"] for c in data["children"]])
        self.assertNotIn("secret", str(s))
        self.assertIsNotNone(s["disk"])

    def test_categories_in_fixed_order(self) -> None:
        cats: list[dict] = self.scanner.summary()["categories"]
        self.assertEqual([c["name"] for c in cats], ["Images", "Data", "Text & chat", "Logs", "Other"])
        self.assertEqual(cats[0]["size"], 1500)
        self.assertEqual(cats[0]["exts"], [{"ext": "png", "size": 1500, "files": 2}])

    def test_folder_detail(self) -> None:
        d: dict = self.scanner.folder("data")
        self.assertEqual([f["name"] for f in d["files"]], ["nodes.json", "primary.txt", "README"])
        self.assertEqual(d["files"][1]["label"], "Chat history (encrypted)")
        self.assertEqual(d["largest"][0]["path"], "data/tiles/13/1/2.png")
        self.assertEqual(d["subfolders"][0]["path"], "data/tiles")
        self.assertEqual(self.scanner.folder("data/tiles/13")["folder"]["label"], "Zoom level 13")
        self.assertEqual(self.scanner.folder("data/empty")["folder"]["files"], 0)

    def test_folder_lookup_cannot_escape(self) -> None:
        for bad in ("", "/", "..", "data/..", "data/link", "/etc", "outside", "data/tiles/../../outside"):
            self.assertIsNone(self.scanner.folder(bad), bad)

    def test_type_detail(self) -> None:
        t: dict = self.scanner.file_type(ext="png")
        self.assertEqual((t["files"], t["size"], t["average"], t["category"]), (2, 1500, 750, "Images"))
        self.assertEqual(t["folders"], [{"path": "data/tiles/13/1", "label": None, "files": 2, "size": 1500}])
        c: dict = self.scanner.file_type(category="Logs")
        self.assertEqual(c["exts"][0]["ext"], "log")
        self.assertIsNone(self.scanner.file_type(category="Nope"))
        self.assertIsNone(self.scanner.file_type(ext="exe"))

    def test_symlinked_root_is_skipped(self) -> None:
        linked_log: str = os.path.join(self.dir, "log_link")
        os.symlink(self.outside, linked_log)
        scanner: StorageScanner = StorageScanner({"data": os.path.join(self.dir, "data"), "log": linked_log}, cache_seconds=0)
        s: dict = scanner.summary()
        self.assertEqual([r["path"] for r in s["tree"]], ["data"])
        self.assertNotIn("secret", str(s))

    def test_disk_usage_skips_symlinked_root(self) -> None:
        linked_log: str = os.path.join(self.dir, "log_link")
        os.symlink(self.outside, linked_log)
        scanner: StorageScanner = StorageScanner({"log": linked_log, "data": os.path.join(self.dir, "data")}, cache_seconds=0)
        with mock.patch("web.storage_scanner.shutil.disk_usage", wraps=shutil.disk_usage) as usage:
            scanner.summary()
        consulted: list[str] = [c.args[0] for c in usage.call_args_list]
        self.assertNotIn(linked_log, consulted)
        self.assertEqual(consulted, [os.path.join(self.dir, "data")])

    def test_disk_usage_none_when_no_root_accepted(self) -> None:
        linked_log: str = os.path.join(self.dir, "log_link")
        os.symlink(self.outside, linked_log)
        scanner: StorageScanner = StorageScanner({"log": linked_log}, cache_seconds=0)
        self.assertIsNone(scanner.summary()["disk"])

    def test_cache_and_rescan(self) -> None:
        cached: StorageScanner = StorageScanner({"data": os.path.join(self.dir, "data")}, cache_seconds=3600)
        self.assertEqual(cached.summary()["total"]["files"], 6)
        _write(os.path.join(self.dir, "data", "new.json"), 1)
        self.assertEqual(cached.summary()["total"]["files"], 6, "served from the cache")
        self.assertEqual(self.scanner.summary()["total"]["files"], 8)


class StoragePageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()
        data, log = _make_tree(self.dir)
        config_path: str = os.path.join(self.dir, "meshbot.config")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(f"[meshbot]\nbot_name = TestBot\nAdminUsername = {USERNAME}\nAdminPassword = {PASSWORD}\n")
        channel = channel_pb2.Channel()
        channel.settings.name = "Test"
        self.server = WebServer(
            node_db=MagicMock(), iface=MagicMock(), channel=channel, config=MagicMock(),
            bot_name="TestBot", tile_cache=MagicMock(), data_dir=data,
            passphrase="test-passphrase", config_file=config_path,
        )
        self.server._storage = StorageScanner({"data": data, "log": log}, cache_seconds=0)
        self.client = self.server._app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sign_in(self) -> None:
        self.client.post("/admin/login", data={"username": USERNAME, "password": PASSWORD, "next": "/storage"})

    def test_signed_out(self) -> None:
        res = self.client.get("/storage")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["Location"].endswith("/admin/login?next=/storage"))
        for url in ("/api/storage", "/api/storage/folder?path=data", "/api/storage/type?ext=png"):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403, url)
            self.assertNotIn("nodes.json", res.get_data(as_text=True))
        self.assertNotIn('href="/storage"', self.client.get("/").get_data(as_text=True))

    def test_signed_in(self) -> None:
        self._sign_in()
        self.assertIn('href="/storage"', self.client.get("/").get_data(as_text=True))
        self.assertIn('src="/static/storage.js"', self.client.get("/storage").get_data(as_text=True))
        res = self.client.get("/api/storage")
        self.assertEqual(res.headers.get("Cache-Control"), "no-store")
        self.assertEqual(res.get_json()["total"]["files"], 8, "7 test files + the salt.bin the server makes")
        self.assertEqual(self.client.get("/api/storage/folder?path=data/tiles").get_json()["folder"]["size"], 1500)
        self.assertEqual(self.client.get("/api/storage/folder?path=../etc").status_code, 404)
        self.assertEqual(self.client.get("/api/storage/type?category=Logs").get_json()["files"], 1)
        self.assertEqual(self.client.get("/api/storage/type?ext=exe").status_code, 404)
        self.assertEqual(self.client.get("/api/storage/type").status_code, 404)


if __name__ == "__main__":
    unittest.main()
