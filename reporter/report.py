"""Assembles the blocks into one image. One that fails never stops the rest."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, NamedTuple, Optional, Sequence

from PIL import Image

from . import http, render
from .config import Config
from .sections import REGISTRY, TITLES, events, pages, reminders

PRIVATE = (events, reminders, pages.wifi_page)  # only ever on paper
AT_ONCE = 4  # with a dead network everything waits for its time-out: better together

log = logging.getLogger(__name__)


class Report(NamedTuple):
    image: Image.Image
    failed: List[str]
    missing: Sequence[str] = ()  # feeds that gave nothing, though others did
    pieces: Sequence[tuple] = ()  # (name, picture) of each block that has something to print


def _fetch(name: str, cfg: Config, now: datetime, on_screen: bool):
    section = REGISTRY[name]
    if on_screen and section in PRIVATE:
        return section.example()
    return section.fetch(cfg, http.make_session(), now)


def build(cfg: Config, now: datetime, on_screen: bool = False, names: Optional[Sequence[str]] = None, asked: Sequence[str] = ()) -> Report:
    """`on_screen` previews never read the calendar, the reminders or the Wi-Fi details.
    `names` are the blocks, normally those of the receipt. Those in `asked` say so if they
    have nothing to print; the others are left out."""
    pieces, failed, missing = [], [], []
    with ThreadPoolExecutor(AT_ONCE) as pool:
        waiting = [(name, pool.submit(_fetch, name, cfg, now, on_screen)) for name in (cfg.sections if names is None else names)]
        for name, pending in waiting:
            try:
                data = pending.result()
                missing += getattr(data, "missing", ())
                image = REGISTRY[name].render(data, now)
                log.info("block %s %s", name, "left out" if image is None else "ok")
                if image is None and name in asked:
                    image = render.notice(f"{TITLES[name]}: nothing today")
            except Exception as exc:
                log.warning("block %s failed: %s", name, http.trace(exc))
                failed.append(name)
                image = render.notice(f"{TITLES.get(name, name)} unavailable")
            if image is not None:
                pieces.append((name, image))
    images = [image for _, image in pieces]
    return Report(render.to_bitmap(render.stack(images or [render.notice("Nothing to print today")])), failed, missing, pieces)
