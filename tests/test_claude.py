"""Tests for the passcode-protected Claude sessions page (/claude)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from meshtastic import channel_pb2

from web.web_server import WebServer  # first: it reloads web.claude_sessions on import
from web.claude_sessions import ClaudeSessionReader

SID: str = "11111111-2222-3333-4444-555555555555"
PASSCODE: str = "claude only"


def _write_session(home: str, session_id: str = SID, pid: int | None = None) -> None:
    folder: str = os.path.join(home, "projects", "-home-me-proj")
    os.makedirs(folder, exist_ok=True)
    records: list[dict] = [
        {"type": "user", "timestamp": "2026-11-26T10:00:00Z", "cwd": "/home/me/proj", "message": {"role": "user", "content": "Fix the map page"}},
        {"type": "assistant", "timestamp": "2026-11-26T10:00:05Z", "message": {
            "model": "claude-opus-5-5",
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 50},
            "content": [{"type": "thinking", "thinking": "private"}, {"type": "text", "text": "Looking now."},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls web"}}]}},
        {"type": "user", "timestamp": "2026-11-26T10:00:06Z", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "SECRET_TOKEN=abc123"}]}},
        {"type": "ai-title", "aiTitle": "Map page fix"},
        "not json at all",
        {"type": "cost-state", "totalCostUSD": "0.42"},
    ]
    with open(os.path.join(folder, session_id + ".jsonl"), "w", encoding="utf-8") as f:
        for rec in records:
            f.write((rec if isinstance(rec, str) else json.dumps(rec)) + "\n")
    if pid is not None:
        os.makedirs(os.path.join(home, "sessions"), exist_ok=True)
        with open(os.path.join(home, "sessions", f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "sessionId": session_id, "status": "busy", "cwd": "/home/me/proj"}, f)


class ClaudeSessionReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home: str = tempfile.mkdtemp()
        self.reader = ClaudeSessionReader(self.home)

    def tearDown(self) -> None:
        shutil.rmtree(self.home, ignore_errors=True)

    def test_empty_home(self) -> None:
        self.assertEqual(self.reader.list_sessions(), [])
        self.assertEqual(self.reader.live_sessions(), [])

    def test_summary(self) -> None:
        _write_session(self.home)
        [s] = self.reader.list_sessions()
        self.assertEqual(s["id"], SID)
        self.assertEqual(s["title"], "Map page fix")
        self.assertEqual(s["cwd"], "/home/me/proj")
        self.assertEqual(s["first_prompt"], "Fix the map page")
        self.assertEqual(s["turns"], 1)
        self.assertEqual(s["models"], {"claude-opus-5-5": 1})
        self.assertEqual(s["tokens"]["cache_read_input_tokens"], 1000)
        self.assertEqual(s["cost_usd"], 0.42)
        self.assertIsNone(s["live"])

    def test_live_status_and_stale_pid(self) -> None:
        _write_session(self.home, pid=os.getpid())
        self.assertEqual(self.reader.list_sessions()[0]["live"], "busy")
        _write_session(self.home, pid=2**22 + 12345)  # no such process: ignored
        self.assertEqual(len(self.reader.live_sessions()), 1)

    def test_conversation_has_no_tool_results_or_thinking(self) -> None:
        _write_session(self.home)
        detail: dict = self.reader.get_session(SID)
        roles: list[str] = [m["role"] for m in detail["messages"]]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        self.assertEqual(detail["messages"][2]["text"], "ls web")
        text: str = json.dumps(detail)
        self.assertNotIn("SECRET_TOKEN", text)
        self.assertNotIn("private", text)

    def test_subagent_tokens_are_counted(self) -> None:
        _write_session(self.home)
        self.assertEqual(self.reader.list_sessions()[0]["tokens"]["output_tokens"], 50)
        sub_dir: str = os.path.join(self.home, "projects", "-home-me-proj", SID, "subagents")
        os.makedirs(sub_dir)
        with open(os.path.join(sub_dir, "agent-a1.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-haiku-5-5", "usage": {
                "input_tokens": 1, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3, "output_tokens": 7}}}) + "\n")
        s: dict = self.reader.list_sessions()[0]  # cache must notice the new subagent file
        self.assertEqual(s["subagents"], 1)
        self.assertEqual(s["tokens"], {"input_tokens": 11, "cache_creation_input_tokens": 102, "cache_read_input_tokens": 1003, "output_tokens": 57})
        self.assertEqual(s["subagent_tokens"]["output_tokens"], 7)
        self.assertEqual(s["models"], {"claude-opus-5-5": 1}, "turns and models stay the main session's")

    def test_bad_ids(self) -> None:
        _write_session(self.home)
        for bad in ("../../etc/passwd", "*", "AAAAAAAA-2222-3333-4444-555555555555", SID + "\n", ""):
            self.assertIsNone(self.reader.get_session(bad))
        self.assertIsNone(self.reader.get_session("99999999-2222-3333-4444-555555555555"))

    def test_cache_notices_changes(self) -> None:
        _write_session(self.home)
        self.assertEqual(self.reader.list_sessions()[0]["title"], "Map page fix")
        path: str = os.path.join(self.home, "projects", "-home-me-proj", SID + ".jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "ai-title", "aiTitle": "Renamed"}) + "\n")
        self.assertEqual(self.reader.list_sessions()[0]["title"], "Renamed")
        os.remove(path)
        self.assertEqual(self.reader.list_sessions(), [])


class ClaudePageTests(unittest.TestCase):
    def _write_config(self, passcode: str | None) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("[meshbot]\nbot_name = TestBot\nEventsPasscode = events pass\n")
            if passcode is not None:
                f.write(f"ClaudePasscode = {passcode}\n")

    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()
        self.home: str = os.path.join(self.dir, "claude-home")
        _write_session(self.home)
        self.config_path: str = os.path.join(self.dir, "meshbot.config")
        self._write_config(PASSCODE)
        channel = channel_pb2.Channel()
        channel.settings.name = "Test"
        self.server = WebServer(
            node_db=MagicMock(), iface=MagicMock(), channel=channel, config=MagicMock(),
            bot_name="TestBot", tile_cache=MagicMock(), data_dir=self.dir,
            passphrase="test-passphrase", config_file=self.config_path,
        )
        self.server._claude_reader = ClaudeSessionReader(self.home)
        self.client = self.server._app.test_client()

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sign_in(self, passcode: str = PASSCODE, client=None):
        return (client or self.client).post("/api/claude/auth", json={"passcode": passcode})

    def test_page_and_menu_link(self) -> None:
        html: str = self.client.get("/claude").get_data(as_text=True)
        self.assertIn('src="/static/claude.js"', html)
        self.assertIn('href="/claude"', self.client.get("/").get_data(as_text=True))

    def test_signed_out_gets_nothing(self) -> None:
        self.assertEqual(self.client.get("/api/claude/auth").get_json(), {"enabled": True, "viewer": False})
        for url in ("/api/claude/sessions", f"/api/claude/sessions/{SID}"):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403)
            self.assertTrue(res.get_json()["auth_required"])
            self.assertNotIn("Map page fix", res.get_data(as_text=True))

    def test_sign_in_and_read(self) -> None:
        self.assertEqual(self._sign_in().status_code, 200)
        res = self.client.get("/api/claude/sessions")
        self.assertEqual(res.headers.get("Cache-Control"), "no-store")
        self.assertEqual(res.get_json()["sessions"][0]["title"], "Map page fix")
        detail = self.client.get(f"/api/claude/sessions/{SID}").get_json()
        self.assertEqual(detail["messages"][0]["text"], "Fix the map page")
        self.assertEqual(self.client.get("/api/claude/sessions/99999999-2222-3333-4444-555555555555").status_code, 404)

    def test_events_passcode_does_not_open_claude(self) -> None:
        self.assertEqual(self.client.post("/api/events/auth", json={"passcode": "events pass"}).status_code, 200)
        self.assertEqual(self.client.get("/api/claude/sessions").status_code, 403)
        self.assertEqual(self._sign_in("events pass").status_code, 401)

    def test_claude_passcode_does_not_open_events(self) -> None:
        self._sign_in()
        self.assertFalse(self.client.get("/api/events/auth").get_json()["editor"])

    def test_wrong_passcode_lockout(self) -> None:
        for _ in range(5):
            self.assertEqual(self._sign_in("nope").status_code, 401)
        self.assertEqual(self._sign_in().status_code, 429)
        # The Claude lockout is separate from the Events one.
        self.assertEqual(self.client.post("/api/events/auth", json={"passcode": "events pass"}).status_code, 200)

    def test_sign_out_and_passcode_change(self) -> None:
        self._sign_in()
        self.client.delete("/api/claude/auth")
        self.assertEqual(self.client.get("/api/claude/sessions").status_code, 403)
        self._sign_in()
        self._write_config("new one")
        self.assertEqual(self.client.get("/api/claude/sessions").status_code, 403)

    def test_no_passcode_turns_page_off(self) -> None:
        self._write_config(None)
        self.assertEqual(self.client.get("/api/claude/auth").get_json(), {"enabled": False, "viewer": False})
        self.assertEqual(self._sign_in().status_code, 503)
        self.assertIn("ClaudePasscode", self.client.get("/api/claude/sessions").get_json()["error"])


if __name__ == "__main__":
    unittest.main()
