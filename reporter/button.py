"""Front-panel button. [button] in the settings says which blocks a number of taps, or some
seconds of holding, print; holding 5 seconds always shuts the Pi down safely.

Always running, so it also keeps the web interface's status fresh and, like the timer, deletes
lists from the phone once their day is over.
"""

import logging
import subprocess
import threading
import time
from dataclasses import replace
from datetime import datetime
from functools import partial
from typing import Callable, List, Optional

from PIL import Image

from . import config, jobs, lists, render, report
from .blocks import block
from .config import Config
from .printer import print_receipt

log = logging.getLogger(__name__)

TIDY_EVERY = 600  # seconds
SHUTDOWN = 5  # seconds; longer than any hold that can be chosen
NEXT_TAP = 0.8  # seconds to wait for another tap; 0.5 split somebody's three taps in two


class Panel:
    def __init__(self, load: Callable[[], Config], led) -> None:
        self._load, self._last = load, None
        self.led = led
        self.busy = threading.Lock()
        self.going_down = False
        self.was_held = False
        self.pressed_at = 0.0
        self.taps = 0
        self.timer: Optional[threading.Timer] = None
        self.tap_lock = threading.Lock()

    def load(self) -> Config:
        """For every press, so changed settings count at once. A mistake in the files must not
        take the button away, or the Pi could not be shut down."""
        try:
            self._last = self._load()
        except Exception as exc:
            if self._last is None:
                raise
            log.warning("the settings cannot be used, keeping the last ones: %s", type(exc).__name__)
        return self._last

    def pressed(self) -> None:
        self.was_held = False
        self.pressed_at = time.monotonic()
        with self.tap_lock:
            self._stop_waiting()

    def released(self) -> None:
        if self.was_held or not self.pressed_at:  # or already down when the service started
            return
        seconds, self.pressed_at = time.monotonic() - self.pressed_at, 0.0
        held = self.load().button.for_hold(seconds)
        if held is not None:
            with self.tap_lock:
                self.taps = 0
            self._print(held, "hold")
            return
        with self.tap_lock:
            self._stop_waiting()
            self.taps += 1
            self.timer = threading.Timer(NEXT_TAP, self._taps_done)
            self.timer.daemon = True
            self.timer.start()

    def _stop_waiting(self) -> None:
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def _taps_done(self) -> None:
        with self.tap_lock:
            taps, self.taps = self.taps, 0
        if taps:
            self._print(self.load().button.for_taps(taps), f"{taps} taps")

    def held(self) -> None:
        """Never waits behind something that is stuck."""
        self.was_held = True
        with self.tap_lock:
            self.taps = 0
            if self.going_down:
                return
            self.going_down = True
        try:
            threading.Thread(target=self._shut_down, daemon=True).start()
        except RuntimeError:  # no threads left
            self._shut_down()

    def _print(self, names: List[str], press: str) -> None:
        log.info("button, %s: %s", press, ", ".join(names) or "nothing")
        if names:
            self._start(partial(self._print_blocks, names))

    def _start(self, action) -> None:
        """Run in the background; ignore presses while something is in progress."""
        if self.busy.acquire(blocking=False):
            try:
                threading.Thread(target=self._run, args=(action,), daemon=True).start()
            except RuntimeError:
                self.busy.release()
                raise
        else:
            log.info("busy, ignoring button")

    def _run(self, action) -> None:
        self.led.on()
        try:
            action()
        except Exception:
            log.exception("button action failed")
        finally:
            self.led.off()
            self.busy.release()

    def _print_blocks(self, names: List[str]) -> None:
        cfg = self.load()
        asked = [name for name in names if name != "receipt"]
        if "trains" in asked:  # its days are for the receipt
            cfg = replace(cfg, trains=replace(cfg.trains, days=config.DAY_NAMES))
        everything = list(dict.fromkeys(each for name in names for each in (cfg.sections if name == "receipt" else (name,))))
        print_receipt(cfg.printer, report.build(cfg, datetime.now(cfg.tz), names=everything, asked=asked).image)

    def _shut_down(self) -> None:
        log.info("button held, shutting down")
        self.led.on()
        try:
            print_receipt(self.load().printer, goodbye())
        except Exception:
            log.exception("goodbye print failed")
        try:
            subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "poweroff"], check=True)
        except (OSError, subprocess.CalledProcessError):
            log.exception("cannot shut down")
            self.led.off()
            self.going_down = False  # the next hold tries again


def goodbye() -> Image.Image:
    canvas = render.Canvas()
    block(canvas, "moon", "Shutting down", ["Wait for the green light to stop, then unplug."])
    return render.to_bitmap(canvas.finish())


def tidy(cfg: Config) -> None:
    """Never let a problem here stop the button."""
    if lists.clear_old(cfg, datetime.now(cfg.tz).date()):
        log.info("deleted a list whose day is over")
    jobs.refresh_status(cfg)


def run(cfg: Config) -> None:
    from gpiozero import LED, Button  # only available on the Pi

    led = LED(cfg.button.led_pin)
    button = Button(cfg.button.button_pin, pull_up=True, bounce_time=0.03,
                    hold_time=SHUTDOWN)
    panel = Panel(config.load, led)
    button.when_pressed = panel.pressed
    button.when_released = panel.released
    button.when_held = panel.held
    log.info("watching button on GPIO %d", cfg.button.button_pin)
    while True:  # the button itself works in gpiozero's own threads
        tidy(panel.load())
        time.sleep(TIDY_EVERY)
