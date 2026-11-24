"""Minimal driver for a 58 mm TTL thermal printer (CSN-A2 and its relatives)."""

import logging
import time
from typing import Callable, Iterator, Optional

import serial
from PIL import Image

from .config import PrinterSettings

log = logging.getLogger(__name__)

ROW_BYTES = 48  # 384 dots
PAPER_OUT = 0x04


class PrinterError(RuntimeError):
    pass


def rows(img: Image.Image) -> Iterator[bytes]:
    """Pack a 1-bit image into 48-byte rows; a set bit burns a dot."""
    if img.mode != "1" or img.width != ROW_BYTES * 8:
        raise ValueError(f"expected a 1-bit image {ROW_BYTES * 8} wide, got {img.mode} {img.size}")
    data = bytes(b ^ 0xFF for b in img.tobytes())
    for start in range(0, len(data), ROW_BYTES):
        yield data[start:start + ROW_BYTES]


class ThermalPrinter:
    def __init__(self, settings: PrinterSettings) -> None:
        self.settings = settings
        self._port: Optional[serial.Serial] = None

    def __enter__(self) -> "ThermalPrinter":
        self._port = self._open()
        try:
            self._initialise()
        except BaseException:
            self._port.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._port.close()

    def _open(self, wait: float = 180) -> serial.Serial:
        """Open the port exclusively, waiting if another print is in progress."""
        deadline = time.monotonic() + wait
        while True:
            try:
                return serial.Serial(self.settings.port, self.settings.baudrate,
                                     timeout=2, write_timeout=30, exclusive=True)
            except serial.SerialException as exc:
                if "lock" not in str(exc).lower() or time.monotonic() >= deadline:
                    raise PrinterError(f"cannot open {self.settings.port}: {exc}") from exc
                time.sleep(2)

    def _send(self, data: bytes) -> None:
        self._port.write(data)
        self._port.flush()

    def _initialise(self) -> None:
        self._send(b"\xff")            # wake
        time.sleep(0.1)
        self._send(b"\x1b8\x00\x00")   # ESC 8: never sleep while we are printing
        self._send(b"\x1b@")           # ESC @: reset
        time.sleep(0.5)
        self.apply_heat()

    def apply_heat(self) -> None:
        s = self.settings
        self._send(bytes((0x1B, 0x37, s.heat_dots, s.heat_time, s.heat_interval)))
        self._send(bytes((0x12, 0x23, (s.break_time << 5) | s.density)))

    def status(self, timeout: float = 2) -> Optional[int]:
        """Status byte, or None if the printer does not answer."""
        self._port.reset_input_buffer()
        self._port.timeout = timeout
        self._send(b"\x1bv\x00")
        reply = self._port.read(1)
        return reply[0] if reply else None

    def _resync(self) -> None:
        """Recover a printer left waiting for the rest of a garbled command.

        NULs fill whatever it is waiting for (blank dots at worst) and are
        ignored otherwise.
        """
        self._send(b"\x00" * 256)
        time.sleep(0.5)
        self._initialise()

    def check_ready(self, attempts: int = 5) -> None:
        status = self.status()
        for attempt in range(1, attempts):
            if status is not None:
                break
            log.warning("no answer from printer, resyncing (%d/%d)", attempt, attempts - 1)
            self._resync()
            status = self.status()
        if status is None:
            raise PrinterError("printer does not answer (powered off or unplugged?)")
        if status & PAPER_OUT:
            raise PrinterError("printer is out of paper")

    def print_image(self, img: Image.Image, feed_lines: int = 3) -> None:
        """Stream one row per command, paced so the printer's small buffer never overruns.

        Do not drain the port after each row: that takes 50 ms instead of the 27 ms a
        row needs on the wire, the motor stops between rows and the text ghosts.
        """
        next_row = time.monotonic()
        for row in rows(img):
            self._port.write(b"\x12*\x01" + bytes((ROW_BYTES,)) + row)
            next_row += self.settings.row_time
            time.sleep(max(0.0, next_row - time.monotonic()))
        self._port.flush()
        if feed_lines:
            self.feed(feed_lines)

    def feed(self, lines: int) -> None:
        self._send(bytes((0x1B, 0x64, lines)))

    def confirm_done(self) -> bool:
        """Check the printer still answers and has paper after a print.

        This does NOT prove the rows reached the paper: it has answered normally after
        dropping more than half of them. Only eyes can tell.

        Called once the paper has moved, so problems are logged, not raised:
        raising would make the caller print the whole receipt again.
        """
        status = self.status(timeout=20)
        for _ in range(2):  # a single reply can get lost
            if status is None:
                status = self.status()
        if status is None:
            log.warning("printer did not confirm the end of the print")
            return False
        if status & PAPER_OUT:
            log.warning("paper ran out during the print")
            return False
        log.info("printer status after the print: 0x%02x", status)
        return True


def print_receipt(settings: PrinterSettings, img: Image.Image,
                  on_start: Optional[Callable[[], None]] = None) -> bool:
    """`on_start` runs once the printer is ready, just before any paper moves."""
    with ThermalPrinter(settings) as printer:
        printer.check_ready()
        if on_start:
            on_start()
        started = time.monotonic()
        printer.print_image(img)
        confirmed = printer.confirm_done()
        log.info("sent %d rows in %.0fs, printer answered afterwards=%s", img.height, time.monotonic() - started, confirmed)
        return confirmed
