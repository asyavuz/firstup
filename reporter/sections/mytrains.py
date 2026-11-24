"""The next few trains you could catch. The page with the whole hour is reporter/trains.py."""

from datetime import datetime, timedelta
from typing import NamedTuple, Optional

from PIL import Image

from .. import stations, trains
from ..config import DAY_NAMES
from ..pictograms import pictogram
from ..render import RIGHT, WIDTH, Canvas, fit, font, line_height


class Mine(NamedTuple):
    board: trains.Board
    towards: str
    start: datetime


def fetch(cfg, session, now: datetime) -> Optional[Mine]:
    settings = cfg.trains
    token = trains.load_token()
    if token is None or DAY_NAMES[now.weekday()] not in settings.days:
        return None
    start = now + timedelta(minutes=settings.offset)
    return Mine(trains.upcoming(settings, token, session, now, start), settings.towards, start)


def render(data: Optional[Mine], now: datetime) -> Optional[Image.Image]:
    if data is None:
        return None
    canvas = Canvas()
    small, picture = font("semibold", 18), pictogram("train", 34)
    towards = stations.find(data.towards) if data.towards else None
    room = 2 * RIGHT - WIDTH  # in the middle, and not past RIGHT
    canvas.heading(fit(data.board.station or "My trains", font("bold", 26), room - picture.width - 12), picture)
    canvas.text(WIDTH / 2, canvas.y, fit((f"to {towards.name}, " if towards else "") + f"from {data.start:%H:%M}", small, room), small, "ma")
    canvas.y += line_height(small) + 4
    for train in data.board.trains:
        trains._row(canvas, train)
    if not data.board.trains:
        canvas.text(WIDTH / 2, canvas.y, "No trains", font("semibold", 20), "ma")
        canvas.y += line_height(font("semibold", 20))
    canvas.y += 2
    return canvas.finish()
