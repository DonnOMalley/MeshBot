"""Tests for the mesh !event / !events / !eventinfo commands.

Run from the repo root:  .venv/bin/python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

from common.constants import _EVENTS_SUBDIR, _MESH_MAX_MESSAGE_CHARS, _PACKET_KEY_DECODED, _PACKET_KEY_WEB_RESPONSES
from web.web_server import WebServer  # noqa: F401  first: it reloads web.event_store on import
from web.event_store import EventStore
from commands.event_command_helper import EventCommandHelper, fit_bytes, split_message

NY: ZoneInfo = ZoneInfo("America/New_York")
# A fixed "now": Thursday 2026-11-26 12:00 in New York.
NOW: datetime = datetime(2026, 11, 26, 12, 0, tzinfo=NY).astimezone(timezone.utc)


def _at(day: int, hour: int, minute: int = 0) -> str:
    return EventStore.format_time(datetime(2026, 11, day, hour, minute, tzinfo=NY))


def _fields(**overrides) -> dict:
    base: dict = {
        "name": "Mesh Meetup",
        "description": "Bring radios.",
        "start": _at(28, 19),
        "end": _at(28, 21),
        "tz": "America/New_York",
        "location_type": "physical",
        "location_address": "1 Main St, Dayton, OH",
        "website": "https://example.com",
        "contact_name": "Pat",
        "contact_phone": "(937) 555-0100",
        "contact_phone_texts": "1",
    }
    base.update(overrides)
    return base


def _nbytes(text: str) -> int:
    return len(text.encode("utf-8"))


class EventCommandHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()
        self.store: EventStore = EventStore(self.dir, Fernet.generate_key())
        self.helper: EventCommandHelper = EventCommandHelper(self.store, local_zone=NY)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _create(self, approved: bool = True, **overrides) -> dict:
        clean, errors = EventStore.validate(_fields(**overrides))
        self.assertEqual(errors, {})
        return self.store.create(clean, approved=approved)

    def test_no_events(self) -> None:
        self.assertEqual(self.helper.compute_next(NOW), "No upcoming events are scheduled.")
        self.assertEqual(self.helper.compute_list(NOW), "No upcoming events are scheduled.")
        self.assertEqual(self.helper.compute_details("", NOW), ["No upcoming events are scheduled."])

    def test_no_store(self) -> None:
        self.assertEqual(EventCommandHelper(None).compute_next(NOW), "Events are not available right now.")

    def test_next_event_summary(self) -> None:
        self._create(name="Later", start=_at(30, 9), end=_at(30, 10))
        self._create()
        self.assertEqual(
            self.helper.compute_next(NOW),
            "Next event: Mesh Meetup\nSat Nov 28 7PM-9PM\n1 Main St, Dayton, OH\n!eventinfo 1 for details",
        )

    def test_happening_now_comes_first(self) -> None:
        self._create()
        self._create(name="Lunch", start=_at(26, 11, 30), end=_at(26, 13), location_type="online",
                     location_address="", location_link="https://meet.example.com/x")
        message: str = self.helper.compute_next(NOW)
        self.assertTrue(message.startswith("Happening now: Lunch\nThu Nov 26 11:30AM-1PM\nOnline\n"), message)

    def test_unapproved_and_past_hidden(self) -> None:
        self._create(name="Pending", approved=False)
        self._create(name="Old", start=_at(1, 9), end=_at(1, 10))
        self.assertEqual(self.helper.compute_next(NOW), "No upcoming events are scheduled.")

    def test_long_name_and_address_still_fit_with_hint(self) -> None:
        self._create(name="N" * 120, location_address="A" * 300)
        message: str = self.helper.compute_next(NOW)
        self.assertLessEqual(_nbytes(message), _MESH_MAX_MESSAGE_CHARS)
        self.assertTrue(message.startswith("Next event: NNN"))

    def test_list_is_numbered_and_fits(self) -> None:
        for day in range(27, 31):
            self._create(name=f"Event on the {day}th with a long name " + "x" * 60, start=_at(day, 18), end=_at(day, 19))
        self._create(name="Weekly", start=_at(27, 8), end=_at(27, 9), recurrence="weekly")
        message: str = self.helper.compute_list(NOW)
        self.assertLessEqual(_nbytes(message), _MESH_MAX_MESSAGE_CHARS)
        lines: list[str] = message.split("\n")
        self.assertEqual(lines[0], "Upcoming events:")
        self.assertTrue(lines[1].startswith("1. Fri 11/27 8AM Weekly"), lines[1])
        self.assertEqual(lines[-1], "!eventinfo N for details")
        self.assertEqual(sum("Weekly" in line for line in lines), 1)  # a repeat is listed once

    def test_details_by_number_and_name(self) -> None:
        self._create(name="Trivia", start=_at(29, 18), end=_at(29, 20), recurrence="weekly", contact_signal="pat.01")
        self._create()
        first: list[str] = self.helper.compute_details("", NOW)
        self.assertIn("Mesh Meetup\nWhen: Sat Nov 28 7PM-9PM\nWhere: 1 Main St, Dayton, OH\nBring radios.", first[0])
        second: list[str] = self.helper.compute_details("2", NOW)
        self.assertIn("Repeats: Weekly", second[0])
        self.assertIn("Contact: Pat, (937) 555-0100 (call/text), Signal pat.01", second[0])
        self.assertEqual(self.helper.compute_details("trIVia", NOW), second)
        self.assertEqual(self.helper.compute_details("#2", NOW), second)
        self.assertEqual(self.helper.compute_details("9", NOW), ["There is no event #9. Send !events for the list."])
        self.assertIn("No upcoming event matches", self.helper.compute_details("bingo", NOW)[0])

    def test_long_description_split_into_parts(self) -> None:
        self._create(description=("Lots to say about this event. " * 60).strip())
        parts: list[str] = self.helper.compute_details("1", NOW)
        self.assertGreater(len(parts), 1)
        self.assertLessEqual(len(parts), 5)
        for i, part in enumerate(parts, 1):
            self.assertLessEqual(_nbytes(part), _MESH_MAX_MESSAGE_CHARS)
            self.assertTrue(part.startswith(f"{i}/{len(parts)} "), part[:10])

    def test_all_day_event(self) -> None:
        clean, errors = EventStore.validate(_fields(all_day="1", start_day="2026-11-28", end_day="2026-11-29", start="", end=""))
        self.assertEqual(errors, {})
        self.store.create(clean)
        self.assertIn("\nSat Nov 28-Sun Nov 29\n", self.helper.compute_next(NOW))

    def test_read_only(self) -> None:
        # An ended event left in events.json must not be re-filed by the mesh reader.
        self._create(name="Old", start=_at(1, 9), end=_at(1, 10))
        path: str = os.path.join(self.dir, "events.json")
        before: float = os.path.getmtime(path)
        with open(path) as f:
            raw: str = f.read()
        self.helper.compute_next(NOW)
        with open(path) as f:
            self.assertEqual(f.read(), raw)
        self.assertEqual(os.path.getmtime(path), before)


class SplitTests(unittest.TestCase):
    def test_short_text_single_part(self) -> None:
        self.assertEqual(split_message("hello"), ["hello"])

    def test_emoji_counted_as_bytes(self) -> None:
        text: str = "\U0001f389" * 100  # 400 bytes
        self.assertLessEqual(_nbytes(fit_bytes(text)), _MESH_MAX_MESSAGE_CHARS)
        for part in split_message(text):
            self.assertLessEqual(_nbytes(part), _MESH_MAX_MESSAGE_CHARS)

    def test_overflow_capped(self) -> None:
        parts: list[str] = split_message("word " * 1000, max_parts=3)
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[-1].endswith("…"))


class UserCommandsWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_encrypted_store_and_web_dm(self) -> None:
        from commands.user_commands import UserCommands
        from common.encryption_helper import EncryptionHelper
        from common.constants import _NODE_DB_SALT_FILE

        key = EncryptionHelper.resolve_key("secret", os.path.join(self.dir, _NODE_DB_SALT_FILE))
        store: EventStore = EventStore(os.path.join(self.dir, _EVENTS_SUBDIR), key)
        clean, _ = EventStore.validate(_fields(start=EventStore.format_time(datetime.now(timezone.utc) + timedelta(days=1)),
                                               end=EventStore.format_time(datetime.now(timezone.utc) + timedelta(days=1, hours=1))))
        store.create(clean)
        commands = UserCommands(MagicMock(), MagicMock(), MagicMock(), data_dir=self.dir, passphrase="secret").get_commands()
        self.assertTrue({"event", "events", "eventinfo"} <= set(commands))
        packet: dict = {_PACKET_KEY_DECODED: {}}
        with unittest.mock.patch("common.meshtastic_helper.MeshtasticHelper.is_web_user_packet", return_value=True):
            commands["event"]("!abc", "", packet)
        self.assertTrue(packet[_PACKET_KEY_DECODED][_PACKET_KEY_WEB_RESPONSES][0].startswith("Next event: Mesh Meetup"))

    def test_radio_sends_parts_as_dms(self) -> None:
        from commands.user_commands import UserCommands

        store: EventStore = EventStore(os.path.join(self.dir, _EVENTS_SUBDIR), None)
        clean, _ = EventStore.validate(_fields(description="Long. " * 200,
                                               start=EventStore.format_time(datetime.now(timezone.utc) + timedelta(days=1)),
                                               end=EventStore.format_time(datetime.now(timezone.utc) + timedelta(days=1, hours=1))))
        store.create(clean)
        iface = MagicMock()
        config = MagicMock(node_id="!bot")
        commands = UserCommands(iface, config, MagicMock(index=1), data_dir=self.dir).get_commands()
        with unittest.mock.patch("commands.user_commands.threading.Timer") as timer:
            commands["eventinfo"]("!abc", "1", {"id": 42, _PACKET_KEY_DECODED: {}})
        first = iface.sendText.call_args
        self.assertEqual(first.kwargs["destinationId"], "!abc")
        self.assertTrue(first.args[0].startswith("1/"))
        self.assertGreaterEqual(timer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
