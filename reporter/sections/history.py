"""One thing that happened on this day. From Wikipedia's selected anniversaries (CC BY-SA)."""

import re
from datetime import datetime
from typing import NamedTuple, Optional

from PIL import Image

from .. import http
from ..blocks import titled
from ..render import RIGHT, Canvas, clean, font, line_height, wrap

URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{month:02d}/{day:02d}"
LONGEST, MOST = 170, 8  # letters, lines
ASIDE, PICTURED = re.compile(r" ?\(([^()]*)\)"), re.compile(r"pictured|depicted|shown")
# Not over breakfast, if there is anything else.
GRIM = re.compile(r"\b(kill|massacre|murder|assassin|holocaust|genocide|execut(ed|ion)|bomb|crash|earthquake|casualt|shot\b|death|dead|die[ds]\b|attack|terror|"
                  r"torpedo|hanged|suicide|explosi|explode|famine|plague|tsunami|rape[ds]?\b|slave|shooting|stabb|wars?\b|battles?\b|nazi)", re.IGNORECASE)


class Moment(NamedTuple):
    year: int
    text: str


def parse(payload, year: int) -> Moment:
    """A different one each year."""
    moments = []
    for entry in payload["selected"]:
        text = ASIDE.sub(lambda m: "" if PICTURED.search(m[1]) else m[0], clean(str(entry.get("text") or "")))
        if text and isinstance(entry.get("year"), int):
            moments.append(Moment(entry["year"], text))
    short = [m for m in moments if len(m.text) <= LONGEST]
    best = [m for m in short if not GRIM.search(m.text)] or short or moments
    if not best:
        raise RuntimeError("nothing for this day")
    return best[year % len(best)]


def fetch(cfg, session, now: datetime) -> Moment:
    return parse(http.get(session, URL.format(month=now.month, day=now.day)).json(), now.year)


def render(data: Moment, now: datetime) -> Optional[Image.Image]:
    canvas = Canvas()
    year = f"{-data.year} BC" if data.year < 0 else data.year
    left, strong, body = titled(canvas, "On this day", "hourglass"), font("bold", 22), font("semibold", 21)
    canvas.text(left, canvas.y, str(year), strong)
    canvas.y += line_height(strong)
    for line in wrap(data.text, body, RIGHT - left, MOST):
        canvas.text(left, canvas.y, line, body)
        canvas.y += line_height(body)
    canvas.y += 6
    return canvas.finish()
