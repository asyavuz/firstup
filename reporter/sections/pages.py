"""Whole pages as blocks, so they can go wherever any other block can."""

from typing import Any, Callable, Optional

from PIL import Image

from .. import health, poster, render, trains, wifi


class Page:
    """`ask` gets the data, `draw` makes the picture from it."""

    def __init__(self, ask: Callable, draw: Callable, example: Optional[str] = None) -> None:
        self.ask, self.draw, self._example = ask, draw, example

    def fetch(self, cfg, session, now) -> Any:
        return self.ask(cfg, now)

    def render(self, data, now) -> Image.Image:
        return render.notice(data) if isinstance(data, str) else self.draw(data, now)

    def example(self) -> Optional[str]:
        return self._example


departures = Page(lambda cfg, now: (cfg.trains, trains.ask(cfg.trains, now)), lambda data, now: trains.draw(*data, now))
health_page = Page(lambda cfg, now: cfg, health.page)
poster_page = Page(lambda cfg, now: None, lambda data, now: poster.page(now))
wifi_page = Page(lambda cfg, now: wifi.load(), lambda data, now: wifi.page(data), "Wi-Fi details, on paper only")
