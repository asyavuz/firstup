from datetime import datetime

from PIL import Image

from ..render import RIGHT, Canvas, font


def fetch(cfg, session, now):
    return None


def render(data, now: datetime) -> Image.Image:
    canvas = Canvas()
    canvas.text(0, 2, f"{now:%H:%M}", font("title", 69))
    canvas.text(RIGHT, 14, f"{now.day} {now:%b %Y}", font("subtitle", 27), "ra")
    canvas.text(RIGHT, 46, f"{now:%A}", font("subtitle", 25), "ra")
    canvas.y = 88
    return canvas.finish()
