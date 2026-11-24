"""What the short sections share: a bold picture on the left, a strong line and a few more."""

from typing import Sequence

from .pictograms import pictogram
from .render import PAD, RIGHT, Canvas, font, line_height, wrap

TEXT_X, ICON, COLUMN = PAD + 54, 44, 38


def block(canvas: Canvas, picture: str, strong: str, lines: Sequence[str] = (), most: int = 3, right: float = RIGHT) -> None:
    top, bold, body = canvas.y + 4, font("bold", 22), font("semibold", 20)
    canvas.y = top - 2
    for line in wrap(strong, bold, right - TEXT_X, 2):
        canvas.text(TEXT_X, canvas.y, line, bold)
        canvas.y += line_height(bold)
    for text in lines:
        for line in wrap(text, body, right - TEXT_X, most):
            canvas.text(TEXT_X, canvas.y, line, body)
            canvas.y += line_height(body)
    image = pictogram(picture, ICON)
    canvas.y = max(canvas.y, top + ICON)
    canvas.icon_centred(image, PAD + ICON / 2, (top + canvas.y) / 2 if not lines else top + ICON / 2)
    canvas.y += 4


def titled(canvas: Canvas, title: str, picture: str) -> float:
    """A title in the middle and a picture under it at the left. Where the text beside it starts."""
    canvas.heading(title)
    image = pictogram(picture, COLUMN)
    canvas.icon(image, PAD + (COLUMN - image.width) / 2, canvas.y + 5)
    return PAD + COLUMN + 14
