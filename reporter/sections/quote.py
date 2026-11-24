from datetime import datetime
from typing import NamedTuple

from PIL import Image

from .. import http
from ..blocks import COLUMN, titled
from ..pictograms import pictogram
from ..render import PAD, RIGHT, Canvas, clean, fit, font, line_height, wrap

URL = "https://zenquotes.io/api/today"


class Quote(NamedTuple):
    text: str
    author: str


def parse(payload) -> Quote:
    return Quote(clean(payload[0]["q"]), clean(payload[0]["a"]) or "Unknown")


def fetch(cfg, session, now) -> Quote:
    return parse(http.get(session, URL).json())


def render(data: Quote, now: datetime) -> Image.Image:
    canvas = Canvas()
    left = titled(canvas, "Quote of the day", "quotes")
    body, author = font("semibold", 21), font("bold", 19)
    for line in wrap(data.text, body, RIGHT - left, 12):
        canvas.text(left, canvas.y, line, body)
        canvas.y += line_height(body)
    canvas.y = max(canvas.y, pictogram("quotes", COLUMN).height + 40) + 4
    canvas.text(RIGHT, canvas.y, fit(f"– {data.author}", author, RIGHT - PAD), author, "ra")
    canvas.y += line_height(author) + 4
    return canvas.finish()
