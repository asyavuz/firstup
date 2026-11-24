import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from reporter import button, config, poster, render, settings


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setattr(button, "NEXT_TAP", 0.06)
    got = []
    current = SimpleNamespace(button=config.ButtonSettings())
    p = button.Panel(lambda: current, SimpleNamespace(on=lambda: None, off=lambda: None))
    monkeypatch.setattr(p, "_print_blocks", got.append)
    monkeypatch.setattr(p, "_shut_down", lambda: got.append("down"))
    return p, got, current


def tap(p, count, gap=0.0):
    for _ in range(count):
        p.pressed(), p.released()
        time.sleep(gap)


def hold(p, monkeypatch, seconds):
    clock = iter([100.0, 100.0 + seconds])
    monkeypatch.setattr(button, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=time.sleep))
    p.pressed(), p.released()
    time.sleep(0.2)


@pytest.mark.parametrize("taps, printed", [(1, [["receipt"]]), (2, [["wifi"]]), (3, [["departures"]]), (4, []), (5, [["poster"]]), (6, [])])
def test_taps(panel, taps, printed):
    p, got, _ = panel
    tap(p, taps)
    time.sleep(0.2)
    assert got == printed


def test_the_wait_starts_again_at_every_tap(panel):
    p, got, _ = panel
    tap(p, 3, gap=0.04)  # longer in total than one wait
    time.sleep(0.2)
    assert got == [["departures"]]


def test_a_long_gap_is_two_single_taps(panel):
    p, got, _ = panel
    tap(p, 2, gap=0.2)
    time.sleep(0.2)
    assert got == [["receipt"], ["receipt"]]


def test_a_press_under_way_is_waited_for(panel):
    p, got, _ = panel
    tap(p, 1)
    p.pressed()
    time.sleep(0.15)  # still down when the first wait would have ended
    assert got == []
    p.released()
    time.sleep(0.2)
    assert got == [["wifi"]]


@pytest.mark.parametrize("seconds, printed", [(0.3, ["receipt"]), (1.9, ["receipt"]), (2.1, ["health"]), (4.9, ["health"])])
def test_how_long_it_is_held(panel, monkeypatch, seconds, printed):
    p, got, _ = panel
    hold(p, monkeypatch, seconds)
    assert got == [printed]


@pytest.mark.parametrize("seconds, printed", [(0.9, ["news", "quote"]), (1.0, ["sudoku"]), (2.9, ["sudoku"]), (3.5, ["weather", "health"])])
def test_any_number_of_taps_and_seconds_can_print_anything(panel, monkeypatch, seconds, printed):
    p, got, current = panel
    current.button = config.ButtonSettings(taps=(("news", 1), ("quote", 1), ("wifi", 9)), holds=(("weather", 3), ("sudoku", 1), ("health", 3)))
    hold(p, monkeypatch, seconds)
    assert got == [printed]
    got.clear()
    monkeypatch.undo()
    monkeypatch.setattr(button, "NEXT_TAP", 0.06)
    monkeypatch.setattr(p, "_print_blocks", got.append)
    tap(p, 9)
    time.sleep(0.3)
    assert got == [["wifi"]]


def test_hold_is_not_a_tap_and_always_shuts_down(panel):
    p, got, current = panel
    current.button = config.ButtonSettings(taps=(), holds=())
    tap(p, 1)
    p.pressed(), p.held(), p.released()
    time.sleep(0.2)
    assert got == ["down"]


def test_blocks_are_printed_together_and_the_receipt_is_all_of_its_own(monkeypatch):
    seen = []
    monkeypatch.setattr(button.report, "build", lambda cfg, now, names, asked: seen.append((names, asked, cfg.trains.days)) or SimpleNamespace(image=None))
    monkeypatch.setattr(button, "print_receipt", lambda *a: None)
    cfg = config.load()
    p = button.Panel(lambda: cfg, None)
    p._print_blocks(["sudoku", "receipt"])
    p._print_blocks(["trains"])
    assert seen == [(["sudoku", *cfg.sections], ["sudoku"], cfg.trains.days), (["trains"], ["trains"], settings.DAYS)]


def test_a_release_without_a_press_is_nothing(panel):
    p, got, _ = panel
    p.released()
    time.sleep(0.2)
    assert got == []


def test_slow_settings_do_not_make_a_tap_a_hold(panel, monkeypatch):
    p, got, current = panel
    real = p._load
    monkeypatch.setattr(p, "_load", lambda: time.sleep(0.3) or real())
    current.button = config.ButtonSettings(taps=(("receipt", 1),), holds=(("health", 0.25),))
    p.pressed(), p.released()
    time.sleep(0.8)
    assert got == [["receipt"]]


def test_a_mistake_in_the_files_does_not_take_the_button_away(panel, monkeypatch):
    p, got, _ = panel
    tap(p, 1)
    time.sleep(0.2)
    monkeypatch.setattr(p, "_load", lambda: (_ for _ in ()).throw(ValueError("[weather] has no setting called latitud")))
    tap(p, 2)
    time.sleep(0.2)
    assert got == [["receipt"], ["wifi"]]


def test_every_hold_is_shorter_than_shutting_down():
    assert settings.HOLDS[1] < button.SHUTDOWN
    for name, _ in config.load().button.taps + config.load().button.holds:
        assert name in settings.PRESSABLE


def test_the_poster_says_where_it_comes_from(monkeypatch):
    with_address = poster.page(datetime(2026, 11, 24, 16, 31))
    assert poster.ADDRESS.startswith("github.com/") and render.font("bold", 19).getlength(poster.ADDRESS) < 2 * render.RIGHT - render.WIDTH
    monkeypatch.setattr(poster, "ADDRESS", "")
    without = poster.page(datetime(2026, 11, 24, 16, 31))
    below = (0, with_address.height - 26, render.WIDTH, with_address.height)
    assert with_address.convert("L").crop(below).getextrema()[0] == 0 and with_address.size == without.size
    assert without.convert("L").crop(below).getextrema() == (255, 255)


def test_the_poster_fits_the_paper_and_spares_the_print_head():
    image = poster.page(datetime(2026, 11, 24, 16, 31))
    assert image.mode == "1" and image.width == render.WIDTH and image.height < 700
    rows = [sum(1 for v in image.crop((0, y, render.WIDTH, y + 1)).convert("L").tobytes() if v == 0) for y in range(image.height)]
    assert sum(rows) / (image.width * image.height) < .42
    assert max(sum(rows[y:y + 24]) / (24 * render.WIDTH) for y in range(len(rows) - 24)) < .72  # no long solid bands


def test_shutting_down_does_not_wait_for_something_stuck(panel, monkeypatch):
    p, got, _ = panel
    stuck = threading.Event()
    monkeypatch.setattr(p, "_print_blocks", lambda names: stuck.wait(5))
    tap(p, 1)
    time.sleep(0.2)
    assert p.busy.locked()
    p.pressed(), p.held(), p.released()
    p.pressed(), p.held(), p.released()
    time.sleep(0.1)
    assert got == ["down"]  # once, and although the print is still going
    stuck.set()


def test_without_threads_the_pi_can_still_be_shut_down(panel, monkeypatch):
    p, got, _ = panel
    monkeypatch.setattr(button.threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("can't start new thread")))
    with pytest.raises(RuntimeError):
        p._start(lambda: None)
    assert not p.busy.locked()
    p.pressed(), p.held()
    assert got == ["down"]


def test_a_failed_shutdown_can_be_tried_again(monkeypatch):
    tries = []

    def fails(*args, **kwargs):
        tries.append(args)
        raise button.subprocess.CalledProcessError(1, "sudo")
    monkeypatch.setattr(button.subprocess, "run", fails)
    monkeypatch.setattr(button, "print_receipt", lambda *a: None)
    p = button.Panel(config.load, SimpleNamespace(on=lambda: None, off=lambda: None))
    for _ in range(2):
        p.held()
        time.sleep(0.3)
    assert len(tries) == 2
