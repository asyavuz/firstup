"""Carries out what the web interface asks for.

The web program cannot print, fetch anything or see this account's files. It leaves an
empty file, named after what it wants, in one folder; systemd then runs `reporter requests`
as the normal account. Nothing is read from those files, so there is nothing in them to
trust. Answers go to a second folder, which the web program can only read.

Calendar titles and the Wi-Fi details never go there.
"""

import io
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PIL import Image

from . import calibrate, config, health, lists, render, report, schedule, settings, trains
from .config import Config
from .printer import PrinterError, print_receipt
from .sections import TITLES

log = logging.getLogger(__name__)

REQUESTS, OUT = settings.BASE / "requests", settings.BASE / "out"
MAX_ROUNDS = 10
HANDED = "rail"
PAPER = ("receipt", "trains", "health", "calibrate")
PAUSE, PER_DAY = timedelta(seconds=20), 10  # so a web program gone wrong cannot empty the roll


def take(folder: Path, handed: Optional[Dict[str, str]] = None, started: Callable[[str], None] = lambda kind: None) -> List[str]:
    """What is asked for. Removed before it is done, so nothing can run again and again."""
    wanted = []
    for name in sorted(os.listdir(folder)):
        path = folder / name
        if name == HANDED and handed is not None:  # the only one that holds anything: a train token
            for _ in range(40):  # it is there a moment before its content
                handed[name] = (lists.read(path) or "").strip()
                if handed[name]:
                    break
                time.sleep(0.05)
        if name in KINDS:
            started(name)  # before it goes, or an older answer would count in between
        try:
            path.unlink()
        except (IsADirectoryError, PermissionError):
            try:
                path.rmdir()
            except OSError:
                log.warning("cannot clear something odd from the requests folder")
            continue
        except FileNotFoundError:
            continue
        if name in KINDS:
            wanted.append(name)
    return wanted


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    try:
        tmp.write_bytes(data)
        tmp.chmod(0o640)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _save_png(image, name: str) -> None:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    _write(OUT / name, buffer.getvalue())


def status(cfg: Config, now: datetime) -> dict:
    defaults = config.load(changes=config.NO_CHANGES)
    last = schedule.read_stamp(health.stamp())
    return {
        "at": now.isoformat(timespec="seconds"),
        "health": health.collect(cfg, now),
        "last_print": last.isoformat() if last else "",
        "defaults": config.as_settings(defaults),
        "problems": list(cfg.problems) + [f"config.local.toml, {problem}" for problem in config.not_offered()],
        "rail_key": trains.load_token() is not None,
    }


def write_status(cfg: Config, now: datetime) -> str:
    _write(OUT / "status.json", json.dumps(status(cfg, now)).encode())
    return "Checked"


def refresh_status(cfg: Config) -> None:
    """For the button service; does nothing if there is no web interface."""
    try:
        if OUT.is_dir():
            write_status(cfg, datetime.now(cfg.tz))
    except Exception as exc:
        log.warning("cannot write the web interface's status: %s", type(exc).__name__)


def _preview(cfg: Config, now: datetime) -> str:
    """Every block is drawn, also those that are off, so that switching one shows at once."""
    others = [name for name in settings.SECTIONS if name not in cfg.sections and name != "departures"]  # that asks for a whole hour
    result = report.build(cfg, now, on_screen=True, names=[*cfg.sections, *others])
    pieces = [(name, image) for name, image in result.pieces if name in settings.SECTIONS]
    chosen = [image for name, image in pieces if name in cfg.sections]
    _save_png(render.to_bitmap(render.stack(chosen or [render.notice("Nothing to print today")])) if pieces else result.image, "preview.png")
    places, top = {}, 0
    for name, image in pieces:
        places[name] = [top, image.height]
        top += image.height
    if pieces:
        sheet = Image.new("L", (render.WIDTH, top), 255)
        for name, image in pieces:
            sheet.paste(image, (0, places[name][0]))
        _save_png(render.to_bitmap(sheet), "blocks.png")
    _write(OUT / "blocks.json", json.dumps({"height": top, "places": places}).encode())
    result = result._replace(failed=[name for name in result.failed if name in cfg.sections])
    said = [f"Unavailable now: {', '.join(TITLES.get(name, name) for name in result.failed)}"] if result.failed else []
    if result.missing:
        said.append(f"No headlines from: {', '.join(result.missing)}. Is the address right?")
    return ". ".join(said) or "Ready"


def _preview_trains(cfg: Config, now: datetime) -> str:
    _save_png(trains.build(cfg.trains, now), "trains.png")
    return "Ready"


def _sent(answered: bool) -> str:
    return "Sent to the printer" if answered else "Sent, but the printer did not answer afterwards"


def _receipt(cfg: Config, now: datetime) -> str:
    return _sent(print_receipt(cfg.printer, report.build(cfg, now).image))


def _trains(cfg: Config, now: datetime) -> str:
    return _sent(print_receipt(cfg.printer, trains.build(cfg.trains, now)))


def _health(cfg: Config, now: datetime) -> str:
    return _sent(print_receipt(cfg.printer, health.page(cfg, now)))


def _calibrate(cfg: Config, now: datetime) -> str:
    return _sent(calibrate.run(cfg.printer))


_handed: Dict[str, str] = {}  # never logged, never written to `out`


def _rail(cfg: Config, now: datetime) -> str:
    said = trains.keep(_handed.pop(HANDED, ""), cfg.trains, now)
    write_status(cfg, now)
    return said


def _rail_forget(cfg: Config, now: datetime) -> str:
    trains.PATH.unlink(missing_ok=True)
    write_status(cfg, now)
    return "Forgotten. The trains are left out from now on"


KINDS: Dict[str, Callable[[Config, datetime], str]] = {
    "status": write_status, "preview": _preview, "preview-trains": _preview_trains,
    "receipt": _receipt, "trains": _trains, "health": _health, "calibrate": _calibrate,
    "rail": _rail, "rail-forget": _rail_forget,
}


def _result(kind: str, state: str, text: str, now: datetime) -> None:
    _write(OUT / f"result-{kind}.json",
           json.dumps({"state": state, "text": text, "at": now.isoformat(timespec="seconds")}).encode())


def _saved(name: str) -> dict:
    try:
        data = json.loads((OUT / name).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _count_paper(kind: str, now: datetime) -> dict:
    """Raises if there has been enough of it; gives back how it was before. Kept where the web
    program can only read."""
    used = _saved("paper.json")
    before = dict(used)
    today = now.date().isoformat()
    count = used.get("count", 0) if used.get("day") == today else 0
    last = used.get(kind) or ""
    if count >= PER_DAY:
        raise TooMuch(f"{PER_DAY} a day from here is the limit. The button still works")
    if last and timedelta(0) <= now - datetime.fromisoformat(last) < PAUSE:
        raise TooMuch("that came out a moment ago")
    used.update({"day": today, "count": count + 1, kind: now.isoformat()})
    _write(OUT / "paper.json", json.dumps(used).encode())
    return before


class TooMuch(Exception):
    pass


def do(kind: str) -> None:
    cfg = config.load()
    _result(kind, "working", "", datetime.now(cfg.tz))
    before = None
    try:
        if kind in PAPER:
            before = _count_paper(kind, datetime.now(cfg.tz))
        state, text = "done", KINDS[kind](cfg, datetime.now(cfg.tz))
    except trains.NoToken as exc:
        state, text = "failed", f"Not saved: {exc}"
    except TooMuch as exc:
        log.warning("%s: refused", kind)
        state, text = "failed", str(exc)
    except PrinterError as exc:
        log.warning("%s: %s", kind, exc)
        state, text = "failed", str(exc)
        if before is not None:  # nothing came out, so it does not count
            _write(OUT / "paper.json", json.dumps(before).encode())
    except Exception as exc:
        log.exception("%s failed", kind)
        state, text = "failed", f"It went wrong ({type(exc).__name__})"
    _result(kind, state, text, datetime.now(cfg.tz))
    if kind != "status":
        log.info("%s: %s", kind, state)


def refuse(text: str) -> int:
    """If the settings cannot be read: an answer all the same, or systemd would ask for ever."""
    for kind in take(REQUESTS):
        _result(kind, "failed", text, datetime.now().astimezone())
    return 1


def run() -> int:
    for _ in range(MAX_ROUNDS):
        wanted = take(REQUESTS, _handed, lambda kind: _result(kind, "working", "", datetime.now().astimezone()))
        if not wanted:
            break
        for kind in wanted:
            do(kind)
    return 0
