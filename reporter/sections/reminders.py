"""Today's reminders, as dropped off by a phone in the same way as the calendar, and just as
private. One line each, with the day it is due if it has one:

    2026-11-24
    2026-11-24 09:30 Ring the dentist
    2026-11-24 00:00 Put the bins out
    Buy a bulb

Shortcuts writes 00:00 for a day without a time."""

import re
from datetime import date, datetime
from typing import List, NamedTuple, Optional, Tuple

from PIL import Image

from .. import lists
from ..render import PAD, RIGHT, WIDTH, Canvas, font, line_height, wrap
from . import events

MAX, BOX, TEXT_X = 12, 22, PAD + 36
_DUE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (.+)$")


class Item(NamedTuple):
    title: str
    due: str  # "overdue", a time, "today" or nothing


def _item(line: str, today: date) -> Optional[Tuple[tuple, Item]]:
    """With its place in the list. None if it is due later."""
    dated = _DUE.match(line)
    try:
        day = date.fromisoformat(dated[1]) if dated else None
    except ValueError:
        day = None  # part of the title after all
    if day and day > today:
        return None
    event = events.event(dated[2] if day else line)
    if day and day < today:
        return (0, day, event.sort), Item(event.title, "overdue")
    if event.when not in ("All day", "00:00"):
        return (1, today, event.sort), Item(event.title, event.when)
    due_today = day or event.when == "00:00"
    return (2 if due_today else 3, today, ""), Item(event.title, "today" if due_today else "")


def parse(text: str, today: date) -> List[Item]:
    found = [item for item in (_item(line, today) for line in events.lines(text, today) or []) if item]
    return [item for _, item in sorted(found, key=lambda placed: placed[0])]


def fetch(cfg, session, now: datetime) -> List[Item]:
    """Empty if none were sent: somebody who does not use this never sees it."""
    return parse(lists.read(lists.paths(cfg)[1]) or "", now.date())


def example() -> List[Item]:
    return [Item("A reminder for today", "today"), Item("One without a deadline", "")]


def render(data: List[Item], now: datetime) -> Optional[Image.Image]:
    if not data:
        return None
    canvas = Canvas()
    body, strong = font("semibold", 20), font("bold", 20)
    canvas.heading("To do")
    canvas.y += 2
    for item in data[:MAX]:
        canvas.draw.rounded_rectangle([PAD + 2, canvas.y + 2, PAD + 2 + BOX, canvas.y + 2 + BOX], 4, outline=0, width=3)
        canvas.text(RIGHT, canvas.y, item.due, strong, "ra")
        room = RIGHT - TEXT_X - (strong.getlength(item.due) + 12 if item.due else 0)
        for line in wrap(item.title, body, room, 2):
            canvas.text(TEXT_X, canvas.y, line, body)
            canvas.y += line_height(body)
        canvas.y += 6
    if len(data) > MAX:
        canvas.text(WIDTH / 2, canvas.y, f"and {len(data) - MAX} more", body, "ma")
        canvas.y += line_height(body) + 4
    return canvas.finish()
