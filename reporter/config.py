"""Loads config.toml, with the web interface's settings over it, into one read-only object."""

import logging
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from datetime import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import settings

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DAY_NAMES = settings.DAYS
LOCAL = Path(os.environ.get("REPORTER_LOCAL", ROOT / "config.local.toml"))  # this home's own values, not in git
NO_CHANGES = Path("/nonexistent/web/settings/settings.json")


@dataclass(frozen=True)
class Schedule:
    days: Tuple[int, ...]  # Monday is 0
    time: time
    catch_up_until: time


@dataclass(frozen=True)
class PrinterSettings:
    port: str = "/dev/serial0"
    baudrate: int = 19200
    heat_dots: int = 7
    heat_time: int = 70
    heat_interval: int = 40
    density: int = 10
    break_time: int = 2
    row_time: float = 0.03


@dataclass(frozen=True)
class ButtonSettings:
    button_pin: int = 23
    led_pin: int = 18
    # What each press prints: (block, taps) and (block, seconds). See settings.PRESSABLE.
    taps: Tuple[Tuple[str, int], ...] = (("receipt", 1), ("wifi", 2), ("departures", 3), ("poster", 5))
    holds: Tuple[Tuple[str, int], ...] = (("health", 2),)

    def for_taps(self, count: int) -> List[str]:
        return [name for name, taps in self.taps if taps == count]

    def for_hold(self, seconds: float) -> Optional[List[str]]:
        """What the longest hold reached prints; None if it was too short to be a hold."""
        reached = max((s for _, s in self.holds if s <= seconds), default=None)
        return None if reached is None else [name for name, s in self.holds if s == reached]


@dataclass(frozen=True)
class WeatherSettings:
    latitude: float = 51.5085
    longitude: float = -0.1257
    place: str = "London"  # a label only
    uv_from: int = 3

    @property
    def position(self) -> Dict[str, float]:
        """What the weather sites are asked for: to about a kilometre, not to the front door."""
        return {"latitude": round(self.latitude, 2), "longitude": round(self.longitude, 2)}


@dataclass(frozen=True)
class WarningSettings:
    region: str = "se"  # the Met Office's code, see settings.REGIONS


@dataclass(frozen=True)
class PollenSettings:
    level: str = "moderate"  # print from this level
    kinds: Tuple[str, ...] = ("grass", "birch", "alder", "mugwort")


@dataclass(frozen=True)
class TubeSettings:
    favourite: str = ""
    modes: Tuple[str, ...] = ("tube", "overground", "elizabeth-line", "dlr")


@dataclass(frozen=True)
class TrainSettings:
    station: str = "CLJ"
    towards: str = ""  # only trains calling here, if set
    minutes: int = 60
    # For the receipt only: skip trains this soon, show this many, on these days.
    offset: int = 0
    count: int = 3
    days: Tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri")


@dataclass(frozen=True)
class Feed:
    name: str
    url: str


@dataclass(frozen=True)
class NewsSettings:
    count: int = 5
    feeds: Tuple[Feed, ...] = ()


@dataclass(frozen=True)
class SudokuSettings:
    level: str = "medium"


@dataclass(frozen=True)
class EventsSettings:
    inbox: str = "/var/lib/receipt-inbox/drop/events.txt"
    host: str = ""  # name on the drop box's certificate, for the web interface and the health page


@dataclass(frozen=True)
class Config:
    timezone: str
    sections: Tuple[str, ...]
    schedule: Tuple[Schedule, ...]
    printer: PrinterSettings = field(default_factory=PrinterSettings)
    button: ButtonSettings = field(default_factory=ButtonSettings)
    weather: WeatherSettings = field(default_factory=WeatherSettings)
    warnings: WarningSettings = field(default_factory=WarningSettings)
    pollen: PollenSettings = field(default_factory=PollenSettings)
    tube: TubeSettings = field(default_factory=TubeSettings)
    news: NewsSettings = field(default_factory=NewsSettings)
    trains: TrainSettings = field(default_factory=TrainSettings)
    sudoku: SudokuSettings = field(default_factory=SudokuSettings)
    events: EventsSettings = field(default_factory=EventsSettings)
    problems: Tuple[str, ...] = ()  # with the web interface's settings

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


GROUPS: Dict[str, type] = {
    "printer": PrinterSettings, "button": ButtonSettings, "weather": WeatherSettings, "warnings": WarningSettings, "pollen": PollenSettings,
    "tube": TubeSettings, "news": NewsSettings, "trains": TrainSettings, "sudoku": SudokuSettings, "events": EventsSettings,
}


def _parse_days(names: List[str]) -> Tuple[int, ...]:
    unknown = [n for n in names if n not in DAY_NAMES]
    if unknown or not names:
        raise ValueError(f"schedule.days must be one or more of {', '.join(DAY_NAMES)}")
    return tuple(sorted({DAY_NAMES.index(n) for n in names}))


def _parse_schedule(slots: List[dict]) -> Tuple[Schedule, ...]:
    if not isinstance(slots, list):
        raise ValueError("the schedule needs double brackets: [[schedule]]")
    parsed = []
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {"days", "time", "catch_up_until"}:
            raise ValueError("each [[schedule]] needs days, time and catch_up_until, and nothing else")
        schedule = Schedule(days=_parse_days(slot["days"]), time=time.fromisoformat(slot["time"]),
                            catch_up_until=time.fromisoformat(slot["catch_up_until"]))
        if schedule.catch_up_until <= schedule.time:
            raise ValueError("schedule.catch_up_until must be later than schedule.time")
        parsed.append(schedule)
    days = [day for schedule in parsed for day in schedule.days]
    if not parsed or len(days) != len(set(days)):
        raise ValueError("schedule needs at least one slot, and each day in one slot only")
    return tuple(parsed)


def _known(given: Any, kind: type, where: str) -> Dict[str, Any]:
    """Refuses what is not a setting: a misspelt one would otherwise do nothing."""
    if not isinstance(given, dict):
        raise ValueError(f"{where} must be a group of settings")
    unknown = sorted(set(given) - {f.name for f in fields(kind)})
    if unknown:
        raise ValueError(f"{where} has no setting called {', '.join(unknown)}")
    return given


def _frozen(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else tuple(value.items()) if isinstance(value, dict) else value


def _build(raw: Dict[str, Any], problems: List[str]) -> Config:
    raw = _known(dict(raw), Config, "the file")
    groups: Dict[str, Any] = {}
    for name, kind in GROUPS.items():
        given = _known(raw.get(name, {}), kind, f"[{name}]")
        for key in ("taps", "holds"):
            if not isinstance(given.get(key, {}), dict):
                raise ValueError(f"[{name}] {key} must look like {{ receipt = 1 }}")
        if name == "news":
            given = {**given, "feeds": [Feed(**_known(feed, Feed, "[[news.feeds]]")) for feed in given.get("feeds", [])]}
        groups[name] = kind(**{key: _frozen(value) for key, value in given.items()})
    return Config(timezone=raw["timezone"], sections=tuple(raw["sections"]),
                  schedule=_parse_schedule(raw["schedule"]) if raw["schedule"] else (), problems=tuple(problems), **groups)


def _read(path: Path) -> Dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from None


def load(path: Path = ROOT / "config.toml", changes: Optional[Path] = None) -> Config:
    """Raises ValueError if config.toml or config.local.toml is wrong. `changes`, the web
    settings, can never make this fail."""
    raw = _read(Path(path))
    if LOCAL.is_file():
        raw = settings.merge(raw, _read(LOCAL))
    _parse_schedule(raw["schedule"])
    config = _build(raw, [])
    config.tz  # fail now, not at 08:00, if the timezone name is wrong
    over, problems = settings.load(settings.PATH if changes is None else changes)
    try:
        config = _build(settings.merge(raw, over), problems)
    except Exception as exc:
        config = _build(raw, problems + [f"the settings do not fit together ({type(exc).__name__})"])
    for problem in config.problems:
        log.warning("web settings: %s", problem)
    return config


def not_offered() -> List[str]:
    """What the files say that the web interface, which is stricter, does not allow."""
    return settings.check(as_settings(load(changes=NO_CHANGES)))[1]


def as_settings(cfg: Config) -> Dict[str, Any]:
    """This configuration in the shape the web interface uses."""
    plain = asdict(cfg)
    values: Dict[str, Any] = {
        "sections": list(cfg.sections),
        "schedule": [{"days": [DAY_NAMES[d] for d in slot.days], "time": f"{slot.time:%H:%M}",
                      "catch_up_until": f"{slot.catch_up_until:%H:%M}"} for slot in cfg.schedule],
        "weather": {k: plain["weather"][k] for k in ("place", "latitude", "longitude", "uv_from")},
        "pollen": {"level": cfg.pollen.level, "kinds": list(cfg.pollen.kinds)},
        "tube": {"favourite": cfg.tube.favourite, "modes": list(cfg.tube.modes)},
        "news": {"count": cfg.news.count, "feeds": [asdict(feed) for feed in cfg.news.feeds]},
        "sudoku": {"level": cfg.sudoku.level},
        "warnings": {"region": cfg.warnings.region},
        "trains": {**{k: plain["trains"][k] for k in ("station", "towards", "offset", "count")}, "days": list(cfg.trains.days)},
        "button": {"taps": dict(cfg.button.taps), "holds": dict(cfg.button.holds)},
        "printer": {"heat_time": cfg.printer.heat_time},
    }
    return values


def state_dir(create: bool = True) -> Path:
    """systemd sets STATE_DIRECTORY; fall back to the home dir for manual runs."""
    path = Path(os.environ.get("STATE_DIRECTORY") or Path.home() / ".local/state/reporter")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
