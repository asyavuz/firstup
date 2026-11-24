"""Every National Rail station: code, name, position. Standard library only.

stations.csv comes from github.com/davwheat/uk-railway-stations (Open Database Licence).
"""

import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, NamedTuple, Optional

FILE = Path(__file__).resolve().parent / "stations.csv"


class Station(NamedTuple):
    code: str
    name: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})"


@lru_cache(maxsize=1)
def all_stations() -> Dict[str, Station]:
    with FILE.open(encoding="utf-8", newline="") as handle:
        return {code: Station(code, name, float(lat), float(lon)) for code, name, lat, lon in csv.reader(handle)}


def find(text: str) -> Optional[Station]:
    """From a label, a code or a full name, as somebody might type it."""
    text = " ".join(text.split()).lower()
    stations = all_stations()
    if text.endswith(")") and "(" in text:
        text = text[text.rindex("(") + 1:-1]
    if text.upper() in stations:
        return stations[text.upper()]
    return next((s for s in stations.values() if s.name.lower() == text), None)
