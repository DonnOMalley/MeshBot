"""Read-only view of the Claude Code sessions stored on this computer.

Claude Code keeps one transcript per session at
``~/.claude/projects/<folder>/<sessionId>.jsonl`` (one JSON record per line) and
a small status file per running session at ``~/.claude/sessions/<pid>.json``.
The format is internal to Claude Code and can change between versions, so
anything this reader does not recognise is skipped rather than raising.

Tool *results* are never returned: they hold raw command output and file
contents, which is where secrets are most likely to appear.
"""
from __future__ import annotations

import glob
import json
import os
import re
import threading

from common.constants import (
    _CLAUDE_MAX_MESSAGES,
    _CLAUDE_TEXT_MAX_LEN,
    _CLAUDE_TOOL_INPUT_MAX_LEN,
)

_SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TOKEN_KEYS: tuple[str, ...] = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


class ClaudeSessionReader:
    """Lists and reads Claude Code sessions under *home_dir* (normally ``~/.claude``)."""

    def __init__(self, home_dir: str) -> None:
        self._home = os.path.expanduser(home_dir)
        self._cache: dict[str, tuple[tuple[float, int], dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_valid_id(session_id: str) -> bool:
        return bool(_SESSION_ID_RE.fullmatch(session_id or ""))

    # region Listing
    def list_sessions(self) -> list[dict]:
        """Every stored session, most recently active first, with live status merged in."""
        live: dict[str, dict] = {s["session_id"]: s for s in self.live_sessions()}
        paths: list[str] = glob.glob(os.path.join(self._home, "projects", "*", "*.jsonl"))
        result: list[dict] = []
        for path in paths:
            summary: dict | None = self._cached_summary(path)
            if summary is not None:
                item: dict = dict(summary)
                running: dict | None = live.get(item["id"])
                item["live"] = running["status"] if running else None
                result.append(item)
        with self._lock:  # forget files that have been cleaned up
            for gone in set(self._cache) - set(paths):
                del self._cache[gone]
        result.sort(key=lambda s: s["updated"] or "", reverse=True)
        return result

    def live_sessions(self) -> list[dict]:
        """Sessions whose Claude Code process is still running."""
        result: list[dict] = []
        for path in glob.glob(os.path.join(self._home, "sessions", "*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    data: dict = json.load(f)
                pid: int = int(data["pid"])
                os.kill(pid, 0)  # raises when the process is gone (stale file)
            except PermissionError:
                pass  # running, but as another user
            except (OSError, ValueError, KeyError, TypeError):
                continue
            result.append({
                "session_id": data.get("sessionId"),
                "pid": data.get("pid"),
                "name": data.get("name"),
                "cwd": data.get("cwd"),
                "status": data.get("status") or "running",
                "kind": data.get("kind"),
            })
        return result

    def _cached_summary(self, path: str) -> dict | None:
        try:
            st: os.stat_result = os.stat(path)
        except OSError:
            return None
        key: tuple[float, int] = (st.st_mtime, st.st_size)
        with self._lock:
            hit = self._cache.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
        summary: dict | None = self._summarize(path)
        if summary is not None:
            with self._lock:
                self._cache[path] = (key, summary)
        return summary

    def _summarize(self, path: str) -> dict | None:
        session_id: str = os.path.basename(path)[: -len(".jsonl")]
        if not self.is_valid_id(session_id):
            return None
        s: dict = {
            "id": session_id, "title": None, "cwd": None, "first_prompt": None,
            "started": None, "updated": None, "turns": 0, "models": {},
            "tokens": dict.fromkeys(_TOKEN_KEYS, 0), "cost_usd": None,
            "subagents": len(glob.glob(os.path.join(path[: -len(".jsonl")], "subagents", "*.jsonl"))),
        }
        for rec in _records(path):
            kind = rec.get("type")
            ts = rec.get("timestamp")
            if isinstance(ts, str):
                s["started"] = s["started"] or ts
                s["updated"] = ts
            if not s["cwd"] and isinstance(rec.get("cwd"), str):
                s["cwd"] = rec["cwd"]
            if kind == "ai-title" and isinstance(rec.get("aiTitle"), str):
                s["title"] = rec["aiTitle"]
            elif kind == "cost-state":
                try:
                    s["cost_usd"] = round(float(rec["totalCostUSD"]), 4)
                except (KeyError, TypeError, ValueError):
                    pass
            elif kind == "user" and s["first_prompt"] is None and not rec.get("isMeta"):
                content = (rec.get("message") or {}).get("content")
                if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
                    s["first_prompt"] = content.strip()[:200]
            elif kind == "assistant":
                message = rec.get("message") or {}
                usage = message.get("usage") if isinstance(message, dict) else None
                if isinstance(usage, dict):
                    s["turns"] += 1
                    model = str(message.get("model"))
                    s["models"][model] = s["models"].get(model, 0) + 1
                    for k in _TOKEN_KEYS:
                        value = usage.get(k)
                        if isinstance(value, int):
                            s["tokens"][k] += value
        s["models"].pop("<synthetic>", None)
        return s
    # endregion Listing

    # region One session
    def get_session(self, session_id: str) -> dict | None:
        """The session's summary and its conversation, or None when it does not exist.

        Returns user and assistant text plus a short form of each tool call; the
        newest ``_CLAUDE_MAX_MESSAGES`` entries only, with ``omitted`` counting the rest.
        """
        if not self.is_valid_id(session_id):
            return None
        matches: list[str] = glob.glob(os.path.join(self._home, "projects", "*", session_id + ".jsonl"))
        if not matches:
            return None
        path: str = matches[0]
        summary: dict | None = self._cached_summary(path)
        if summary is None:
            return None
        messages: list[dict] = []
        for rec in _records(path):
            if rec.get("type") not in ("user", "assistant") or rec.get("isMeta") or rec.get("isSidechain"):
                continue
            content = (rec.get("message") or {}).get("content")
            blocks: list = [{"type": "text", "text": content}] if isinstance(content, str) else (content if isinstance(content, list) else [])
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    messages.append({"role": rec["type"], "ts": rec.get("timestamp"), "text": _clip(str(block["text"]), _CLAUDE_TEXT_MAX_LEN)})
                elif block.get("type") == "tool_use":
                    messages.append({"role": "tool", "ts": rec.get("timestamp"), "tool": str(block.get("name", "")),
                                     "text": _clip(_tool_summary(block.get("input")), _CLAUDE_TOOL_INPUT_MAX_LEN)})
        omitted: int = max(0, len(messages) - _CLAUDE_MAX_MESSAGES)
        live: dict = {s["session_id"]: s for s in self.live_sessions()}
        session: dict = dict(summary)
        session["live"] = live[session_id]["status"] if session_id in live else None
        return {"session": session, "messages": messages[omitted:], "omitted": omitted}
    # endregion One session


def _records(path: str):
    """Each JSON object in a .jsonl file; bad lines and unreadable files are skipped."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def _tool_summary(tool_input) -> str:
    """The most telling field of a tool call (command, path, pattern…), else its JSON."""
    if isinstance(tool_input, dict):
        for key in ("description", "command", "file_path", "pattern", "url", "query", "prompt"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return json.dumps(tool_input, ensure_ascii=False)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
