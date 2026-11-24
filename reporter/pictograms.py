"""Solid icons drawn in code. Drawn large and scaled down, so strokes stay several dots
wide: thin lines print pale on thermal paper."""

from functools import lru_cache
from math import cos, radians, sin

from PIL import Image, ImageDraw

SIZE, STROKE = 400, 26


def _sunscreen(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([110, 140, 290, 385], 36, outline=255, width=STROKE)
    d.rectangle([150, 92, 250, 150], fill=255)
    d.rounded_rectangle([160, 20, 240, 100], 18, fill=255)
    cx, cy = 200, 262
    d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=255)
    for angle in range(0, 360, 45):
        x, y = cos(radians(angle)), sin(radians(angle))
        d.line([cx + x * 42, cy + y * 42, cx + x * 62, cy + y * 62], fill=255, width=16)


def _hat(d: ImageDraw.ImageDraw) -> None:
    d.chord([95, 70, 305, 390], 180, 360, fill=255)
    d.rectangle([95, 225, 305, 258], fill=0)
    d.ellipse([5, 235, 395, 330], fill=255)
    d.rectangle([100, 232, 300, 246], fill=0)


def _shade(d: ImageDraw.ImageDraw) -> None:
    d.pieslice([20, 40, 380, 400], 180, 360, fill=255)
    for x in (110, 200, 290):
        d.line([200, 44, x, 222], fill=0, width=12)
    for x in (20, 110, 200, 290):
        d.ellipse([x, 196, x + 90, 250], fill=0)
    d.line([200, 30, 200, 385], fill=255, width=STROKE)
    d.line([120, 380, 280, 380], fill=255, width=STROKE)


def _flower(d: ImageDraw.ImageDraw) -> None:
    for angle in range(0, 360, 60):
        x, y = 200 + 108 * cos(radians(angle)), 200 + 108 * sin(radians(angle))
        d.ellipse([x - 74, y - 74, x + 74, y + 74], fill=255)
    for angle in range(30, 390, 60):
        d.line([200, 200, 200 + 190 * cos(radians(angle)), 200 + 190 * sin(radians(angle))], fill=0, width=16)
    d.ellipse([128, 128, 272, 272], fill=0)
    d.ellipse([150, 150, 250, 250], fill=255)


def _train(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([70, 20, 330, 310], 70, fill=255)
    d.rounded_rectangle([108, 84, 188, 180], 14, fill=0)
    d.rounded_rectangle([212, 84, 292, 180], 14, fill=0)
    d.rounded_rectangle([150, 42, 250, 62], 8, fill=0)
    for x in (112, 248):
        d.ellipse([x, 226, x + 40, 266], fill=0)
    d.line([120, 310, 70, 385], fill=255, width=30)
    d.line([280, 310, 330, 385], fill=255, width=30)
    d.line([96, 350, 304, 350], fill=255, width=22)


def _calendar(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([30, 60, 370, 375], 40, fill=255)
    for x in (110, 260):
        d.rounded_rectangle([x, 15, x + 34, 110], 14, fill=255)
    d.rectangle([62, 148, 338, 343], fill=0)
    d.polygon([(200, 172), (221, 226), (279, 229), (234, 265), (249, 321), (200, 290), (151, 321), (166, 265), (121, 229), (179, 226)], fill=255)


def _clock(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([20, 20, 380, 380], fill=255)
    d.ellipse([62, 62, 338, 338], fill=0)
    d.line([200, 200, 200, 108], fill=255, width=34)
    d.line([200, 200, 268, 236], fill=255, width=34)
    d.ellipse([178, 178, 222, 222], fill=255)


def _warning(d: ImageDraw.ImageDraw) -> None:
    d.polygon([(200, 22), (392, 366), (8, 366)], fill=255)
    d.line([200, 130, 200, 252], fill=0, width=44)
    d.ellipse([174, 284, 226, 336], fill=0)


def _tunnel(d: ImageDraw.ImageDraw) -> None:
    d.pieslice([10, 10, 390, 390], 180, 360, fill=255)
    d.rectangle([10, 200, 390, 385], fill=255)
    d.pieslice([62, 62, 338, 338], 180, 360, fill=0)
    d.rectangle([62, 200, 338, 385], fill=0)
    d.rounded_rectangle([104, 110, 296, 352], 60, fill=255)
    d.rounded_rectangle([130, 168, 270, 248], 12, fill=0)
    for x in (132, 238):
        d.ellipse([x, 282, x + 34, 316], fill=0)


def _smile(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([15, 15, 385, 385], fill=255)
    d.ellipse([52, 52, 348, 348], fill=0)
    for x in (122, 238):
        d.ellipse([x, 130, x + 40, 178], fill=255)
    d.arc([112, 120, 288, 296], 25, 155, fill=255, width=32)


def _quotes(d: ImageDraw.ImageDraw) -> None:
    for x in (20, 215):
        d.rounded_rectangle([x, 190, x + 165, 350], 40, fill=255)
        d.pieslice([x, 60, x + 270, 330], 180, 270, fill=255)
        d.pieslice([x + 72, 132, x + 250, 330], 180, 275, fill=0)
        d.rounded_rectangle([x, 190, x + 165, 350], 40, fill=255)


def _uv(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([112, 112, 288, 288], fill=255)
    for angle in range(0, 360, 45):
        x, y = cos(radians(angle)), sin(radians(angle))
        d.line([200 + x * 128, 200 + y * 128, 200 + x * 188, 200 + y * 188], fill=255, width=40)


def _moon(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([40, 30, 380, 370], fill=255)
    d.ellipse([150, 0, 430, 290], fill=0)


def _grid(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([20, 20, 380, 380], 30, fill=255)
    for i in range(3):
        for j in range(3):
            if (i + j) % 2:
                d.rectangle([52 + i * 104, 52 + j * 104, 140 + i * 104, 140 + j * 104], fill=0)


def _hourglass(d: ImageDraw.ImageDraw) -> None:
    d.rounded_rectangle([70, 15, 330, 62], 18, fill=255)
    d.rounded_rectangle([70, 338, 330, 385], 18, fill=255)
    d.polygon([(100, 62), (300, 62), (300, 112), (216, 200), (300, 288), (300, 338), (100, 338), (100, 288), (184, 200), (100, 112)], fill=255)
    d.polygon([(140, 88), (260, 88), (260, 104), (140, 104)], fill=0)
    d.polygon([(200, 232), (262, 300), (138, 300)], fill=0)


_DRAWINGS = {"sunscreen": _sunscreen, "hat": _hat, "shade": _shade, "flower": _flower, "train": _train,
             "calendar": _calendar, "clock": _clock, "warning": _warning, "hourglass": _hourglass, "grid": _grid, "tunnel": _tunnel, "smile": _smile, "quotes": _quotes,
             "uv": _uv, "moon": _moon}


@lru_cache(maxsize=None)
def pictogram(name: str, box: int) -> Image.Image:
    mask = Image.new("L", (SIZE, SIZE), 0)
    _DRAWINGS[name](ImageDraw.Draw(mask))
    mask = mask.crop(mask.getbbox())
    scale = box / max(mask.size)
    mask = mask.resize((round(mask.width * scale), round(mask.height * scale)), Image.LANCZOS)
    img = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    img.putalpha(mask)
    return img
