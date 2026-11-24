"""Drawing helpers shared by all sections."""

import os
import unicodedata
from functools import lru_cache
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ROOT

WIDTH = 384  # dots across the paper
PAD = 5
RIGHT = WIDTH - 12  # right-hand text stops here: the last few dots print pale
# Grey level below which a dot is burned. Thresholding keeps text crisp;
# Pillow's default dithering speckles it.
THRESHOLD = 190

# Nothing lighter than semibold: the head heats each row of dots once, so strokes
# one or two dots thick come out pale or not at all. Keep text at 18 or larger.
_FONT_FILES = {
    "title": "SF-Pro-Rounded-Heavy.otf",
    "subtitle": "SF-Pro-Rounded-Bold.otf",
    "semibold": "SF-Compact-Rounded-Semibold.otf",
    "bold": "SF-Compact-Rounded-Bold.otf",
}


# Apple's fonts are not ours to give away. Without them Nunito is used, at these weights.
_OPEN_FONT, _WEIGHTS = ROOT / "assets/fonts-open/Nunito.ttf", {"title": 900, "subtitle": 800, "semibold": 750, "bold": 850}


@lru_cache(maxsize=None)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    ours = ROOT / "assets/fonts" / _FONT_FILES[name]
    if ours.is_file() and not os.environ.get("REPORTER_OPEN_FONTS"):
        return ImageFont.truetype(str(ours), size)
    face = ImageFont.truetype(str(_OPEN_FONT), round(size * .92))  # it is wider
    face.set_variation_by_axes([_WEIGHTS[name]])
    return face


def line_height(fnt: ImageFont.FreeTypeFont) -> int:
    ascent, descent = fnt.getmetrics()
    return ascent + descent


@lru_cache(maxsize=None)
def icon(filename: str, box: int, embolden: bool = False) -> Image.Image:
    """An icon trimmed of its transparent border and fitted into box x box dots.

    `embolden` thickens thin line art that would otherwise print pale.
    """
    img = Image.open(ROOT / "assets/icons" / filename).convert("RGBA")
    img = img.crop(img.getchannel("A").getbbox())
    scale = box / max(img.size)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(size, Image.LANCZOS)
    if embolden:
        img.putalpha(img.getchannel("A").filter(ImageFilter.MaxFilter(3)))
    return img


MAX_TEXT = 4000
SIGNS = "°©®™№"  # the fonts have these, unlike most other symbols


def clean(text: str) -> str:
    """Drop emoji and control codes and tidy spaces. Cuts off what is longer than any paper."""
    kept = []
    for ch in text[:MAX_TEXT]:
        category = unicodedata.category(ch)
        if category.startswith("Z") or ch in "\t\r\n":
            kept.append(" ")
        elif ch in SIGNS or ord(ch) <= 0xFFFF and category not in ("So", "Cc", "Cf", "Cs", "Co", "Cn"):
            kept.append(ch)
    return " ".join("".join(kept).split())


MAX_LINE_CHARS = 200  # more than any line can hold; bounds the work on hostile text
MAX_LINES = 40


def _prefix(text: str, fnt: ImageFont.FreeTypeFont, max_width: float, suffix: str = "") -> int:
    """How many leading characters of `text` fit, found by bisection."""
    low, high = 0, min(len(text), MAX_LINE_CHARS)
    while low < high:
        middle = (low + high + 1) // 2
        if fnt.getlength(text[:middle] + suffix) <= max_width:
            low = middle
        else:
            high = middle - 1
    return low


def fit(text: str, fnt: ImageFont.FreeTypeFont, max_width: float) -> str:
    """Shorten text with an ellipsis so it never runs into its neighbour."""
    if len(text) <= MAX_LINE_CHARS and fnt.getlength(text) <= max_width:
        return text
    return text[:_prefix(text, fnt, max_width, "…")].rstrip() + "…"


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_width: float,
         max_lines: int = MAX_LINES) -> List[str]:
    """Wrap by measured pixel width, at most `max_lines` lines, the last one shortened."""
    lines: List[str] = []
    rest = " ".join(text[:MAX_LINE_CHARS * max_lines].split())
    while rest:
        if len(rest) <= MAX_LINE_CHARS and fnt.getlength(rest) <= max_width:
            lines.append(rest)
            break
        if len(lines) == max_lines - 1:
            lines.append(fit(rest, fnt, max_width))
            break
        cut = max(1, _prefix(rest, fnt, max_width))
        # Break at a space: the one right after the cut, or the last one before it.
        space = cut if rest[cut:cut + 1] == " " else rest.rfind(" ", 0, cut)
        if space > 0:
            cut = space
        lines.append(rest[:cut])
        rest = rest[cut:].lstrip()
    return lines


class Canvas:
    """A growing strip of paper; `y` is where the next thing goes."""

    def __init__(self) -> None:
        self.img = Image.new("L", (WIDTH, 2000), 255)
        self.draw = ImageDraw.Draw(self.img)
        self.y = 0

    def text(self, x: float, y: float, text: str, fnt: ImageFont.FreeTypeFont, anchor: str = "la") -> None:
        self.draw.text((x, y), text, font=fnt, fill=0, anchor=anchor)

    def icon(self, img: Image.Image, x: float, y: float) -> None:
        self.img.paste(img.convert("L"), (round(x), round(y)), img.getchannel("A"))

    def icon_centred(self, img: Image.Image, cx: float, cy: float) -> None:
        self.icon(img, cx - img.width / 2, cy - img.height / 2)

    def heading(self, text: str, picture: Optional[Image.Image] = None) -> None:
        fnt = font("bold", 26)
        self.y += 4
        left, height = (WIDTH - fnt.getlength(text)) / 2, line_height(fnt)
        if picture:
            left += (picture.width + 12) / 2
            self.icon(picture, left - picture.width - 12, self.y + 1)
            height = max(height, picture.height + 2)
        self.text(left, self.y + height / 2, text, fnt, "lm")
        self.y += height + 4

    def rule(self) -> None:
        self.y += PAD
        dotted_rule(self.draw, self.y)
        self.y += PAD

    def finish(self) -> Image.Image:
        # Never past the bottom: cropping outside the image fills with black.
        return self.img.crop((0, 0, WIDTH, min(round(self.y), self.img.height)))


def dotted_rule(draw: ImageDraw.ImageDraw, y: float) -> None:
    for x in range(0, WIDTH, 8):
        draw.rectangle([x, y, x + 3, y + 1], fill=0)


def separator() -> Image.Image:
    img = Image.new("L", (WIDTH, 2 * PAD), 255)
    dotted_rule(ImageDraw.Draw(img), PAD)
    return img


def notice(text: str) -> Image.Image:
    canvas = Canvas()
    fnt = font("semibold", 20)
    canvas.y = PAD
    canvas.text(WIDTH / 2, canvas.y, text, fnt, "ma")
    canvas.y += line_height(fnt) + PAD
    return canvas.finish()


def stack(images: List[Image.Image]) -> Image.Image:
    sep = separator()
    parts: List[Image.Image] = []
    for i, img in enumerate(images):
        if i:
            parts.append(sep)
        parts.append(img)
    out = Image.new("L", (WIDTH, sum(p.height for p in parts)), 255)
    y = 0
    for part in parts:
        out.paste(part, (0, y))
        y += part.height
    return out


def to_bitmap(img: Image.Image) -> Image.Image:
    return img.point(lambda p: 0 if p < THRESHOLD else 255).convert("1", dither=Image.Dither.NONE)
