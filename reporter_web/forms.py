"""Turns submitted forms into settings. Raises ValueError with words for the user."""

import hashlib
import json
import re
from typing import Any, Dict, List

from reporter import settings, stations

Form = Dict[str, List[str]]
KEEP = (30, 60, 120, 180, 240)  # minutes to keep trying
LAST = 23 * 60 + 55
_POSITION = re.compile(r"^(-?\d{1,2}(?:\.\d{1,8})?)\s*,\s*(-?\d{1,3}(?:\.\d{1,8})?)$")


def one(form: Form, name: str) -> str:
    return form.get(name, [""])[0].strip()


def shown(form: Form, name: str, otherwise: int) -> int:
    """A number that was typed, to show it again."""
    try:
        return _whole(form, name)
    except ValueError:
        return otherwise


def _whole(form: Form, name: str) -> int:
    text = one(form, name)
    if not (text.isascii() and text.isdigit() and len(text) <= 4):
        raise ValueError("Choose a number")
    return int(text)


def sections(form: Form, current: Any, original: Any) -> List[str]:
    order = [name for name in dict.fromkeys(form.get("order", [])) if name in settings.SECTIONS]
    order += [name for name in settings.SECTIONS if name not in order]
    on = set(form.get("on", []))
    chosen = [name for name in order if name in on]
    direction, _, name = one(form, "move").partition(":")
    if name in chosen and direction in ("up", "down"):
        place = chosen.index(name)
        other = place + (-1 if direction == "up" else 1)
        if 0 <= other < len(chosen):
            chosen[place], chosen[other] = chosen[other], chosen[place]
    return chosen


def minutes(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:])


def _clock(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def schedule(form: Form, current: Any, original: Any) -> List[dict]:
    slots: Dict[tuple, List[str]] = {}
    for day in settings.DAYS:
        together = day in form.get("all", [])
        if not (together or form.get(f"on-{day}")):
            continue
        hour, minute = (_whole(form, f"all-{part}" if together else f"{part}-{day}") for part in ("hour", "minute"))
        keep = _whole(form, f"keep-{day}")
        start = hour * 60 + minute
        if start >= LAST:
            raise ValueError(f"on {day}, choose a time before 23:55")
        # The next half hour always fits; more must not go past midnight without a word.
        end = start + keep if keep > KEEP[0] else min(start + keep, LAST)
        if end > LAST:
            raise ValueError(f"on {day} it cannot keep trying past 23:55. Choose a shorter time")
        slots.setdefault((_clock(start), _clock(end)), []).append(day)
    return [{"days": days, "time": time, "catch_up_until": until} for (time, until), days in slots.items()]


def weather(form: Form, current: Any, original: Any) -> dict:
    text, uv = " ".join(one(form, "place").split()), _whole(form, "uv_from")
    position = _POSITION.match(text)
    known = next((place for place in (current, original) if place["place"].lower() == text.lower()), None)
    if known:
        text, latitude, longitude = known["place"], known["latitude"], known["longitude"]
    elif position:
        latitude, longitude = float(position[1]), float(position[2])
    else:
        station = stations.find(text)
        if station is None:
            raise ValueError("Choose a station from the list, or type a position like 51.51, -0.13")
        text, latitude, longitude = station.name, station.latitude, station.longitude
    return {"place": text, "latitude": latitude, "longitude": longitude, "uv_from": uv}


def pollen(form: Form, current: Any, original: Any) -> dict:
    return {"level": one(form, "level"), "kinds": [k for k in settings.POLLENS if k in form.get("kinds", [])]}


def tube(form: Form, current: Any, original: Any) -> dict:
    return {"favourite": one(form, "favourite"), "modes": [m for m in settings.MODES if m in form.get("modes", [])]}


def news(form: Form, current: Any, original: Any) -> dict:
    feeds = []
    for i in range(settings.MAX_FEEDS):
        name, url = one(form, f"name-{i}"), one(form, f"url-{i}")
        if name or url:
            try:
                settings.news({"count": 1, "feeds": [{"name": name, "url": url}]})
            except ValueError as exc:
                raise ValueError(f"feed {i + 1}: {exc}") from None
            feeds.append({"name": name, "url": url})
    return {"count": _whole(form, "count"), "feeds": feeds}


def fingerprint(value: Any) -> str:
    """Goes out with a form, to tell afterwards whether this form changed anything."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def _station(text: str, current: str, what: str) -> str:
    if current and text.upper() == current:
        return current  # also one that is not in the list
    station = stations.find(text)
    if station is None:
        raise ValueError(f"{what}: choose a station from the list")
    return station.code


def trains(form: Form, current: Any, original: Any) -> dict:
    towards = one(form, "towards")
    return {"station": _station(one(form, "station"), current["station"], "station"), "towards": _station(towards, current["towards"], "only trains calling at") if towards else "",
            "offset": _whole(form, "offset"), "count": _whole(form, "trains"), "days": [d for d in settings.DAYS if d in form.get("days", [])]}


def warnings(form: Form, current: Any, original: Any) -> dict:
    return {"region": one(form, "region")}


def _presses(form: Form, kind: str) -> Dict[str, int]:
    return {name: _whole(form, f"{kind}-{name}") for name in settings.PRESSABLE if one(form, f"{kind}-{name}") not in ("", "0")}


def button(form: Form, current: Any, original: Any) -> dict:
    return {"taps": _presses(form, "taps"), "holds": _presses(form, "hold")}


def sudoku(form: Form, current: Any, original: Any) -> dict:
    return {"level": one(form, "sudoku")}


def printer(form: Form, current: Any, original: Any) -> dict:
    return {"heat_time": _whole(form, "heat_time")}


FORMS = {"sections": sections, "schedule": schedule, "weather": weather, "warnings": warnings, "pollen": pollen, "tube": tube,
         "news": news, "sudoku": sudoku, "trains": trains, "button": button, "printer": printer}
