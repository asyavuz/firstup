"""Decides whether a scheduled run should print.

The timer alone is not enough. The Pi has no battery-backed clock, so after a
power cut it boots with a stale date and the clock then jumps forward, which can
fire a timer at the wrong moment. Every scheduled run is therefore re-checked
here against a synchronised clock.
"""

import logging
import os
import subprocess
import time
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

from . import settings
from .config import Schedule

log = logging.getLogger(__name__)


class Decision(NamedTuple):
    run: bool
    reason: str


def decide(now: datetime, slots: Sequence[Schedule], last_printed: Optional[date]) -> Decision:
    schedule = next((slot for slot in slots if now.weekday() in slot.days), None)
    if schedule is None:
        return Decision(False, f"{now:%A} is not a printing day")
    if last_printed == now.date():
        return Decision(False, "already printed today")
    if now.time() < schedule.time:
        return Decision(False, f"too early ({now:%H:%M}), prints at {schedule.time:%H:%M}")
    if now.time() > schedule.catch_up_until:
        return Decision(False, f"too late ({now:%H:%M}), cut-off is {schedule.catch_up_until:%H:%M}")
    return Decision(True, "due")


def read_stamp(path: Path) -> Optional[date]:
    try:
        return date.fromisoformat(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_stamp(path: Path, day: date) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as handle:
        handle.write(day.isoformat() + "\n")
        handle.flush()
        os.fsync(handle.fileno())  # must survive a power cut during the print
    settings.replace(tmp, path)


def clock_is_synchronised() -> bool:
    out = subprocess.run(
        ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return out.stdout.strip() == "yes"


def wait_for_clock(timeout: float = 180, poll: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if clock_is_synchronised():
                return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("cannot read clock status: %s", exc)
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)
