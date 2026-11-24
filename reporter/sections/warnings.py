"""Met Office weather warnings for one region, when there are any."""

import re
from datetime import datetime
from typing import List, NamedTuple, Optional

from PIL import Image

from .. import feeds, http
from ..blocks import block
from ..render import RIGHT, WIDTH, Canvas, font, icon, line_height

URL = "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/{region}"
MAX, ICON = 3, 40
LEVELS = ("red", "amber", "yellow")
_TITLE = re.compile(r"^(Yellow|Amber|Red) warnings? (?:of|for) (.+?) affecting", re.IGNORECASE)
_TIMES = re.compile(r"valid from (\d\d)(\d\d) (\w{3} \d{1,2}) \w{3} to (\d\d)(\d\d) (\w{3} \d{1,2}) \w{3}")
_ICONS = (("thunder", "wi-thunderstorm"), ("lightning", "wi-lightning"), ("snow", "wi-snow"), ("ice", "wi-snowflake-cold"), ("rain", "wi-umbrella"),
          ("wind", "wi-strong-wind"), ("fog", "wi-fog"), ("heat", "wi-hot"))


class Alert(NamedTuple):
    strong: str
    times: str
    icon: str  # "" when there is none for it


class Alerts(NamedTuple):
    worst: List[Alert]
    more: int  # how many others there are


def parse(content: bytes) -> Alerts:
    """The worst ones first, then in the feed's order."""
    found = []
    for item in feeds.items(content, ("title", "description")):
        title, times = _TITLE.match(item["title"]), _TIMES.search(item.get("description", ""))
        kind = title[2].lower() if title else ""
        strong = f"{title[1].capitalize()} warning: {kind}" if title else item["title"]
        picture = next((f"{name}.svg.png" for word, name in _ICONS if word in kind), "")
        span = f"{times[3]}, {times[1]}:{times[2]} to " + ("" if times[6] == times[3] else f"{times[6]}, ") + f"{times[4]}:{times[5]}" if times else ""
        level = LEVELS.index(title[1].lower()) if title else len(LEVELS)
        found.append((level, Alert(strong, span, picture)))
    worst = [alert for _, alert in sorted(found, key=lambda pair: pair[0])]
    return Alerts(worst[:MAX], len(worst[MAX:]))


def fetch(cfg, session, now: datetime) -> Alerts:
    return parse(http.get(session, URL.format(region=cfg.warnings.region)).content)


def render(data: Alerts, now: datetime) -> Optional[Image.Image]:
    if not data.worst:
        return None
    canvas = Canvas()
    for alert in data.worst:
        top = canvas.y
        picture = icon(alert.icon, ICON) if alert.icon else None
        block(canvas, "warning", alert.strong, [alert.times] if alert.times else [], right=RIGHT - ICON - 8 if picture else RIGHT)
        if picture:
            canvas.icon_centred(picture, RIGHT - ICON / 2, top + 32)
    if data.more:
        small = font("semibold", 20)
        canvas.text(WIDTH / 2, canvas.y, f"and {data.more} more", small, "ma")
        canvas.y += line_height(small) + 4
    return canvas.finish()
