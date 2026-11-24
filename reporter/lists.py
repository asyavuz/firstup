"""The lists a phone has sent: reading them, and deleting them in time. Standard library only
and nothing that draws, because the timer runs this every five minutes.

Another account writes these files, so no link is followed and nothing is waited for."""

import logging
import os
import stat
import time
from datetime import date
from itertools import islice
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

MAX_BYTES = 8192
HALF_SENT = 600  # seconds after which a list that only half arrived is not coming
MAX_FILES = 1000


def paths(cfg) -> Tuple[Path, Path]:
    """The calendar's and the reminders'."""
    inbox = Path(cfg.events.inbox)
    return inbox, inbox.with_name("reminders.txt")


def read(path: Path) -> Optional[str]:
    """None if there is no such list."""
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        return os.read(handle, MAX_BYTES).decode("utf-8", "ignore") if stat.S_ISREG(os.fstat(handle).st_mode) else None
    except OSError:
        return None
    finally:
        os.close(handle)


def arrived(path: Path) -> Optional[float]:
    """When it came, or None."""
    try:
        info = path.lstat()
    except OSError:
        return None
    return info.st_mtime if stat.S_ISREG(info.st_mode) else None


def clear_old(cfg, today: date) -> bool:
    """Deletes lists whose day is over or that make no sense, and whatever else is in the drop
    box's folder for long. Never raises."""
    files = paths(cfg)
    folder = files[0].parent
    try:
        theirs = folder.stat().st_uid != os.getuid()  # the drop box's own folder, not one somebody chose
        with os.scandir(folder) as entries:
            found = [folder / entry.name for entry in islice(entries, MAX_FILES)]
        others = [path for path in found if path not in files and (theirs or path.name.startswith(".in."))]
    except OSError:
        others = []
    return any([_try(_clear, path, today) for path in files] + [_try(_clear_odd, path) for path in others])


def _try(step, *args) -> bool:
    try:
        return step(*args)
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("cannot tidy a list: %s", type(exc).__name__)
        return False


def _clear(path: Path, today: date) -> bool:
    path.lstat()  # raises if there is none
    try:
        if date.fromisoformat((read(path) or "").split("\n", 1)[0].strip()) >= today:
            return False
    except ValueError:
        pass
    return _remove(path)


def _clear_odd(path: Path) -> bool:
    return abs(time.time() - path.lstat().st_mtime) > HALF_SENT and _remove(path)


def _remove(path: Path) -> bool:
    try:
        path.unlink()
    except (IsADirectoryError, PermissionError):  # a folder
        path.rmdir()
    return True
