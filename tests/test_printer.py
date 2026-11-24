import dataclasses
from types import SimpleNamespace

import pytest
from PIL import Image

from reporter import __main__ as cli
from reporter import config, http, lists, printer, report, schedule

FAST = dataclasses.replace(config.PrinterSettings(), row_time=0)


class FakeSerial:
    """Records bytes; answers the status query with `status` (None means silent)."""

    def __init__(self, status=0x20):
        self.status, self.sent, self.pending, self.closed = status, b"", b"", False
        self.timeout = None

    def write(self, data):
        self.sent += data
        if data == b"\x1bv\x00" and self.status is not None:
            self.pending += bytes((self.status,))

    def read(self, n):
        out, self.pending = self.pending[:n], self.pending[n:]
        return out

    def flush(self): pass
    def reset_input_buffer(self): self.pending = b""
    def close(self): self.closed = True


@pytest.fixture
def port(monkeypatch):
    fake = FakeSerial()
    monkeypatch.setattr(printer.serial, "Serial", lambda *a, **k: fake)
    monkeypatch.setattr(printer.time, "sleep", lambda s: None)
    return fake


def test_rows_pack_black_as_set_bits():
    img = Image.new("1", (384, 2), 1)
    img.putpixel((0, 0), 0)
    img.putpixel((383, 1), 0)
    first, second = printer.rows(img)
    assert first == b"\x80" + b"\x00" * 47
    assert second == b"\x00" * 47 + b"\x01"


def test_rows_rejects_wrong_size():
    with pytest.raises(ValueError):
        list(printer.rows(Image.new("1", (200, 2))))


def test_print_sends_each_row_and_confirms(port):
    assert printer.print_receipt(FAST, Image.new("1", (384, 10), 0)) is True
    assert port.sent.count(b"\x12*\x01\x30" + b"\xff" * 48) == 10
    assert port.sent.index(b"\x1b8\x00\x00") < port.sent.index(b"\x12*")  # sleep disabled first
    assert port.closed


@pytest.mark.parametrize("status, message", [(None, "does not answer"), (0x24, "out of paper")])
def test_not_ready_prints_nothing(port, status, message):
    port.status = status
    with pytest.raises(printer.PrinterError, match=message):
        printer.print_receipt(FAST, Image.new("1", (384, 10), 0))
    assert b"\x12*" not in port.sent
    assert port.closed


def test_one_lost_reply_is_survived(port, monkeypatch):
    """Seen on the real printer: silent for the first two queries, then fine."""
    queries = []
    real_write = FakeSerial.write

    def flaky(self, data):
        if data == b"\x1bv\x00":
            queries.append(data)
            if len(queries) <= 2:
                self.sent += data
                return
        real_write(self, data)
    monkeypatch.setattr(FakeSerial, "write", flaky)
    assert printer.print_receipt(FAST, Image.new("1", (384, 3), 0)) is True
    assert b"\x00" * 256 in port.sent


def test_calibration_changes_heat_for_every_block(port):
    from reporter import calibrate
    assert calibrate.run(FAST) is True
    for heat in calibrate.HEAT_TIMES:
        assert bytes((0x1B, 0x37, FAST.heat_dots, heat, FAST.heat_interval)) in port.sent
        assert calibrate.block(heat).width == 384
    assert max(calibrate.HEAT_TIMES) < 90  # 90 smudges, 110 squashes
    last_heat = port.sent[port.sent.rindex(b"\x1b7"):][:5]
    assert last_heat == bytes((0x1B, 0x37, FAST.heat_dots, FAST.heat_time, FAST.heat_interval))  # left as configured


def test_port_is_not_drained_after_every_row(port, monkeypatch):
    """Draining per row took 50 ms, stopped the motor and ghosted the text."""
    flushes = []
    monkeypatch.setattr(FakeSerial, "flush", lambda self: flushes.append(len(self.sent)))
    with printer.ThermalPrinter(FAST) as device:
        flushes.clear()
        device.print_image(Image.new("1", (384, 20), 0), feed_lines=0)
    assert len(flushes) == 1
    assert port.sent.count(b"\x12*\x01\x30" + b"\xff" * 48) == 20


# --- the scheduled command end to end, with a fake printer ---

@pytest.fixture
def scheduled(monkeypatch, tmp_path, port):
    cfg = dataclasses.replace(config.load(), printer=FAST)
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(schedule, "wait_for_clock", lambda: True)
    monkeypatch.setattr(http, "wait_for_network", lambda: True)
    monkeypatch.setattr(report, "build",
                        lambda c, n: SimpleNamespace(image=Image.new("1", (384, 4), 0), failed=[]))

    def run(*args):
        class Clock(cli.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(*args, tzinfo=tz)
        monkeypatch.setattr(cli, "datetime", Clock)
        before = port.sent.count(b"\x12*")
        code = cli.cmd_scheduled(cfg, None)
        return code, port.sent.count(b"\x12*") - before
    return run


def test_prints_once_on_a_weekday(scheduled):
    assert scheduled(2026, 11, 24, 8, 0) == (0, 4)
    assert scheduled(2026, 11, 24, 8, 2) == (0, 0)
    assert scheduled(2026, 11, 25, 8, 0) == (0, 4)


def test_weekend_prints_at_ten_not_eight(scheduled):
    assert scheduled(2026, 11, 28, 8, 0) == (0, 0)
    assert scheduled(2026, 11, 28, 10, 0) == (0, 4)
    assert scheduled(2026, 11, 29, 10, 0) == (0, 4)


def test_out_of_paper_is_retried_later(scheduled, port):
    port.status = 0x24
    with pytest.raises(printer.PrinterError):
        scheduled(2026, 11, 24, 8, 0)
    port.status = 0x20
    assert scheduled(2026, 11, 24, 8, 30) == (0, 4)


def test_unsynchronised_clock_prints_nothing(scheduled, monkeypatch, port):
    monkeypatch.setattr(schedule, "wait_for_clock", lambda: False)
    assert scheduled(2026, 11, 24, 8, 0) == (cli.EXIT_RETRY, 0)


def test_the_clock_is_not_waited_for_when_nothing_is_due(scheduled, monkeypatch):
    monkeypatch.setattr(schedule, "wait_for_clock", lambda: pytest.fail("waited"))
    assert scheduled(2026, 11, 24, 7, 55) == (0, 0)
    assert scheduled(2026, 11, 24, 10, 5) == (0, 0)


def test_a_network_that_comes_after_midnight_does_not_cost_tomorrow_its_receipt(scheduled, monkeypatch):
    def midnight():
        class Clock(cli.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 25, 0, 0, tzinfo=tz)
        monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(http, "wait_for_network", midnight)
    assert scheduled(2026, 11, 24, 9, 59) == (0, 0)
    monkeypatch.setattr(http, "wait_for_network", lambda: True)
    assert scheduled(2026, 11, 25, 8, 0) == (0, 4)


def test_a_clock_that_was_wrong_is_asked_again(scheduled, monkeypatch):
    def corrected():
        class Clock(cli.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 24, 15, 0, tzinfo=tz)
        monkeypatch.setattr(cli, "datetime", Clock)
        return True
    monkeypatch.setattr(schedule, "wait_for_clock", corrected)
    assert scheduled(2026, 11, 24, 8, 0) == (0, 0)


def test_printer_errors_ask_systemd_to_try_again(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["reporter", "status"])
    monkeypatch.setattr(printer.ThermalPrinter, "__enter__", lambda self: (_ for _ in ()).throw(printer.PrinterError("off")))
    assert cli.main() == cli.EXIT_RETRY


def test_journal_lines_carry_their_importance():
    record = cli.logging.LogRecord("reporter", cli.logging.WARNING, "", 0, "one\ntwo", (), None)
    assert cli.JournalFormatter("%(message)s").format(record) == "<4>one\n<4>two"


@pytest.mark.parametrize("error", [printer.serial.SerialException("gone"), OSError("power"), KeyboardInterrupt()])
def test_a_print_cut_short_is_not_started_again(scheduled, port, monkeypatch, error):
    real, rows_sent = FakeSerial.write, []

    def dies_on_the_third_row(self, data):
        if data.startswith(b"\x12*"):
            rows_sent.append(data)
            if len(rows_sent) == 3:
                raise error
        real(self, data)
    monkeypatch.setattr(FakeSerial, "write", dies_on_the_third_row)
    with pytest.raises(type(error)):
        scheduled(2026, 11, 24, 8, 0)
    monkeypatch.setattr(FakeSerial, "write", real)
    assert scheduled(2026, 11, 24, 8, 2) == (0, 0)   # same day: not again
    assert scheduled(2026, 11, 25, 8, 0) == (0, 4)   # next day: normal


def test_a_printer_that_was_never_ready_is_still_retried(scheduled, port):
    port.status = None
    with pytest.raises(printer.PrinterError):
        scheduled(2026, 11, 24, 8, 0)
    port.status = 0x20
    assert scheduled(2026, 11, 24, 8, 2) == (0, 4)


def test_the_list_survives_the_scheduled_print_for_the_button(scheduled, monkeypatch, tmp_path):
    today, over = tmp_path / "events.txt", tmp_path / "reminders.txt"
    today.write_text("2026-11-24\n09:00 Meeting")
    over.write_text("2026-11-23\nYesterday")
    monkeypatch.setattr(lists, "paths", lambda cfg: (today, over))
    assert scheduled(2026, 11, 24, 8, 0) == (0, 4)
    assert today.exists() and not over.exists()  # the timer deletes it even if the button service does not run


def test_lists_are_deleted_on_days_without_a_print(scheduled, monkeypatch, tmp_path):
    over = tmp_path / "events.txt"
    over.write_text("2026-11-23\n09:00 Meeting")
    monkeypatch.setattr(lists, "paths", lambda cfg: (over, tmp_path / "reminders.txt"))
    assert scheduled(2026, 11, 24, 0, 5) == (0, 0) and not over.exists()


def test_a_picture_shows_examples_not_the_calendar(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(report, "build", lambda cfg, now, on_screen=False, names=None, asked=(): seen.append((on_screen, names)) or report.Report(Image.new("1", (384, 4), 1), []))
    monkeypatch.setattr(cli.sys, "argv", ["reporter", "render", "-o", str(tmp_path / "x.png")])
    assert cli.main() == 0 and seen == [(True, None)]
