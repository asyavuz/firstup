from datetime import datetime
from typing import List, NamedTuple, Optional

from PIL import Image

from .. import http
from ..pictograms import pictogram
from ..render import PAD, RIGHT, WIDTH, Canvas, clean, fit, font, line_height, wrap

URL = "https://api.tfl.gov.uk/Line/Mode/{modes}/Status"

MAX_LINES = 40  # more than there are
GOOD = ("Good Service", "No Issues")
SHORT_STATUS = {"No Step Free Access": "No Step-Free", "Change of frequency": "Freq. Change"}


class Line(NamedTuple):
    name: str
    status: str
    reason: str

    @property
    def good(self) -> bool:
        return self.status in GOOD


class Status(NamedTuple):
    lines: List[Line]
    favourite: Optional[Line]


def parse(payload, favourite: str) -> Status:
    lines = []
    for entry in payload[:MAX_LINES]:
        statuses = entry.get("lineStatuses") or []
        # Lowest severity number is the worst; a line can carry several at once.
        worst = min(statuses, key=lambda s: s.get("statusSeverity", 10), default=None)
        name = clean(entry["name"])
        if worst is None:
            lines.append(Line(name, "No data", ""))
        else:
            status = clean(worst["statusSeverityDescription"])
            lines.append(Line(name, SHORT_STATUS.get(status, status),
                              clean(worst.get("reason") or "")))
    if not lines:
        raise RuntimeError("TfL returned no lines")
    return Status(lines, next((ln for ln in lines if ln.name.lower() == favourite.lower()), None))


def fetch(cfg, session, now) -> Status:
    url = URL.format(modes=",".join(cfg.tube.modes))
    return parse(http.get(session, url).json(), cfg.tube.favourite)


def _render_favourite(canvas: Canvas, line: Line) -> None:
    name_font, status_font = font("bold", 24), font("semibold", 24)
    mark = pictogram("tunnel", 36)
    named = mark.width + 10 + name_font.getlength(line.name)
    beside = named + 10 + status_font.getlength(line.status) <= RIGHT - PAD
    x = max(PAD, (WIDTH - named - (10 + status_font.getlength(line.status) if beside else 0)) / 2)
    mid = canvas.y + 16
    canvas.icon(mark, x, mid - mark.height / 2)
    x += mark.width + 10
    canvas.text(x, mid, fit(line.name, name_font, RIGHT - x), name_font, "lm")
    if beside:
        canvas.text(x + name_font.getlength(line.name) + 10, mid, line.status, status_font, "lm")
    canvas.y += 38
    for text in [] if beside else wrap(line.status, status_font, RIGHT - PAD, 2):
        canvas.text(WIDTH / 2, canvas.y, text, status_font, "ma")
        canvas.y += line_height(status_font)
    if not line.good and line.reason:
        small = font("semibold", 18)
        for text in wrap(line.reason, small, RIGHT - PAD, 5):
            canvas.text(PAD, canvas.y, text, small)
            canvas.y += line_height(small)
        canvas.y += 5


def render(data: Status, now: datetime) -> Image.Image:
    canvas = Canvas()
    canvas.heading("Underground status")
    if data.favourite:
        _render_favourite(canvas, data.favourite)
    others = [ln for ln in data.lines if ln is not data.favourite]
    disrupted = [ln for ln in others if not ln.good]
    name_font, status_font = font("semibold", 20), font("bold", 20)
    for line in disrupted:
        status = fit(line.status, status_font, WIDTH * 0.55)
        room = RIGHT - PAD - 10 - status_font.getlength(status)
        canvas.text(PAD, canvas.y, fit(line.name, name_font, room), name_font)
        canvas.text(RIGHT, canvas.y, status, status_font, "ra")
        canvas.y += line_height(name_font) + 2
    if len(disrupted) < len(others):
        canvas.y += 2
        text = "Good service on all other lines" if disrupted or data.favourite else "Good service on all lines"
        canvas.text(WIDTH / 2, canvas.y, text, name_font, "ma")
        canvas.y += line_height(name_font) + 2
    return canvas.finish()
