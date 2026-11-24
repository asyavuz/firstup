"""Prints a short strip of settings so the best can be chosen by eye.

Copy the winner into [printer] in config.local.toml. Worth repeating after a change of
paper or power supply. Seen on paper: contrast rises from 45 to 75,
90 smudges, 110 and above squash the print to about half its length.
"""

import dataclasses
import logging

from PIL import Image, ImageDraw

from . import render
from .config import PrinterSettings
from .printer import ThermalPrinter

log = logging.getLogger(__name__)

HEAT_TIMES = (55, 60, 65, 70, 75, 80)  # hottest last: it can spoil what follows


def block(heat: int) -> Image.Image:
    canvas = render.Canvas()
    canvas.y = 6
    fnt = render.font("semibold", 20)
    canvas.text(0, canvas.y, str(heat), render.font("title", 36))
    canvas.text(76, canvas.y, "Minor Delays", fnt)
    canvas.text(render.RIGHT, canvas.y, "1024 demanding", fnt, "ra")
    canvas.text(76, canvas.y + 26, "Have a vision.", fnt)
    canvas.text(render.RIGHT, canvas.y + 26, "Colin Powell", fnt, "ra")
    canvas.y += 62
    render.dotted_rule(ImageDraw.Draw(canvas.img), canvas.y)
    canvas.y += 8
    return render.to_bitmap(canvas.finish())


def run(settings: PrinterSettings) -> bool:
    with ThermalPrinter(settings) as device:
        device.check_ready()
        for heat in HEAT_TIMES:
            device.settings = dataclasses.replace(settings, heat_time=heat)
            device.apply_heat()
            device.print_image(block(heat), feed_lines=0)
            device.status(timeout=5)  # returns once the block has been worked through
            log.info("heat time %d sent", heat)
        device.settings = settings
        device.apply_heat()
        device.feed(4)
        return device.confirm_done()
