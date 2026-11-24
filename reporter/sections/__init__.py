"""The blocks. Each has `fetch(cfg, session, now)` and `render(data, now)`.

`render` may return None to leave the block out today.

Fetching and drawing are separate so drawing can be tested without a network.
"""

from ..settings import SECTIONS
from . import (ahead, closing, events, header, history, mytrains, news, pages, pollen, quote, reminders, sudoku, tube, warnings,
               weather, weekend)

REGISTRY = {
    "header": header,
    "warnings": warnings,
    "weather": weather,
    "pollen": pollen,
    "events": events,
    "reminders": reminders,
    "ahead": ahead,
    "trains": mytrains,
    "tube": tube,
    "weekend": weekend,
    "news": news,
    "history": history,
    "quote": quote,
    "sudoku": sudoku,
    "departures": pages.departures,
    "health": pages.health_page,
    "wifi": pages.wifi_page,
    "poster": pages.poster_page,
    "closing": closing,
}

# Shown on paper when a block fails; the same names as in the web interface.
TITLES = {name: label.split(" (")[0] for name, label in SECTIONS.items()}
