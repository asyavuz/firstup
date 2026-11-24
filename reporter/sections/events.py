"""Today's calendar, as dropped off by a phone.

Received by deploy/receipt_inbox.py. The Pi never holds a calendar login or link, only
a short text for one day:

    2026-11-24
    09:30-10:00 Dentist
    All day Parents visiting

The first line is the day the list is for, so it can be sent the evening before.
Everything here treats the text as untrusted.
"""

import re
from datetime import date, datetime
from typing import List, NamedTuple, Optional

from PIL import Image

from .. import lists
from ..render import PAD, RIGHT, WIDTH, Canvas, clean, font, line_height, notice, wrap

MAX_EVENTS = 10
TITLE_X = 138

_TIMED = re.compile(r"^(\d{1,2}):(\d{2})(?:\s*[-–]\s*(\d{1,2}):(\d{2}))?\s+(.+)$")
_ALL_DAY = re.compile(r"^all[ -]day:?\s+(.+)$", re.IGNORECASE)


class Event(NamedTuple):
    sort: str
    when: str
    title: str


class Inbox(NamedTuple):
    received: bool
    events: List[Event]


def event(line: str) -> Event:
    timed = _TIMED.match(line)
    if timed:
        h1, m1, h2, m2, title = timed.groups()
        start = f"{int(h1):02d}:{m1}"
        return Event(start, f"{start}–{int(h2):02d}:{m2}" if h2 else start, title)
    all_day = _ALL_DAY.match(line)
    return Event("", "All day", all_day.group(1) if all_day else line)


def lines(text: str, today: date) -> Optional[List[str]]:
    """What a list says for today, or None if it is empty, malformed or for another day."""
    found = [line for line in (clean(raw) for raw in text.splitlines()) if line]
    try:
        return found[1:] if found and date.fromisoformat(found[0]) == today else None
    except ValueError:
        return None


def parse(text: str, today: date) -> Optional[List[Event]]:
    """The events for today, or None as above."""
    found = lines(text, today)
    return None if found is None else sorted(map(event, found), key=lambda e: e.sort)


def fetch(cfg, session, now: datetime) -> Optional[Inbox]:
    path, _ = lists.paths(cfg)
    if not path.parent.is_dir():
        return None  # not set up: the section is left out
    events = parse(lists.read(path) or "", now.date())
    return Inbox(events is not None, events or [])


def example() -> Inbox:
    """What a preview on a screen shows instead of the real calendar."""
    return Inbox(True, [Event("", "All day", "An all-day event"), Event("09:30", "09:30–10:00", "A timed event")])


def render(data: Optional[Inbox], now: datetime) -> Optional[Image.Image]:
    if data is None:
        return None
    if not data.received:
        return notice("Calendar not received")
    if not data.events:
        return notice("Nothing in your calendar today")
    canvas = Canvas()
    canvas.heading("Today")
    when_font, body = font("bold", 20), font("semibold", 20)
    for event in data.events[:MAX_EVENTS]:
        canvas.text(PAD, canvas.y, event.when, when_font)
        for line in wrap(event.title, body, RIGHT - TITLE_X, 2):
            canvas.text(TITLE_X, canvas.y, line, body)
            canvas.y += line_height(body)
        canvas.y += 5
    if len(data.events) > MAX_EVENTS:
        canvas.text(WIDTH / 2, canvas.y, f"and {len(data.events) - MAX_EVENTS} more", body, "ma")
        canvas.y += line_height(body) + 5
    return canvas.finish()
