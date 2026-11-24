"""On Fridays: what TfL is closing over the weekend."""

from datetime import date, datetime, timedelta
from typing import Dict, List, NamedTuple, Optional
from urllib.parse import quote

from PIL import Image

from .. import http
from ..render import PAD, RIGHT, WIDTH, Canvas, clean, fit, font, line_height, wrap

LINES_URL = "https://api.tfl.gov.uk/Line/Mode/{modes}"
STATUS_URL = "https://api.tfl.gov.uk/Line/{ids}/Status/{start}/to/{end}"

FRIDAY = 4
FINE = (10, 18)  # good service, no issues
MAX_LINES = 40  # more than there are
NEVER_AT_WEEKENDS = {"waterloo-city"}  # listed as closed every week
SHORT = {"Planned Closure": "Closed", "Part Closure": "Part closed", "Reduced Service": "Reduced",
         "Part Suspended": "Part susp.", "No Step Free Access": "No step-free", "Change of frequency": "Changed"}
# Trains after midnight belong to the evening before.
DAY_STARTS = timedelta(hours=4)


class Closure(NamedTuple):
    line: str
    status: str
    days: str  # "", "Sat" or "Sun"; empty means both
    reason: str


class Weekend(NamedTuple):
    closures: List[Closure]
    favourite: Optional[Closure]


def _touched(periods, saturday: date) -> List[str]:
    """Which of the two days the given validity periods touch; both if there are none."""
    days = []
    for offset, name in enumerate(("Sat", "Sun")):
        day = saturday + timedelta(days=offset)
        spans = [[(datetime.fromisoformat(period[k].replace("Z", "+00:00")) - DAY_STARTS).date() for k in ("fromDate", "toDate")] for period in periods]
        if not spans or any(start <= day <= end for start, end in spans):
            days.append(name)
    return days


def parse(payload, favourite: str, saturday: date) -> Weekend:
    closures = []
    for line in payload[:MAX_LINES]:
        if line["id"] in NEVER_AT_WEEKENDS:
            continue
        worst: Dict[str, dict] = {}  # for each day: closed on one can be part closed on the other
        for status in line.get("lineStatuses", []):
            if status.get("statusSeverity", 10) not in FINE:
                for day in _touched(status.get("validityPeriods") or [], saturday):
                    if day not in worst or status["statusSeverity"] < worst[day]["statusSeverity"]:
                        worst[day] = status
        same = len(worst) == 2 and worst["Sat"]["statusSeverityDescription"] == worst["Sun"]["statusSeverityDescription"]
        for day in ("Sat",) if same else [day for day in ("Sat", "Sun") if day in worst]:
            status = clean(worst[day]["statusSeverityDescription"])
            closures.append(Closure(clean(line["name"]), SHORT.get(status, status), "" if same else day, clean(worst[day].get("reason") or "")))
    return Weekend(closures, next((c for c in closures if c.line.lower() == favourite.lower()), None))


def fetch(cfg, session, now: datetime) -> Optional[Weekend]:
    if now.weekday() != FRIDAY:
        return None
    saturday = now.date() + timedelta(days=1)
    lines = http.get(session, LINES_URL.format(modes=",".join(cfg.tube.modes))).json()
    url = STATUS_URL.format(ids=",".join(quote(str(line["id"]), safe="") for line in lines[:MAX_LINES]),
                            start=saturday, end=saturday + timedelta(days=2))  # to Monday at 00:00, or Sunday is left out
    return parse(http.get(session, url).json(), cfg.tube.favourite, saturday)


def render(data: Optional[Weekend], now: datetime) -> Optional[Image.Image]:
    if data is None:
        return None
    canvas = Canvas()
    canvas.heading("Closed this weekend")
    name_font, status_font = font("semibold", 20), font("bold", 20)
    for closure in data.closures:
        status = fit(f"{closure.status} {closure.days}".strip(), status_font, WIDTH * 0.5)
        room = RIGHT - PAD - 10 - status_font.getlength(status)
        canvas.text(PAD, canvas.y, fit(closure.line, name_font, room), name_font)
        canvas.text(RIGHT, canvas.y, status, status_font, "ra")
        canvas.y += line_height(name_font) + 2
    if data.favourite and data.favourite.reason:
        small = font("semibold", 18)
        canvas.y += 4
        for text in wrap(data.favourite.reason, small, RIGHT - PAD, 6):
            canvas.text(PAD, canvas.y, text, small)
            canvas.y += line_height(small)
    if not data.closures:
        canvas.text(WIDTH / 2, canvas.y, "Nothing planned", name_font, "ma")
        canvas.y += line_height(name_font)
    canvas.y += 4
    return canvas.finish()
