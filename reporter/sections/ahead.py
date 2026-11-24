"""Bank holidays and clock changes, a few days before. Holidays: gov.uk."""

from datetime import date, datetime, timedelta
from typing import List, NamedTuple, Optional

from PIL import Image

from .. import http
from ..blocks import block
from ..render import Canvas, clean

URL = "https://www.gov.uk/bank-holidays.json"
HOLIDAY_DAYS, CLOCK_DAYS = 7, 3


class Notice(NamedTuple):
    picture: str
    strong: str
    detail: str


def _when(day: date, today: date) -> str:
    ahead = (day - today).days
    return "Today" if ahead == 0 else "Tomorrow" if ahead == 1 else f"{day:%A} {day.day} {day:%B}"


def clock_change(now: datetime) -> Optional[Notice]:
    """Found from the time zone itself, so it is right wherever the printer is."""
    today = now.date()
    for ahead in range(CLOCK_DAYS + 1):
        day = today + timedelta(days=ahead)
        before, after = (datetime(d.year, d.month, d.day, 12, tzinfo=now.tzinfo).utcoffset() for d in (day - timedelta(days=1), day))
        if before != after:
            back = after < before
            return Notice("clock", f"Clocks go {'back' if back else 'forward'}", f"{_when(day, today)}, an hour {'more' if back else 'less'} in bed")
    return None


def holidays(payload, today: date) -> List[Notice]:
    found = []
    for event in payload["england-and-wales"]["events"]:
        day = date.fromisoformat(event["date"])
        if 0 <= (day - today).days <= HOLIDAY_DAYS:
            name = clean(str(event.get("title") or "Bank holiday"))
            instead = "substitute" in str(event.get("notes") or "").lower()
            found.append(Notice("calendar", f"Bank holiday for {name}" if instead else name if "holiday" in name.lower() else f"{name}, bank holiday", _when(day, today)))
    return found


def fetch(cfg, session, now: datetime) -> List[Notice]:
    change = clock_change(now)
    try:
        found = holidays(http.get(session, URL).json(), now.date())
    except Exception:
        if change is None:
            raise
        found = []  # the clocks matter more than a site that is down
    return ([change] if change else []) + found


def render(data: List[Notice], now: datetime) -> Optional[Image.Image]:
    if not data:
        return None
    canvas = Canvas()
    for notice in data[:3]:
        block(canvas, notice.picture, notice.strong, [notice.detail])
    return canvas.finish()
