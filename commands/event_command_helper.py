from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common.constants import (
    _EVENT_CMD_ALL_DAY,
    _EVENT_CMD_DETAILS_HINT,
    _EVENT_CMD_ELLIPSIS,
    _EVENT_CMD_HORIZON_DAYS,
    _EVENT_CMD_LIST_HEADER,
    _EVENT_CMD_LIST_HINT,
    _EVENT_CMD_LIST_LIMIT,
    _EVENT_CMD_MAX_PARTS,
    _EVENT_CMD_NEXT_LABEL,
    _EVENT_CMD_NONE,
    _EVENT_CMD_NOT_FOUND_INDEX,
    _EVENT_CMD_NOT_FOUND_NAME,
    _EVENT_CMD_NOW_LABEL,
    _EVENT_CMD_OCCURRENCE_SCAN,
    _EVENT_CMD_ONLINE,
    _EVENT_CMD_SEARCH_LIMIT,
    _EVENT_CMD_UNAVAILABLE,
    _EVENTS_LOCATION_ONLINE,
    _EVENTS_RECURRENCE_LABELS,
    _EVENTS_STATUS_ACTIVE,
    _MESH_MAX_MESSAGE_CHARS,
)
from web.event_store import EventStore, EventStoreError, upcoming_occurrences


def fit_bytes(text: str, limit: int = _MESH_MAX_MESSAGE_CHARS) -> str:
    """Cuts *text* so its UTF-8 form fits in *limit* bytes, ending with an ellipsis if cut.

    Meshtastic limits the payload in bytes, so emoji or accented letters count
    for more than one.
    """
    result: str = text
    if len(text.encode("utf-8")) > limit:
        room: int = limit - len(_EVENT_CMD_ELLIPSIS.encode("utf-8"))
        cut: str = text.encode("utf-8")[:room].decode("utf-8", errors="ignore")
        result = cut.rstrip() + _EVENT_CMD_ELLIPSIS
    return result


def split_message(text: str, limit: int = _MESH_MAX_MESSAGE_CHARS, max_parts: int = _EVENT_CMD_MAX_PARTS) -> list[str]:
    """Splits *text* into mesh-sized parts, breaking at line ends, then spaces.

    When more than one part is needed each starts with ``i/n``. Text beyond
    *max_parts* is dropped and the last part ends with an ellipsis.
    """
    def nbytes(s: str) -> int:
        return len(s.encode("utf-8"))

    # Room for a "5/5 " prefix when the text has to be split.
    prefix_room: int = len(f"{max_parts}/{max_parts} ")
    room: int = limit if nbytes(text) <= limit else limit - prefix_room
    chunks: list[str] = []
    rest: str = text.strip()
    while rest and len(chunks) < max_parts:
        if nbytes(rest) <= room:
            chunks.append(rest)
            rest = ""
            break
        head: str = rest.encode("utf-8")[:room].decode("utf-8", errors="ignore")
        cut: int = head.rfind("\n")
        if cut < room // 3:
            cut = head.rfind(" ")
        if cut < room // 3:
            cut = len(head)
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest and chunks:
        chunks[-1] = fit_bytes(chunks[-1] + " " + rest, room)
    if len(chunks) > 1:
        chunks = [f"{i}/{len(chunks)} {c}" for i, c in enumerate(chunks, 1)]
    return chunks


class EventCommandHelper:
    """Builds the replies for the mesh ``!event``, ``!events`` and ``!eventinfo`` commands.

    Reads the published (approved) events from the dashboard's event store and
    turns them into short, mesh-sized text. Performs no radio sends, so the web
    DM page and the radio handlers share the same output.
    """

    # region Protected Variables
    _store: EventStore | None
    _local_zone: tzinfo
    # endregion Protected Variables

    # region Constructor
    def __init__(self, store: EventStore | None, local_zone: tzinfo | None = None) -> None:
        """Initialises the helper.

        Args:
            store: The event store to read, or ``None`` when events are unavailable.
            local_zone: Zone used for events saved without one. Defaults to the
                        computer's own time zone.
        """
        self._store = store
        self._local_zone = local_zone or datetime.now().astimezone().tzinfo or timezone.utc
    # endregion Constructor

    # region Protected Functions
    def _zone(self, event: dict) -> tzinfo:
        """The event's own time zone, else the local one."""
        result: tzinfo = self._local_zone
        name: str = str(event.get("tz", "") or "")
        if name:
            try:
                result = ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return result

    @staticmethod
    def _clock(moment: datetime) -> str:
        """``7PM`` or ``7:30PM``."""
        hour: int = moment.hour % 12 or 12
        minutes: str = f":{moment.minute:02d}" if moment.minute else ""
        return f"{hour}{minutes}{'AM' if moment.hour < 12 else 'PM'}"

    @staticmethod
    def _day_long(day: date) -> str:
        """``Sat Nov 28``."""
        return f"{day:%a %b} {day.day}"

    @staticmethod
    def _day_short(day: date) -> str:
        """``Sat 11/28``."""
        return f"{day:%a} {day.month}/{day.day}"

    def _upcoming(self, now: datetime, limit: int) -> tuple[list[dict], dict[str, dict]] | None:
        """Each event's next date (happening-now first, then soonest), up to *limit*,
        plus the events by id; None if unreadable. A repeating event appears
        once, so it can't crowd the others out of the list."""
        result: tuple[list[dict], dict[str, dict]] | None = None
        if self._store is not None:
            try:
                events: list[dict] = self._store.published_events(now)
                seen: set[str] = set()
                items: list[dict] = []
                for item in upcoming_occurrences(events, now, _EVENT_CMD_HORIZON_DAYS, _EVENT_CMD_OCCURRENCE_SCAN):
                    event_id: str = str(item.get("id", ""))
                    if event_id not in seen:
                        seen.add(event_id)
                        items.append(item)
                result = (items[:limit], {str(e.get("id", "")): e for e in events})
            except (EventStoreError, OSError):
                result = None
        return result

    def _when(self, item: dict, event: dict, short: bool) -> str:
        """When an occurrence is, in the event's own time zone."""
        day_fmt = self._day_short if short else self._day_long
        text: str
        if item.get("all_day"):
            first: date | None = EventStore.parse_day(item.get("first_day", ""))
            last: date | None = EventStore.parse_day(item.get("last_day", ""))
            if first is None:
                text = _EVENT_CMD_ALL_DAY
            elif last is None or last == first:
                text = day_fmt(first) if short else f"{day_fmt(first)} ({_EVENT_CMD_ALL_DAY})"
            else:
                text = f"{day_fmt(first)}-{day_fmt(last)}"
        else:
            zone: tzinfo = self._zone(event)
            start: datetime | None = EventStore.parse_time(item.get("start", ""))
            end: datetime | None = EventStore.parse_time(item.get("end", ""))
            if start is None:
                text = ""
            else:
                local_start: datetime = start.astimezone(zone)
                text = f"{day_fmt(local_start.date())} {self._clock(local_start)}"
                if not short and end is not None and end > start:
                    local_end: datetime = end.astimezone(zone)
                    if local_end.date() == local_start.date():
                        text += f"-{self._clock(local_end)}"
                    else:
                        text += f" to {day_fmt(local_end.date())} {self._clock(local_end)}"
        return text

    @staticmethod
    def _where(event: dict) -> str:
        """The address, ``Online``, or empty."""
        location: dict = event.get("location") or {}
        result: str = str(location.get("address", "") or "").strip()
        if location.get("type") == _EVENTS_LOCATION_ONLINE:
            result = _EVENT_CMD_ONLINE
        return result

    def _find(self, params: str, now: datetime) -> tuple[dict | None, dict | None, str]:
        """Resolves ``!eventinfo`` params to (occurrence, event, error)."""
        query: str = params.strip()
        found: tuple[list[dict], dict[str, dict]] | None = self._upcoming(now, _EVENT_CMD_SEARCH_LIMIT)
        item: dict | None = None
        event: dict | None = None
        error: str = ""
        if found is None:
            error = _EVENT_CMD_UNAVAILABLE
        else:
            items, by_id = found
            if not items:
                error = _EVENT_CMD_NONE
            elif not query or query.lstrip("#").isdigit():
                index: int = int(query.lstrip("#")) if query else 1
                if 1 <= index <= len(items):
                    item = items[index - 1]
                else:
                    error = _EVENT_CMD_NOT_FOUND_INDEX.format(index=index)
            else:
                lowered: str = query.lower()
                item = next((i for i in items if lowered in str(i.get("name", "")).lower()), None)
                if item is None:
                    error = fit_bytes(_EVENT_CMD_NOT_FOUND_NAME.format(query=query[:40]))
            if item is not None:
                event = by_id.get(str(item.get("id", "")), {})
        return item, event, error
    # endregion Protected Functions

    # region Public Functions
    def compute_next(self, now: datetime | None = None) -> str:
        """The ``!event`` reply: the next (or happening-now) event's name, time and place."""
        moment: datetime = now or datetime.now(timezone.utc)
        found: tuple[list[dict], dict[str, dict]] | None = self._upcoming(moment, 1)
        result: str
        if found is None:
            result = _EVENT_CMD_UNAVAILABLE
        elif not found[0]:
            result = _EVENT_CMD_NONE
        else:
            item: dict = found[0][0]
            event: dict = found[1].get(str(item.get("id", "")), {})
            label: str = _EVENT_CMD_NOW_LABEL if item.get("status") == _EVENTS_STATUS_ACTIVE else _EVENT_CMD_NEXT_LABEL
            tail: list[str] = [self._when(item, event, short=False)]
            where: str = self._where(event)
            if where:
                tail.append(where)
            tail.append(_EVENT_CMD_DETAILS_HINT.format(index=1))
            tail_text: str = "\n" + "\n".join(t for t in tail if t)
            # Shorten the name first, then the address, so the hint always fits.
            head_room: int = _MESH_MAX_MESSAGE_CHARS - len(tail_text.encode("utf-8"))
            head: str = fit_bytes(label.format(name=item.get("name", "")), max(40, head_room))
            result = fit_bytes(head + tail_text)
        return result

    def compute_list(self, now: datetime | None = None) -> str:
        """The ``!events`` reply: a numbered list of the next few dates."""
        moment: datetime = now or datetime.now(timezone.utc)
        found: tuple[list[dict], dict[str, dict]] | None = self._upcoming(moment, _EVENT_CMD_LIST_LIMIT)
        result: str
        if found is None:
            result = _EVENT_CMD_UNAVAILABLE
        elif not found[0]:
            result = _EVENT_CMD_NONE
        else:
            items, by_id = found
            items = items[: max(_EVENT_CMD_LIST_LIMIT, 1)]
            footer: str = "\n" + _EVENT_CMD_LIST_HINT
            budget: int = _MESH_MAX_MESSAGE_CHARS - len((_EVENT_CMD_LIST_HEADER + footer).encode("utf-8"))
            per_line: int = max(30, budget // len(items))
            lines: list[str] = []
            used: int = 0
            for index, item in enumerate(items, 1):
                event: dict = by_id.get(str(item.get("id", "")), {})
                when: str = "Now" if item.get("status") == _EVENTS_STATUS_ACTIVE else self._when(item, event, short=True)
                line: str = "\n" + fit_bytes(f"{index}. {when} {item.get('name', '')}", per_line - 1)
                if used + len(line.encode("utf-8")) > budget:
                    break
                lines.append(line)
                used += len(line.encode("utf-8"))
            result = _EVENT_CMD_LIST_HEADER + "".join(lines) + footer
        return result

    def compute_details(self, params: str, now: datetime | None = None) -> list[str]:
        """The ``!eventinfo [N|name]`` reply, split into mesh-sized messages.

        ``N`` is the number from ``!events`` (no number = the next event); any
        other text picks the first upcoming event whose name contains it.
        """
        moment: datetime = now or datetime.now(timezone.utc)
        item, event, error = self._find(params, moment)
        result: list[str]
        if item is None or event is None:
            result = [error]
        else:
            lines: list[str] = [str(item.get("name", "")), "When: " + self._when(item, event, short=False)]
            recurrence: str = _EVENTS_RECURRENCE_LABELS.get(str(event.get("recurrence", "") or ""), "")
            if recurrence:
                lines.append("Repeats: " + recurrence)
            location: dict = event.get("location") or {}
            if location.get("type") == _EVENTS_LOCATION_ONLINE:
                link: str = str(location.get("link", "") or "")
                lines.append("Where: Online" + (f" {link}" if link else ""))
            elif location.get("address"):
                lines.append("Where: " + str(location["address"]))
            description: str = str(event.get("description", "") or "").strip()
            if description:
                lines.append(description)
            if event.get("website"):
                lines.append("Web: " + str(event["website"]))
            contact: dict = event.get("contact") or {}
            bits: list[str] = []
            if contact.get("name"):
                bits.append(str(contact["name"]))
            if contact.get("phone"):
                bits.append(str(contact["phone"]) + (" (call/text)" if contact.get("phone_texts") else ""))
            if contact.get("signal"):
                bits.append("Signal " + str(contact["signal"]))
            if bits:
                lines.append("Contact: " + ", ".join(bits))
            result = split_message("\n".join(lines))
        return result
    # endregion Public Functions
