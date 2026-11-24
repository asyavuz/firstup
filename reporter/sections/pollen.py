"""Pollen, on the days there is some. Forecast: Open-Meteo (CAMS), hourly.

The bands are those used in Britain for grass and birch; alder follows birch and mugwort
follows grass. They are meant for daily counts; here the strongest hour still to come is
used, which in 2026 gave 28 days for grass, 21 birch, 12 alder and 35 mugwort.
"""

from datetime import datetime
from typing import Dict, List, NamedTuple, Optional, Sequence

from PIL import Image

from .. import http
from ..blocks import block
from ..render import Canvas

URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
LEVELS = ("moderate", "high", "very high")
GRASS, TREE = (30, 50, 150), (40, 80, 200)  # grains per cubic metre, for each level
BANDS = {"grass": GRASS, "birch": TREE, "alder": TREE, "mugwort": GRASS}


class Pollen(NamedTuple):
    kind: str
    level: int  # place in LEVELS
    hours: str


def _level(value: float, bands: Sequence[int]) -> int:
    return sum(value >= limit for limit in bands) - 1


def _spell(hours: Sequence[int]) -> str:
    return f"{min(hours):02d}:00–{max(hours) + 1:02d}:00"


def parse(payload: Dict, kinds: Sequence[str], least: str, from_hour: int) -> List[Pollen]:
    hourly, found = payload["hourly"], []
    for kind in kinds:
        ahead = {datetime.fromisoformat(stamp).hour: value or 0 for stamp, value in zip(hourly["time"], hourly.get(f"{kind}_pollen") or [])}
        ahead = {hour: value for hour, value in ahead.items() if hour >= from_hour}
        level = _level(max(ahead.values(), default=0), BANDS[kind])
        if level >= LEVELS.index(least):
            found.append(Pollen(kind, level, _spell([h for h, v in ahead.items() if _level(v, BANDS[kind]) >= 0])))
    return sorted(found, key=lambda p: -p.level)


def fetch(cfg, session, now: datetime) -> List[Pollen]:
    params = {**cfg.weather.position, "timezone": cfg.timezone, "forecast_days": 1,
              "hourly": ",".join(f"{kind}_pollen" for kind in cfg.pollen.kinds)}
    return parse(http.get(session, URL, params=params).json(), cfg.pollen.kinds, cfg.pollen.level, now.hour)


def render(data: List[Pollen], now: datetime) -> Optional[Image.Image]:
    if not data:
        return None
    canvas = Canvas()
    first, *rest = data
    lines = [first.hours]
    if rest:
        lines.append("Also " + ", ".join(f"{p.kind} {LEVELS[p.level]}" for p in rest))
    block(canvas, "flower", f"{first.kind.capitalize()} pollen {LEVELS[first.level]}", lines, 2)
    return canvas.finish()
