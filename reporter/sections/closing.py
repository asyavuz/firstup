from datetime import datetime

from PIL import Image

from ..pictograms import pictogram
from ..render import WIDTH, Canvas, font, line_height


def fetch(cfg, session, now):
    return None


def part_of_day(now: datetime) -> str:
    if 4 <= now.hour < 18:
        return "day"
    return "evening" if 18 <= now.hour < 22 else "night"


def render(data, now: datetime) -> Image.Image:
    canvas = Canvas()
    fnt = font("semibold", 23)
    smile = pictogram("smile", 40)
    text = f"Have a fabulous {part_of_day(now)}!"
    width = fnt.getlength(text) + 8 + smile.width
    x = (WIDTH - width) / 2
    height = max(line_height(fnt), smile.height)
    canvas.text(x, 5 + height / 2, text, fnt, "lm")
    canvas.icon(smile, x + fnt.getlength(text) + 8, 5 + (height - smile.height) / 2)
    canvas.y = height + 10
    return canvas.finish()
