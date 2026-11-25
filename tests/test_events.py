"""Tests for the Events page: the encrypted event store and its web API.

Run from the repo root:  .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from meshtastic import channel_pb2

from common.constants import _EVENTS_FILE, _EVENTS_HISTORY_FILE, _EVENTS_SUBDIR
from web.web_server import WebServer  # first: it reloads web.event_store on import
from web.event_store import EventStore, EventStoreError, build_ics, occurrences

PNG: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG: bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _iso(delta_hours: float) -> str:
    return EventStore.format_time(datetime.now(timezone.utc) + timedelta(hours=delta_hours))


def _fields(**overrides) -> dict:
    base: dict = {
        "name": "Mesh Meetup",
        "description": "Bring radios. Details at https://example.com/meetup.",
        "start": _iso(24),
        "end": _iso(26),
        "location_type": "physical",
        "location_address": "1 Main St, Dayton, OH",
        "location_link": "",
        "website": "https://example.com",
        "contact_name": "Pat",
        "contact_signal": "pat.01",
        "contact_phone": "(937) 555-0100",
        "contact_phone_texts": "1",
    }
    base.update(overrides)
    return base


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()
        self.key: bytes = Fernet.generate_key()
        self.store: EventStore = EventStore(self.dir, self.key)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _create(self, **overrides) -> dict:
        clean, errors = EventStore.validate(_fields(**overrides))
        self.assertEqual(errors, {})
        return self.store.create(clean)

    # ── validation ──
    def test_valid_fields_are_normalised(self) -> None:
        clean, errors = EventStore.validate(_fields(start="2026-12-01T18:00:00.000Z", end="2026-12-01T20:00:00-05:00"))
        self.assertEqual(errors, {})
        self.assertEqual(clean["start"], "2026-12-01T18:00:00Z")
        self.assertEqual(clean["end"], "2026-12-02T01:00:00Z")
        self.assertEqual(clean["location"], {"type": "physical", "address": "1 Main St, Dayton, OH", "link": ""})
        self.assertTrue(clean["contact"]["phone_texts"])

    def test_required_fields(self) -> None:
        _, errors = EventStore.validate({})
        self.assertEqual(set(errors), {"name", "start", "end", "location_type"})

    def test_end_before_start_rejected(self) -> None:
        _, errors = EventStore.validate(_fields(start=_iso(5), end=_iso(4)))
        self.assertIn("end", errors)

    def test_non_http_links_rejected(self) -> None:
        _, errors = EventStore.validate(_fields(website="javascript:alert(1)"))
        self.assertIn("website", errors)
        _, errors = EventStore.validate(_fields(location_type="online", location_link="ftp://x"))
        self.assertIn("location_link", errors)

    def test_online_requires_link_and_physical_requires_address(self) -> None:
        _, errors = EventStore.validate(_fields(location_type="online"))
        self.assertIn("location_link", errors)
        _, errors = EventStore.validate(_fields(location_address=""))
        self.assertIn("location_address", errors)
        clean, errors = EventStore.validate(_fields(location_type="online", location_link="https://meet.example/x"))
        self.assertEqual(errors, {})
        self.assertEqual(clean["location"]["address"], "")

    def test_phone_validation_and_text_flag(self) -> None:
        _, errors = EventStore.validate(_fields(contact_phone="call me"))
        self.assertIn("contact_phone", errors)
        clean, _ = EventStore.validate(_fields(contact_phone="", contact_phone_texts="1"))
        self.assertFalse(clean["contact"]["phone_texts"])

    # ── persistence ──
    def test_create_get_update_delete(self) -> None:
        ev: dict = self._create()
        self.assertTrue(EventStore.is_valid_id(ev["id"]))
        self.assertEqual(ev["status"], "upcoming")
        self.assertEqual(self.store.get(ev["id"])["name"], "Mesh Meetup")

        clean, _ = EventStore.validate(_fields(name="Renamed"))
        updated: dict = self.store.update(ev["id"], clean)
        self.assertEqual(updated["name"], "Renamed")
        self.assertEqual(updated["id"], ev["id"])
        self.assertEqual(updated["created_at"], ev["created_at"])

        self.assertTrue(self.store.delete(ev["id"]))
        self.assertIsNone(self.store.get(ev["id"]))
        self.assertFalse(self.store.delete(ev["id"]))

    def test_files_are_encrypted_at_rest(self) -> None:
        self._create()
        with open(os.path.join(self.dir, _EVENTS_FILE), encoding="utf-8") as f:
            raw: str = f.read()
        self.assertNotIn("Mesh Meetup", raw)
        data: list = json.loads(Fernet(self.key).decrypt(raw.encode()).decode())
        self.assertEqual(data[0]["name"], "Mesh Meetup")
        self.assertNotIn("status", data[0])

    def test_plain_store_without_key(self) -> None:
        plain: EventStore = EventStore(self.dir, None)
        clean, _ = EventStore.validate(_fields())
        plain.create(clean)
        with open(os.path.join(self.dir, _EVENTS_FILE), encoding="utf-8") as f:
            self.assertEqual(json.load(f)[0]["name"], "Mesh Meetup")
        # Turning encryption on later still reads the plain file.
        self.assertEqual(len(EventStore(self.dir, self.key).list_events()), 1)

    def test_ended_events_move_to_history_and_back(self) -> None:
        past: dict = self._create(name="Old", start=_iso(-5), end=_iso(-3))
        self._create(name="Soon")
        active: dict = self._create(name="Now", start=_iso(-1), end=_iso(1))
        statuses: dict = {e["name"]: e["status"] for e in self.store.list_events()}
        self.assertEqual(statuses, {"Old": "past", "Soon": "upcoming", "Now": "active"})

        def names(filename: str) -> set:
            with open(os.path.join(self.dir, filename), encoding="utf-8") as f:
                return {e["name"] for e in json.loads(Fernet(self.key).decrypt(f.read().encode()))}

        self.assertEqual(names(_EVENTS_FILE), {"Soon", "Now"})
        self.assertEqual(names(_EVENTS_HISTORY_FILE), {"Old"})

        # The active event ends: the next read archives it.
        later: datetime = datetime.now(timezone.utc) + timedelta(hours=2)
        self.store.list_events(now=later)
        self.assertEqual(names(_EVENTS_HISTORY_FILE), {"Old", "Now"})

        # Editing a past event into the future moves it back.
        clean, _ = EventStore.validate(_fields(name="Old", start=_iso(48), end=_iso(50)))
        self.store.update(past["id"], clean)
        self.assertIn("Old", names(_EVENTS_FILE))
        self.assertNotIn("Old", names(_EVENTS_HISTORY_FILE))
        self.assertEqual(self.store.get(active["id"])["status"], "active")

    def test_wrong_key_refuses_and_never_overwrites(self) -> None:
        self._create()
        path: str = os.path.join(self.dir, _EVENTS_FILE)
        with open(path, encoding="utf-8") as f:
            before: str = f.read()
        wrong: EventStore = EventStore(self.dir, Fernet.generate_key())
        with self.assertRaises(EventStoreError):
            wrong.list_events()
        clean, _ = EventStore.validate(_fields())
        with self.assertRaises(EventStoreError):
            wrong.create(clean)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_images_encrypted_and_paths_validated(self) -> None:
        ev: dict = self._create()
        self.store.save_cover(ev["id"], PNG, JPEG)
        img_path: str = os.path.join(self.dir, "images", ev["id"], "cover.img")
        with open(img_path, "rb") as f:
            self.assertFalse(f.read().startswith(b"\x89PNG"))
        self.assertEqual(self.store.read_image(ev["id"], "cover"), PNG)
        self.assertEqual(self.store.read_image(ev["id"], "cover_thumb"), JPEG)
        self.assertIsNone(self.store.read_image(ev["id"], "../../salt"))
        self.assertIsNone(self.store.read_image("../x", "cover"))
        with self.assertRaises(ValueError):
            self.store.save_image("../evil", "cover", PNG)
        self.store.delete(ev["id"])
        self.assertFalse(os.path.exists(os.path.dirname(img_path)))

    def test_add_photo(self) -> None:
        ev: dict = self._create(start=_iso(-1), end=_iso(1))
        photo: dict = self.store.add_photo(ev["id"], "  Sam  ", JPEG, JPEG)
        self.assertEqual(photo["uploader"], "Sam")
        self.assertEqual(self.store.get(ev["id"])["photos"], [photo])
        self.assertEqual(self.store.read_image(ev["id"], photo["id"] + "_thumb"), JPEG)
        self.assertIsNone(self.store.add_photo("0" * 16, "x", JPEG, JPEG))

    def test_detect_image_type(self) -> None:
        self.assertEqual(EventStore.detect_image_type(PNG), "image/png")
        self.assertEqual(EventStore.detect_image_type(JPEG), "image/jpeg")
        self.assertEqual(EventStore.detect_image_type(b"GIF89a..."), "image/gif")
        self.assertEqual(EventStore.detect_image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertIsNone(EventStore.detect_image_type(b"<svg onload=alert(1)>"))


class _EventsServerCase(unittest.TestCase):
    """Shared setup: a web server on a temp data dir, signed in as an organizer."""

    PASSCODE: str = "open sesame"

    def _write_config(self, passcode: str | None) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("[meshbot]\nbot_name = TestBot\n")
            if passcode is not None:
                f.write(f"EventsPasscode = {passcode}\n")

    def _sign_in(self, passcode: str | None = None, client=None):
        return (client or self.client).post("/api/events/auth", json={"passcode": passcode if passcode is not None else self.PASSCODE})

    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()
        self.config_path: str = os.path.join(self.dir, "meshbot.config")
        self._write_config(self.PASSCODE)
        channel = channel_pb2.Channel()
        channel.settings.name = "Test"
        channel.index = 1
        self.server: WebServer = WebServer(
            node_db=MagicMock(),
            iface=MagicMock(),
            channel=channel,
            config=MagicMock(),
            bot_name="TestBot",
            tile_cache=MagicMock(),
            data_dir=self.dir,
            passphrase="test-passphrase",
            config_file=self.config_path,
        )
        self.client = self.server._app.test_client()
        self.assertEqual(self._sign_in().status_code, 200)

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _post(self, url: str, fields: dict, files: dict | None = None, method: str = "post"):
        data: dict = dict(fields)
        for name, content in (files or {}).items():
            data[name] = [(io.BytesIO(c), f"{name}{i}.jpg") for i, c in enumerate(content)] if isinstance(content, list) else (io.BytesIO(content), f"{name}.jpg")
        return getattr(self.client, method)(url, data=data, content_type="multipart/form-data")

    def _visitor(self):
        return self.server._app.test_client()


class EventsApiTests(_EventsServerCase):
    def test_page_and_menu_link(self) -> None:
        html: str = self.client.get("/events").get_data(as_text=True)
        self.assertIn('src="/static/events.js"', html)
        self.assertIn("nav-link active", html)
        history_at: int = html.index('href="/history"')
        events_at: int = html.index('href="/events"')
        self.assertGreater(events_at, history_at)
        # The link right after History is Events.
        self.assertEqual(html.index("<a ", history_at + 1), html.rindex("<a ", 0, events_at))
        # Other pages show the link too.
        self.assertIn('href="/events"', self.client.get("/history").get_data(as_text=True))

    def test_default_image_served(self) -> None:
        res = self.client.get("/images/event%20default.svg")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"<svg", res.data)
        res.close()

    def test_create_with_image_and_serve_it(self) -> None:
        res = self._post("/api/events", _fields(), {"image": PNG, "image_thumb": JPEG})
        self.assertEqual(res.status_code, 201, res.get_json())
        ev: dict = res.get_json()
        self.assertTrue(ev["has_image"])
        img = self.client.get(f"/events/{ev['id']}/image/cover")
        self.assertEqual((img.status_code, img.mimetype, img.data), (200, "image/png", PNG))
        thumb = self.client.get(f"/events/{ev['id']}/image/cover_thumb")
        self.assertEqual((thumb.mimetype, thumb.data), ("image/jpeg", JPEG))
        listed: list = self.client.get("/api/events").get_json()["events"]
        self.assertEqual([e["id"] for e in listed], [ev["id"]])
        self.assertEqual(self.client.get(f"/api/events/{ev['id']}").get_json()["name"], "Mesh Meetup")

    def test_create_without_image_uses_default(self) -> None:
        ev: dict = self._post("/api/events", _fields()).get_json()
        self.assertFalse(ev["has_image"])
        self.assertEqual(self.client.get(f"/events/{ev['id']}/image/cover").status_code, 404)

    def test_create_invalid_returns_field_errors(self) -> None:
        res = self._post("/api/events", _fields(name="", website="javascript:alert(1)"))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.get_json()["fields"]), {"name", "website"})
        self.assertEqual(self.client.get("/api/events").get_json()["events"], [])

    def test_non_image_upload_rejected(self) -> None:
        res = self._post("/api/events", _fields(), {"image": b"<svg onload=alert(1)></svg>"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("image", res.get_json()["fields"])

    def test_update_keeps_photos_and_can_remove_image(self) -> None:
        ev: dict = self._post("/api/events", _fields(start=_iso(-1), end=_iso(1)), {"image": PNG}).get_json()
        self.assertEqual(self._post(f"/api/events/{ev['id']}/photos", {"uploader": "Sam"}, {"photo": [JPEG], "thumb": [JPEG]}).status_code, 201)

        res = self._post(f"/api/events/{ev['id']}", _fields(name="Edited", start=_iso(-1), end=_iso(1)), method="put")
        self.assertEqual(res.status_code, 200)
        edited: dict = res.get_json()
        self.assertEqual((edited["name"], edited["has_image"], len(edited["photos"])), ("Edited", True, 1))

        res = self._post(f"/api/events/{ev['id']}", _fields(start=_iso(-1), end=_iso(1), remove_image="1"), method="put")
        self.assertFalse(res.get_json()["has_image"])
        self.assertEqual(self.client.get(f"/events/{ev['id']}/image/cover").status_code, 404)

        res = self._post(f"/api/events/{ev['id']}", _fields(start=_iso(-1), end=_iso(1)), {"image": JPEG}, method="put")
        self.assertTrue(res.get_json()["has_image"])
        self.assertEqual(self.client.get(f"/events/{ev['id']}/image/cover_thumb").data, JPEG)

    def test_update_unknown_event(self) -> None:
        self.assertEqual(self._post("/api/events/" + "a" * 16, _fields(), method="put").status_code, 404)
        self.assertEqual(self._post("/api/events/not-an-id", _fields(), method="put").status_code, 404)

    def test_photos_only_while_active(self) -> None:
        upcoming: dict = self._post("/api/events", _fields()).get_json()
        res = self._post(f"/api/events/{upcoming['id']}/photos", {}, {"photo": [JPEG]})
        self.assertEqual(res.status_code, 409)

        past: dict = self._post("/api/events", _fields(start=_iso(-5), end=_iso(-4))).get_json()
        self.assertEqual(past["status"], "past")
        self.assertEqual(self._post(f"/api/events/{past['id']}/photos", {}, {"photo": [JPEG]}).status_code, 409)

        active: dict = self._post("/api/events", _fields(start=_iso(-1), end=_iso(1))).get_json()
        res = self._post(f"/api/events/{active['id']}/photos", {"uploader": "Sam"}, {"photo": [JPEG, b"not an image", PNG], "thumb": [JPEG, JPEG, PNG]})
        self.assertEqual(res.status_code, 201)
        body: dict = res.get_json()
        self.assertEqual((len(body["added"]), body["rejected"]), (2, 1))
        photo_id: str = body["added"][0]["id"]
        self.assertEqual(self.client.get(f"/events/{active['id']}/image/{photo_id}").data, JPEG)
        self.assertEqual(len(self.client.get(f"/api/events/{active['id']}").get_json()["photos"]), 2)

        self.assertEqual(self._post(f"/api/events/{active['id']}/photos", {}).status_code, 400)

    def test_delete(self) -> None:
        ev: dict = self._post("/api/events", _fields(), {"image": PNG}).get_json()
        self.assertEqual(self.client.delete(f"/api/events/{ev['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/events/{ev['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/events/{ev['id']}/image/cover").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/events/{ev['id']}").status_code, 404)

    def test_image_route_rejects_traversal(self) -> None:
        for url in ("/events/..%2F..%2Fsalt/image/cover", "/events/abcdef12/image/..%2Fx", "/events/abcdef12/image/cover.img"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_upload_too_large(self) -> None:
        big: bytes = b"\xff\xd8\xff" + b"\x00" * (41 * 1024 * 1024)
        res = self._post("/api/events", _fields(), {"image": big})
        self.assertEqual(res.status_code, 413)
        self.assertIn("too large", res.get_json()["error"])

    def test_events_are_stored_encrypted_on_disk(self) -> None:
        self._post("/api/events", _fields(name="Secret Picnic"))
        path: str = os.path.join(self.dir, _EVENTS_SUBDIR, _EVENTS_FILE)
        with open(path, encoding="utf-8") as f:
            self.assertNotIn("Secret Picnic", f.read())


class EventsAuthTests(_EventsServerCase):
    """Organizer passcode protection. Inherits the API tests' setup (signed in)."""

    def test_status_reports_signed_in(self) -> None:
        self.assertEqual(self.client.get("/api/events/auth").get_json(), {"enabled": True, "editor": True})

    def test_visitors_cannot_change_events(self) -> None:
        ev: dict = self._post("/api/events", _fields(start=_iso(-1), end=_iso(1))).get_json()
        visitor = self.server._app.test_client()
        self.assertEqual(visitor.get("/api/events/auth").get_json(), {"enabled": True, "editor": False})
        for res in (
            visitor.put(f"/api/events/{ev['id']}", data=_fields(name="Hacked"), content_type="multipart/form-data"),
            visitor.delete(f"/api/events/{ev['id']}"),
        ):
            self.assertEqual(res.status_code, 403)
            self.assertTrue(res.get_json()["auth_required"])
        self.assertEqual(self.client.get(f"/api/events/{ev['id']}").get_json()["name"], "Mesh Meetup")
        # Viewing and photo uploads stay open to everyone.
        self.assertEqual(visitor.get("/api/events").status_code, 200)
        res = visitor.post(f"/api/events/{ev['id']}/photos", data={"photo": (io.BytesIO(JPEG), "p.jpg")}, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 201)

    def test_wrong_passcode_and_lockout(self) -> None:
        visitor = self.server._app.test_client()
        for _ in range(5):
            self.assertEqual(self._sign_in("nope", visitor).status_code, 401)
        res = self._sign_in(client=visitor)
        self.assertEqual(res.status_code, 429, "locked out even with the right passcode")
        self.assertIn("Too many", res.get_json()["error"])
        self.assertFalse(visitor.get("/api/events/auth").get_json()["editor"])

    def test_sign_out(self) -> None:
        ev: dict = self._post("/api/events", _fields()).get_json()
        self.assertFalse(self.client.delete("/api/events/auth").get_json()["editor"])
        self.assertEqual(self._post(f"/api/events/{ev['id']}", _fields(), method="put").status_code, 403)
        # Signed out, a new event becomes a submission.
        self.assertEqual(self._post("/api/events", _fields()).status_code, 202)

    def test_changing_passcode_signs_everyone_out(self) -> None:
        self._write_config("new passcode")
        self.assertFalse(self.client.get("/api/events/auth").get_json()["editor"])
        self.assertEqual(self._post("/api/events", _fields()).status_code, 202)
        self.assertEqual(self._sign_in("new passcode").status_code, 200)
        self.assertEqual(self._post("/api/events", _fields()).status_code, 201)

    def test_no_passcode_turns_editing_off(self) -> None:
        self._write_config(None)
        self.assertEqual(self.client.get("/api/events/auth").get_json(), {"enabled": False, "editor": False})
        self.assertEqual(self._sign_in().status_code, 503)
        res = self._post("/api/events", _fields())
        self.assertEqual(res.status_code, 403)
        self.assertIn("turned off", res.get_json()["error"])
        res = self._post("/api/events/" + "a" * 16, _fields(), method="put")
        self.assertIn("EventsPasscode", res.get_json()["error"])

    def test_missing_config_file_turns_editing_off(self) -> None:
        os.remove(self.config_path)
        self.assertEqual(self.client.get("/api/events/auth").get_json()["enabled"], False)

    def test_session_cookie_is_samesite_lax(self) -> None:
        res = self._sign_in(client=self.server._app.test_client())
        self.assertIn("SameSite=Lax", res.headers.get("Set-Cookie", ""))


class EventsReviewTests(_EventsServerCase):
    """Visitors submit events; they stay hidden until an organizer approves them."""

    def _submit(self, visitor, **overrides):
        return visitor.post("/api/events", data=_fields(**overrides), content_type="multipart/form-data")

    def _pending_id(self, name: str) -> str:
        events: list = self.client.get("/api/events").get_json()["events"]
        return next(e["id"] for e in events if e["name"] == name)

    def test_organizer_events_are_approved_immediately(self) -> None:
        ev: dict = self._post("/api/events", _fields()).get_json()
        self.assertTrue(ev["approved"])
        self.assertEqual(len(self._visitor().get("/api/events").get_json()["events"]), 1)

    def test_submission_is_pending_and_hidden(self) -> None:
        visitor = self._visitor()
        res = visitor.post("/api/events", data=dict(_fields(name="Visitor Picnic"), image=(io.BytesIO(PNG), "i.png")), content_type="multipart/form-data")
        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.get_json(), {"pending": True, "name": "Visitor Picnic"})
        # Hidden from visitors everywhere: list, detail, image, photos.
        self.assertEqual(visitor.get("/api/events").get_json()["events"], [])
        self.assertEqual(self._visitor().get("/api/events").get_json()["events"], [])
        event_id: str = self._pending_id("Visitor Picnic")
        self.assertEqual(visitor.get(f"/api/events/{event_id}").status_code, 404)
        self.assertEqual(visitor.get(f"/events/{event_id}/image/cover").status_code, 404)
        self.assertEqual(visitor.post(f"/api/events/{event_id}/photos", data={"photo": (io.BytesIO(JPEG), "p.jpg")}, content_type="multipart/form-data").status_code, 404)
        # Organizers see it flagged as pending, with its picture.
        ev: dict = self.client.get(f"/api/events/{event_id}").get_json()
        self.assertFalse(ev["approved"])
        self.assertEqual(self.client.get(f"/events/{event_id}/image/cover").data, PNG)

    def test_approve_publishes(self) -> None:
        visitor = self._visitor()
        self._submit(visitor, name="Visitor Picnic", start=_iso(-1), end=_iso(1))
        event_id: str = self._pending_id("Visitor Picnic")
        # Not even organizers can add photos before approval.
        res = self._post(f"/api/events/{event_id}/photos", {}, {"photo": [JPEG]})
        self.assertEqual(res.status_code, 409)
        # Visitors can't approve.
        res = visitor.post(f"/api/events/{event_id}/approve")
        self.assertEqual(res.status_code, 403)
        res = self.client.post(f"/api/events/{event_id}/approve")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["approved"])
        self.assertEqual([e["name"] for e in visitor.get("/api/events").get_json()["events"]], ["Visitor Picnic"])
        self.assertEqual(visitor.post(f"/api/events/{event_id}/photos", data={"photo": (io.BytesIO(JPEG), "p.jpg")}, content_type="multipart/form-data").status_code, 201)
        self.assertEqual(self.client.post("/api/events/" + "a" * 16 + "/approve").status_code, 404)

    def test_editing_keeps_approval_state(self) -> None:
        self._submit(self._visitor(), name="Visitor Picnic")
        event_id: str = self._pending_id("Visitor Picnic")
        res = self._post(f"/api/events/{event_id}", _fields(name="Visitor Picnic (fixed)"), method="put")
        self.assertFalse(res.get_json()["approved"], "editing a submission does not publish it")
        self.assertEqual(self._visitor().get("/api/events").get_json()["events"], [])

    def test_organizer_can_reject_by_deleting(self) -> None:
        self._submit(self._visitor(), name="Spam", image=(io.BytesIO(PNG), "i.png"))
        event_id: str = self._pending_id("Spam")
        self.assertEqual(self.client.delete(f"/api/events/{event_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/events").get_json()["events"], [])

    def test_submission_validation_errors_still_reported(self) -> None:
        res = self._submit(self._visitor(), name="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.get_json()["fields"])

    def test_submissions_are_rate_limited(self) -> None:
        visitor = self._visitor()
        for i in range(5):
            self.assertEqual(self._submit(visitor, name=f"E{i}").status_code, 202)
        res = self._submit(visitor, name="E6")
        self.assertEqual(res.status_code, 429)
        self.assertIn("Too many", res.get_json()["error"])
        # Organizers are not limited.
        self.assertEqual(self._post("/api/events", _fields()).status_code, 201)

    def test_unreviewed_submission_is_deleted_once_it_ends(self) -> None:
        visitor = self._visitor()
        self._submit(visitor, name="Never Reviewed", start=_iso(1), end=_iso(2), image=(io.BytesIO(PNG), "i.png"))
        self._submit(visitor, name="Approved Later", start=_iso(1), end=_iso(2))
        pending_id: str = self._pending_id("Never Reviewed")
        self.client.post(f"/api/events/{self._pending_id('Approved Later')}/approve")
        img_dir: str = os.path.join(self.dir, _EVENTS_SUBDIR, "images", pending_id)
        self.assertTrue(os.path.isdir(img_dir))
        store: EventStore = self.server._event_store
        later: datetime = datetime.now(timezone.utc) + timedelta(hours=3)
        names: list = [e["name"] for e in store.list_events(now=later)]
        self.assertEqual(names, ["Approved Later"], "approved event kept in history, submission gone")
        self.assertFalse(os.path.exists(img_dir), "its picture is deleted too")
        self.assertIsNone(store.get(pending_id, now=later))
        self.assertEqual(store.get(self._pending_id("Approved Later"), now=later)["status"], "past")

    def test_cannot_submit_an_event_that_already_ended(self) -> None:
        res = self._submit(self._visitor(), name="Yesterday", start=_iso(-5), end=_iso(-4))
        self.assertEqual(res.status_code, 400)
        self.assertIn("end", res.get_json()["fields"])
        # Organizers can still record past events.
        self.assertEqual(self._post("/api/events", _fields(start=_iso(-5), end=_iso(-4))).status_code, 201)

    def test_old_events_without_flag_count_as_approved(self) -> None:
        self.assertTrue(EventStore.is_approved({"id": "x"}))
        self.assertFalse(EventStore.is_approved({"id": "x", "approved": False}))


class CalendarFileTests(_EventsServerCase):
    """'Add to calendar': the .ics download (Google/Outlook links are built in the browser)."""

    def _unfold(self, text: str) -> str:
        return text.replace("\r\n ", "")

    def test_ics_contents(self) -> None:
        ev: dict = self._post("/api/events", _fields(
            name="Mesh Meetup; Radios, Antennas",
            start="2026-12-05T23:00:00Z", end="2026-12-06T01:30:00Z",
            description="Line one\nBring coax, connectors; snacks \\ drinks",
        )).get_json()
        res = self._visitor().get(f"/events/{ev['id']}/calendar.ics")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "text/calendar")
        self.assertIn('attachment; filename="Mesh-Meetup-Radios-Antennas.ics"', res.headers["Content-Disposition"])
        raw: str = res.get_data(as_text=True)
        self.assertTrue(raw.startswith("BEGIN:VCALENDAR\r\n") and raw.endswith("END:VCALENDAR\r\n"))
        self.assertNotIn("\n", raw.replace("\r\n", ""), "only CRLF line endings")
        for line in raw.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)
        text: str = self._unfold(raw)
        self.assertIn("DTSTART:20261205T230000Z\r\n", text)
        self.assertIn("DTEND:20261206T013000Z\r\n", text)
        self.assertIn(f"UID:{ev['id']}@meshbot-events\r\n", text)
        self.assertIn("SUMMARY:Mesh Meetup\\; Radios\\, Antennas\r\n", text)
        self.assertIn("LOCATION:1 Main St\\, Dayton\\, OH\r\n", text)
        self.assertIn("Line one\\nBring coax\\, connectors\\; snacks \\\\ drinks", text)
        self.assertIn("Website: https://example.com", text)
        self.assertIn(f"URL:http://localhost/events?id={ev['id']}\r\n", text)

    def test_online_event_uses_meeting_link(self) -> None:
        ev: dict = self._post("/api/events", _fields(location_type="online", location_link="https://meet.example.com/net")).get_json()
        text: str = self._unfold(self.client.get(f"/events/{ev['id']}/calendar.ics").get_data(as_text=True))
        self.assertIn("LOCATION:https://meet.example.com/net\r\n", text)
        self.assertIn("Join online: https://meet.example.com/net", text)

    def test_long_unicode_lines_are_folded_safely(self) -> None:
        ics: str = build_ics({"id": "abcdef1234", "name": "🎉 Événement " * 20, "start": "2026-12-05T23:00:00Z", "end": "2026-12-06T01:00:00Z"}, "http://x/events?id=abcdef1234")
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertIn("SUMMARY:" + "🎉 Événement " * 20, self._unfold(ics))

    def test_pending_and_unknown_events_are_not_downloadable(self) -> None:
        visitor = self._visitor()
        visitor.post("/api/events", data=_fields(name="Pending One"), content_type="multipart/form-data")
        pending_id: str = next(e["id"] for e in self.client.get("/api/events").get_json()["events"] if e["name"] == "Pending One")
        self.assertEqual(visitor.get(f"/events/{pending_id}/calendar.ics").status_code, 404)
        self.assertEqual(self.client.get(f"/events/{pending_id}/calendar.ics").status_code, 200)
        self.assertEqual(visitor.get("/events/" + "a" * 16 + "/calendar.ics").status_code, 404)
        self.assertEqual(visitor.get("/events/..%2F..%2Fx/calendar.ics").status_code, 404)


class AllDayEventTests(_EventsServerCase):
    """All-day events: dates instead of times, midnight to midnight."""

    def _all_day(self, first: str, last: str, **extra) -> dict:
        values: dict = {"start": "", "end": ""}
        values.update(extra)
        return _fields(all_day="1", start_day=first, end_day=last, **values)

    def test_validation_keeps_dates_and_spans_midnight_to_midnight(self) -> None:
        clean, errors = EventStore.validate(self._all_day("2026-12-05", "2026-12-06"))
        self.assertEqual(errors, {})
        self.assertTrue(clean["all_day"])
        self.assertEqual((clean["start_day"], clean["end_day"]), ("2026-12-05", "2026-12-06"))
        # Without browser times, falls back to UTC midnights; the end is the
        # midnight after the last day.
        self.assertEqual((clean["start"], clean["end"]), ("2026-12-05T00:00:00Z", "2026-12-07T00:00:00Z"))

    def test_browser_local_midnights_are_kept(self) -> None:
        clean, errors = EventStore.validate(self._all_day("2026-12-05", "2026-12-05", start="2026-12-05T05:00:00Z", end="2026-12-06T05:00:00Z"))
        self.assertEqual(errors, {})
        self.assertEqual((clean["start"], clean["end"]), ("2026-12-05T05:00:00Z", "2026-12-06T05:00:00Z"))

    def test_bad_dates_are_rejected(self) -> None:
        _, errors = EventStore.validate(self._all_day("2026-12-06", "2026-12-05"))
        self.assertIn("end", errors)
        _, errors = EventStore.validate(self._all_day("", "2026-12-05"))
        self.assertEqual(errors.get("start"), "Start date is required.")
        _, errors = EventStore.validate(self._all_day("2026-02-30", "2026-03-01"))
        self.assertIn("start", errors)

    def test_timed_events_are_unchanged(self) -> None:
        clean, errors = EventStore.validate(_fields(start_day="2026-12-05", end_day="2026-12-06"))
        self.assertEqual(errors, {})
        self.assertFalse(clean["all_day"])
        self.assertEqual((clean["start_day"], clean["end_day"]), ("", ""))

    def test_saved_and_switched_back(self) -> None:
        ev: dict = self._post("/api/events", self._all_day("2026-12-05", "2026-12-06")).get_json()
        self.assertTrue(ev["all_day"])
        self.assertEqual(self.client.get(f"/api/events/{ev['id']}").get_json()["end_day"], "2026-12-06")
        timed: dict = self._post(f"/api/events/{ev['id']}", _fields(start="2026-12-05T18:00:00Z", end="2026-12-05T20:00:00Z"), method="put").get_json()
        self.assertFalse(timed["all_day"])
        self.assertEqual(timed["start_day"], "")

    def test_calendar_file_uses_date_values(self) -> None:
        ev: dict = self._post("/api/events", self._all_day("2026-12-31", "2027-01-01")).get_json()
        text: str = self.client.get(f"/events/{ev['id']}/calendar.ics").get_data(as_text=True)
        self.assertIn("DTSTART;VALUE=DATE:20261231\r\n", text)
        self.assertIn("DTEND;VALUE=DATE:20270102\r\n", text)
        self.assertNotIn("DTSTART:", text)

    def test_visitors_can_submit_all_day_events_for_today(self) -> None:
        today: str = datetime.now(timezone.utc).date().isoformat()
        res = self._visitor().post("/api/events", data=self._all_day(today, today), content_type="multipart/form-data")
        self.assertEqual(res.status_code, 202)


class RecurringEventTests(_EventsServerCase):
    """Repeating events: weekly, every other week, monthly, yearly."""

    NY: str = "America/New_York"

    def _repeat(self, recurrence: str, start: str, end: str, **extra) -> dict:
        return _fields(recurrence=recurrence, start=start, end=end, tz=self.NY, **extra)

    def _clean(self, **kw) -> dict:
        clean, errors = EventStore.validate(self._repeat(**kw))
        self.assertEqual(errors, {})
        return clean

    @staticmethod
    def _starts(event: dict, count: int) -> list[str]:
        result: list[str] = []
        for start, _ in occurrences(event):
            result.append(EventStore.format_time(start))
            if len(result) == count:
                break
        return result

    # ── validation ──
    def test_validation_stores_repeat_fields(self) -> None:
        clean = self._clean(recurrence="biweekly", start="2026-12-03T00:00:00Z", end="2026-12-03T02:00:00Z", repeat_until="2027-03-01")
        self.assertEqual((clean["recurrence"], clean["repeat_until"], clean["tz"]), ("biweekly", "2027-03-01", self.NY))
        clean, errors = EventStore.validate(_fields(recurrence="", repeat_until="2027-03-01"))
        self.assertEqual(errors, {})
        self.assertEqual((clean["recurrence"], clean["repeat_until"]), ("", ""), "no repeat → no end date kept")

    def test_validation_rejects_bad_values(self) -> None:
        _, errors = EventStore.validate(_fields(recurrence="daily"))
        self.assertIn("recurrence", errors)
        _, errors = EventStore.validate(self._repeat("weekly", "2026-12-03T00:00:00Z", "2026-12-03T02:00:00Z", repeat_until="2026-12-01"))
        self.assertIn("repeat_until", errors)
        _, errors = EventStore.validate(self._repeat("weekly", "2026-12-03T00:00:00Z", "2026-12-03T02:00:00Z", repeat_until="2026-13-01"))
        self.assertIn("repeat_until", errors)
        clean, errors = EventStore.validate(_fields(recurrence="weekly", tz="Not/AZone"))
        self.assertEqual((errors, clean["tz"]), ({}, ""), "unknown time zone is dropped, not an error")

    # ── occurrences ──
    def test_weekly_keeps_local_time_across_daylight_saving(self) -> None:
        # Thursdays 7 PM New York: 00:00Z in winter (EST), 23:00Z in summer (EDT).
        ev = self._clean(recurrence="weekly", start="2027-03-05T00:00:00Z", end="2027-03-05T02:00:00Z")
        self.assertEqual(self._starts(ev, 3), ["2027-03-05T00:00:00Z", "2027-03-12T00:00:00Z", "2027-03-18T23:00:00Z"])

    def test_biweekly_is_every_14_days(self) -> None:
        ev = self._clean(recurrence="biweekly", start="2026-12-03T00:00:00Z", end="2026-12-03T02:00:00Z")
        self.assertEqual(self._starts(ev, 3), ["2026-12-03T00:00:00Z", "2026-12-17T00:00:00Z", "2026-12-31T00:00:00Z"])

    def test_monthly_on_the_31st_skips_short_months(self) -> None:
        ev = self._clean(recurrence="monthly", start="2027-01-31T17:00:00Z", end="2027-01-31T18:00:00Z")
        days: list[str] = [s[:10] for s in self._starts(ev, 4)]
        self.assertEqual(days, ["2027-01-31", "2027-03-31", "2027-05-31", "2027-07-31"])

    def test_yearly_on_feb_29_only_in_leap_years(self) -> None:
        ev = self._clean(recurrence="yearly", start="2028-02-29T17:00:00Z", end="2028-02-29T18:00:00Z")
        self.assertEqual([s[:10] for s in self._starts(ev, 2)], ["2028-02-29", "2032-02-29"])

    def test_until_is_inclusive(self) -> None:
        ev = self._clean(recurrence="weekly", start="2026-12-03T00:00:00Z", end="2026-12-03T02:00:00Z", repeat_until="2026-12-16")
        # Local dates Dec 2, 9, 16 (7 PM New York) — the 16th is included.
        self.assertEqual(len(list(occurrences(ev))), 3)

    def test_all_day_repeats_keep_their_dates(self) -> None:
        ev = self._clean(recurrence="monthly", start="", end="", all_day="1", start_day="2026-12-05", end_day="2026-12-06")
        spans = [(EventStore.format_time(s), EventStore.format_time(e)) for s, e in list(occurrences(ev))[:2]]
        self.assertEqual(spans, [("2026-12-05T05:00:00Z", "2026-12-07T05:00:00Z"), ("2027-01-05T05:00:00Z", "2027-01-07T05:00:00Z")])

    # ── status, archiving, photos ──
    def test_status_follows_the_current_or_next_date(self) -> None:
        ev = self._clean(recurrence="weekly", start="2026-11-05T00:00:00Z", end="2026-11-05T02:00:00Z")
        during = EventStore.with_status(ev, datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc))
        self.assertEqual((during["status"], during["occurrence_start"]), ("active", "2026-11-26T00:00:00Z"))
        between = EventStore.with_status(ev, datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc))
        self.assertEqual((between["status"], between["occurrence_start"]), ("upcoming", "2026-12-03T00:00:00Z"))
        ended = dict(ev, repeat_until="2026-11-19")
        after = EventStore.with_status(ended, datetime(2026, 11, 27, tzinfo=timezone.utc))
        self.assertEqual((after["status"], after["occurrence_start"]), ("past", "2026-11-19T00:00:00Z"))

    def test_repeating_event_stays_current_until_its_last_date(self) -> None:
        open_ended: dict = self._post("/api/events", self._repeat("weekly", _iso(-24 * 20), _iso(-24 * 20 + 2))).get_json()
        finished: dict = self._post("/api/events", self._repeat("weekly", _iso(-24 * 30), _iso(-24 * 30 + 2), repeat_until=(datetime.now(timezone.utc) - timedelta(days=9)).date().isoformat())).get_json()
        self.assertEqual(open_ended["status"], "upcoming")
        self.assertEqual(finished["status"], "past")
        with open(os.path.join(self.dir, _EVENTS_SUBDIR, _EVENTS_HISTORY_FILE), encoding="utf-8") as f:
            history_raw: str = f.read()
        current: list = self.server._event_store._read_file(_EVENTS_FILE)
        self.assertEqual([e["id"] for e in current], [open_ended["id"]])
        self.assertTrue(history_raw)

    def test_photos_can_be_added_during_a_later_date(self) -> None:
        # First date a week ago; today's repeat is happening now.
        ev: dict = self._post("/api/events", self._repeat("weekly", _iso(-24 * 7 - 1), _iso(-24 * 7 + 2))).get_json()
        self.assertEqual(ev["status"], "active")
        res = self._visitor().post(f"/api/events/{ev['id']}/photos", data={"photo": (io.BytesIO(JPEG), "p.jpg")}, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 201)

    def test_visitors_can_submit_a_series_that_is_still_going(self) -> None:
        visitor = self._visitor()
        going = visitor.post("/api/events", data=self._repeat("monthly", _iso(-24 * 40), _iso(-24 * 40 + 2)), content_type="multipart/form-data")
        self.assertEqual(going.status_code, 202)
        done = visitor.post("/api/events", data=self._repeat("weekly", _iso(-24 * 40), _iso(-24 * 40 + 2), repeat_until=(datetime.now(timezone.utc) - timedelta(days=20)).date().isoformat()), content_type="multipart/form-data")
        self.assertEqual(done.status_code, 400)

    # ── calendar file ──
    def test_calendar_file_has_rrule_and_time_zone(self) -> None:
        ev: dict = self._post("/api/events", self._repeat("biweekly", "2026-12-04T00:00:00Z", "2026-12-04T02:00:00Z", repeat_until="2027-02-25")).get_json()
        text: str = self.client.get(f"/events/{ev['id']}/calendar.ics").get_data(as_text=True).replace("\r\n ", "")
        self.assertIn("DTSTART;TZID=America/New_York:20261203T190000\r\n", text)
        self.assertIn("DTEND;TZID=America/New_York:20261203T210000\r\n", text)
        self.assertIn("RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20270226T045959Z\r\n", text)

    def test_calendar_file_all_day_repeat(self) -> None:
        ev: dict = self._post("/api/events", _fields(recurrence="yearly", all_day="1", start_day="2026-12-25", end_day="2026-12-25", start="", end="", repeat_until="2030-12-25")).get_json()
        text: str = self.client.get(f"/events/{ev['id']}/calendar.ics").get_data(as_text=True)
        self.assertIn("DTSTART;VALUE=DATE:20261225\r\n", text)
        self.assertIn("RRULE:FREQ=YEARLY;UNTIL=20301225\r\n", text)

    def test_one_off_events_are_unchanged(self) -> None:
        ev: dict = self._post("/api/events", _fields()).get_json()
        self.assertEqual((ev["recurrence"], ev["occurrence_start"]), ("", ev["start"]))
        text: str = self.client.get(f"/events/{ev['id']}/calendar.ics").get_data(as_text=True)
        self.assertNotIn("RRULE", text)


if __name__ == "__main__":
    unittest.main()
