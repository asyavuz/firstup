"""Settings changed in the web interface. Standard library only: the web program, which
cannot see the rest of the reporter, uses this file too.

They sit in one JSON file that is laid over config.toml, so a deploy never undoes them.
Every value is checked here, when it is saved and again whenever it is read. A group of
settings that is missing, damaged or out of range is ignored and config.toml's is used:
nothing in this file may stop a print.
"""

import ipaddress
import json
import os
import stat
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import urlsplit

BASE = Path(os.environ.get("REPORTER_WEB", "/var/lib/reporter-web"))
PATH = BASE / "settings" / "settings.json"
MAX_BYTES = 65536
MAX_PROBLEMS = 5  # enough to show something is wrong
UNREADABLE = "the settings file cannot be read"

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SECTIONS = {
    "header": "Date",
    "warnings": "Weather warnings (when there are any)",
    "weather": "Weather",
    "pollen": "Pollen (when there is some)",
    "events": "Calendar",
    "reminders": "Reminders",
    "ahead": "Bank holidays and clock changes",
    "trains": "My trains",
    "tube": "Underground status",
    "weekend": "Weekend closures (Fridays)",
    "news": "Headlines",
    "history": "On this day",
    "quote": "Quote of the day",
    "closing": "Closing message",
    "sudoku": "Sudoku",
    "departures": "Train times (the whole hour)",
    "health": "Printer health",
    "wifi": "Wi-Fi name and password",
    "poster": "First Up poster",
}
# What a press of the button can print: the whole receipt or any block by itself.
PRESSABLE = {"receipt": "The whole receipt", **SECTIONS}
TAPS, HOLDS = (1, 9), (1, 4)  # at 5 seconds the Pi shuts down, always
REGIONS = {
    "se": "London & South East England", "ee": "East of England", "em": "East Midlands", "wm": "West Midlands", "ne": "North East England",
    "nw": "North West England", "sw": "South West England", "yh": "Yorkshire & Humber", "wl": "Wales", "ni": "Northern Ireland",
    "dg": "Dumfries, Galloway, Lothian & Borders", "st": "Strathclyde", "ta": "Central, Tayside & Fife", "gr": "Grampian",
    "he": "Highlands & Eilean Siar", "os": "Orkney & Shetland",
}
SUDOKU = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}
POLLENS = {"grass": "Grass", "birch": "Birch", "alder": "Alder", "mugwort": "Mugwort"}
POLLEN_LEVELS = {"moderate": "Moderate", "high": "High", "very high": "Very high"}
MODES = {
    "tube": "Underground",
    "overground": "Overground",
    "elizabeth-line": "Elizabeth line",
    "dlr": "DLR",
    "tram": "Tram",
}
# As TfL spells them; the highlighted line is matched by name.
LINES = (
    "Bakerloo", "Central", "Circle", "District", "Hammersmith & City", "Jubilee", "Metropolitan",
    "Northern", "Piccadilly", "Victoria", "Waterloo & City", "Elizabeth line", "DLR",
    "Liberty", "Lioness", "Mildmay", "Suffragette", "Weaver", "Windrush", "Tram",
)
HEAT = (45, 85)  # 90 smudges, 110 and above squash the print
COUNT = (1, 8)
UV = (1, 11)
MAX_FEEDS = 6
OFFSET, TRAINS = (0, 120), (1, 6)
STEP = 5  # minutes; the timer that checks whether a print is due runs this often


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _exactly(value: Any, keys: Tuple[str, ...]) -> dict:
    _need(isinstance(value, dict) and set(value) == set(keys), f"expected exactly {', '.join(keys)}")
    return value


def _whole(value: Any, limits: Tuple[int, int], what: str) -> int:
    low, high = limits
    _need(isinstance(value, int) and not isinstance(value, bool) and low <= value <= high,
          f"{what} must be a whole number from {low} to {high}")
    return value


def _number(value: Any, limit: float, what: str) -> float:
    _need(isinstance(value, (int, float)) and not isinstance(value, bool) and -limit <= value <= limit,
          f"{what} must be between -{limit:g} and {limit:g}")
    return round(float(value), 4)


def _text(value: Any, longest: int, what: str) -> str:
    _need(isinstance(value, str), f"{what} must be text")
    value = " ".join(value.split())
    _need(1 <= len(value) <= longest, f"{what} must be 1 to {longest} characters")
    _need(not any(unicodedata.category(c).startswith("C") for c in value), f"{what} has characters that cannot be used")
    return value


def _choices(value: Any, allowed, what: str) -> List[str]:
    _need(isinstance(value, list) and all(isinstance(v, str) for v in value), f"{what} must be a list")
    unknown = [v for v in value if v not in allowed]
    _need(not unknown, f"unknown {what}")
    _need(len(value) == len(set(value)), f"{what} listed twice")
    return value


def _clock(value: Any, what: str) -> int:
    """Minutes after midnight."""
    _need(isinstance(value, str) and len(value) == 5 and value[2] == ":" and value.isascii()
          and (value[:2] + value[3:]).isdigit(), f"{what} must be like 08:00")
    hours, minutes = int(value[:2]), int(value[3:])
    _need(hours < 24 and minutes < 60, f"{what} is not a time")
    return hours * 60 + minutes


def sections(value: Any) -> List[str]:
    value = _choices(value, SECTIONS, "blocks")
    _need(bool(value), "keep at least one block")
    return value


def schedule(value: Any) -> List[dict]:
    """May be empty: nothing prints by itself."""
    _need(isinstance(value, list) and len(value) <= len(DAYS), "too many times")
    seen: List[str] = []
    result = []
    for slot in value:
        slot = _exactly(slot, ("days", "time", "catch_up_until"))
        days = _choices(slot["days"], DAYS, "days")
        _need(bool(days), "a time without days")
        start, end = _clock(slot["time"], "the time"), _clock(slot["catch_up_until"], "the cut-off")
        _need(start % STEP == 0 and end % STEP == 0, f"times must be multiples of {STEP} minutes")
        _need(start < end, "the cut-off must be later than the time")
        seen += days
        result.append({"days": sorted(days, key=DAYS.index), "time": slot["time"], "catch_up_until": slot["catch_up_until"]})
    _need(len(seen) == len(set(seen)), "a day has two times")
    return sorted(result, key=lambda slot: DAYS.index(slot["days"][0]))


def weather(value: Any) -> dict:
    value = _exactly(value, ("place", "latitude", "longitude", "uv_from"))
    return {"place": _text(value["place"], 60, "the place"),
            "latitude": _number(value["latitude"], 90, "latitude"),
            "longitude": _number(value["longitude"], 180, "longitude"),
            "uv_from": _whole(value["uv_from"], UV, "the UV level")}


def pollen(value: Any) -> dict:
    value = _exactly(value, ("level", "kinds"))
    _need(isinstance(value["level"], str) and value["level"] in POLLEN_LEVELS, "unknown pollen level")
    kinds = _choices(value["kinds"], POLLENS, "kinds of pollen")
    _need(bool(kinds), "choose at least one kind of pollen")
    return {"level": value["level"], "kinds": sorted(kinds, key=list(POLLENS).index)}


def tube(value: Any) -> dict:
    value = _exactly(value, ("favourite", "modes"))
    _need(value["favourite"] in ("",) + LINES, "unknown line")
    modes = _choices(value["modes"], MODES, "kinds of line")
    _need(bool(modes), "choose at least one kind of line")
    return {"favourite": value["favourite"], "modes": sorted(modes, key=list(MODES).index)}


def feed_url(value: Any) -> str:
    """A public https address. The reporter checks again, after looking the name up."""
    _need(isinstance(value, str) and 10 <= len(value) <= 300 and value.isascii() and value.isprintable()
          and not set(value) & set(" \\\"'<>`{}|^"), "a feed address must look like https://example.com/feed")
    try:
        parts = urlsplit(value)
        host, port = parts.hostname or "", parts.port
    except ValueError:
        raise ValueError("a feed address must look like https://example.com/feed") from None
    _need(parts.scheme == "https", "feed addresses must start with https://")
    _need(parts.username is None and parts.password is None and port in (None, 443) and not parts.fragment,
          "a feed address must look like https://example.com/feed")
    _need("." in host.strip(".") and "%" not in host, "a feed address needs a full name")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("a feed address must be a name, not numbers")
    _need(not host.rsplit(".", 1)[-1].isdigit(), "a feed address must be a name, not numbers")
    _need(not host.endswith((".local", ".lan", ".home", ".internal", ".localhost", ".arpa")), "a feed address must be public")
    return value


def news(value: Any) -> dict:
    value = _exactly(value, ("count", "feeds"))
    feeds = value["feeds"]
    _need(isinstance(feeds, list) and 1 <= len(feeds) <= MAX_FEEDS, f"choose 1 to {MAX_FEEDS} feeds")
    clean = []
    for feed in feeds:
        feed = _exactly(feed, ("name", "url"))
        clean.append({"name": _text(feed["name"], 20, "a feed's name"), "url": feed_url(feed["url"])})
    names = [feed["name"] for feed in clean]
    _need(len(names) == len(set(names)), "two feeds have the same name")
    return {"count": _whole(value["count"], COUNT, "the number of headlines"), "feeds": clean}


def _station(value: Any, what: str) -> str:
    _need(isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper(),
          f"{what} must be a three-letter code")
    return value


def trains(value: Any) -> dict:
    given = value
    if isinstance(value, dict):  # saved before these existed: only what was chosen counts
        value = {"offset": 0, "count": 3, "days": list(DAYS[:5]), **value}
    value = _exactly(value, ("station", "towards", "offset", "count", "days"))
    days = _choices(value["days"], DAYS, "days")
    station = _station(value["station"], "the station")
    towards = "" if value["towards"] == "" else _station(value["towards"], "the destination")
    _need(station != towards, "the destination is the station itself")
    offset = _whole(value["offset"], OFFSET, "the minutes to skip")
    _need(offset % STEP == 0, f"the minutes to skip must be a multiple of {STEP}")
    checked = {"station": station, "towards": towards, "offset": offset, "count": _whole(value["count"], TRAINS, "the number of trains"),
               "days": sorted(days, key=DAYS.index)}
    return {key: checked[key] for key in checked if key in given}


def warnings(value: Any) -> dict:
    value = _exactly(value, ("region",))
    _need(isinstance(value["region"], str) and value["region"] in REGIONS, "unknown region")
    return dict(value)


def _presses(value: Any, limits: Tuple[int, int], what: str) -> dict:
    _need(isinstance(value, dict) and set(value) <= set(PRESSABLE), f"unknown {what}")
    return {name: _whole(value[name], limits, what) for name in PRESSABLE if name in value}


def button(value: Any) -> dict:
    """How many taps, or seconds of holding, print what. Several things can share a press."""
    value = _exactly(value, ("taps", "holds"))
    return {"taps": _presses(value["taps"], TAPS, "taps"), "holds": _presses(value["holds"], HOLDS, "seconds of holding")}


def sudoku(value: Any) -> dict:
    value = _exactly(value, ("level",))
    _need(isinstance(value["level"], str) and value["level"] in SUDOKU, "unknown difficulty")
    return dict(value)


def printer(value: Any) -> dict:
    value = _exactly(value, ("heat_time",))
    return {"heat_time": _whole(value["heat_time"], HEAT, "the heat")}


GROUPS: Dict[str, Callable[[Any], Any]] = {
    "sections": sections, "schedule": schedule, "weather": weather, "warnings": warnings, "pollen": pollen, "tube": tube,
    "news": news, "sudoku": sudoku, "trains": trains, "button": button, "printer": printer,
}


def check(raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    """The groups that can be used, and what is wrong with the rest."""
    if not isinstance(raw, dict):
        return {}, ["the settings file is not a set of settings"]
    good: Dict[str, Any] = {}
    problems: List[str] = []
    for name, value in raw.items():
        if name not in GROUPS:
            problems.append("an unknown group of settings")
            continue
        try:
            good[name] = GROUPS[name](value)
        except (ValueError, TypeError, RecursionError) as exc:
            problems.append(f"{name}: {exc}" if isinstance(exc, ValueError) else f"{name}: damaged")
    return good, problems[:MAX_PROBLEMS]


def _read(path: Path) -> Tuple[Any, List[str]]:
    """Never raises. The file is written by another account, so links are not followed."""
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        # Nothing chosen yet, unless the small disk it belongs on did not come up.
        lost = path.parent.parent.is_dir() and not path.parent.is_dir()
        return {}, ["the settings disk is missing"] if lost else []
    except OSError:
        return {}, [UNREADABLE]
    try:
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            return {}, ["the settings file is not a file"]
        data = os.read(handle, MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {}, ["the settings file is too long"]
        return json.loads(data), []
    except OSError:
        return {}, [UNREADABLE]
    except (ValueError, RecursionError):
        return {}, ["the settings file is damaged"]
    finally:
        os.close(handle)


def load(path: Path = PATH) -> Tuple[Dict[str, Any], List[str]]:
    """Never raises."""
    found, problems = _read(path)
    return ({}, problems) if problems else check(found)


def stored(path: Path = PATH) -> List[str]:
    """The groups in the file, whether they can be used or not."""
    found = _read(path)[0]
    return [name for name in found if name in GROUPS] if isinstance(found, dict) else []


def change(name: str, value: Any, path: Path = PATH) -> None:
    """Replaces one group, or drops it if `value` is None. The others stay as they are, also
    those this version cannot read: after going back to an older one they come back too."""
    found, problems = _read(path)
    if UNREADABLE in problems:
        raise OSError(UNREADABLE)  # what is in there may still be good
    everything = dict(found) if isinstance(found, dict) else {}
    everything.pop(name, None)
    if value is not None:
        everything[name] = GROUPS[name](value)
    if len(_data(everything)) > MAX_BYTES:
        everything = check(everything)[0]
    _write(everything, path)


def save(values: Dict[str, Any], path: Path = PATH) -> None:
    good, problems = check(values)
    if problems:
        raise ValueError(problems[0])
    _write(good, path)


def _data(values: Dict[str, Any]) -> bytes:
    return (json.dumps(values, indent=1) + "\n").encode()


def _write(values: Dict[str, Any], path: Path) -> None:
    data = _data(values)
    _need(len(data) <= MAX_BYTES, "too many settings")
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    handle = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def replace(tmp: Path, path: Path) -> None:
    """So that not even a power cut brings the old file back."""
    tmp.replace(path)
    folder = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """`over` on top of `base`, group by group; both keep their own copies."""
    merged = dict(base)
    for name, value in over.items():
        under = base.get(name, {})
        merged[name] = {**under, **value} if isinstance(value, dict) and isinstance(under, dict) else value
    return merged
