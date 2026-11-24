"""The First Up poster. Drawn by tools/make_pictures.py."""

from datetime import datetime

from PIL import Image

from . import render
from .config import ROOT

FILE, ADDRESS = ROOT / "assets/gfx/first-up.png", "github.com/asyavuz/firstup"


def page(now: datetime) -> Image.Image:
    picture = Image.open(FILE).convert("L")
    canvas = render.Canvas()
    canvas.img.paste(picture, ((render.WIDTH - picture.width) // 2, 0))
    canvas.y = picture.height + 6
    small, strong = render.font("semibold", 18), render.font("bold", 19)
    canvas.text(render.WIDTH / 2, canvas.y, f"{now:%A} {now.day} {now:%B %Y}, {now:%H:%M}", small, "ma")
    canvas.y += render.line_height(small)
    canvas.text(render.WIDTH / 2, canvas.y, ADDRESS, strong, "ma")
    canvas.y += render.line_height(strong) + 4
    return render.to_bitmap(canvas.finish())
