from datetime import date, datetime, time

import pytest

from reporter import config, schedule

SCHED = (config.Schedule(days=(0, 1, 2, 3, 4), time=time(8, 0), catch_up_until=time(10, 0)),
         config.Schedule(days=(5, 6), time=time(10, 0), catch_up_until=time(12, 0)))


@pytest.mark.parametrize("now, last, run", [
    (datetime(2026, 11, 24, 8, 0, 0), None, True),                        # Tuesday on the dot
    (datetime(2026, 11, 27, 8, 0, 1), date(2026, 11, 26), True),          # Friday, printed Thursday
    (datetime(2026, 11, 28, 8, 0, 0), None, False),                       # Saturday, too early
    (datetime(2026, 11, 28, 10, 0, 0), date(2026, 11, 27), True),         # Saturday at ten
    (datetime(2026, 11, 29, 11, 59), date(2026, 11, 28), True),           # Sunday, catching up
    (datetime(2026, 11, 29, 12, 0, 1), None, False),                      # Sunday, too late
    (datetime(2026, 11, 28, 10, 5), date(2026, 11, 28), False),           # Saturday, already printed
    (datetime(2026, 11, 24, 10, 30), None, False),                        # weekday cut-off is not the weekend's
    (datetime(2026, 11, 24, 7, 59, 59), None, False),                     # too early
    (datetime(2026, 11, 24, 9, 30), None, True),                          # catch-up after downtime
    (datetime(2026, 11, 24, 10, 0, 1), None, False),                      # past the cut-off
    (datetime(2026, 11, 23, 16, 6, 46), None, False),                     # power-on in the afternoon
    (datetime(2026, 11, 24, 8, 5), date(2026, 11, 24), False),            # never twice a day
])
def test_decide(now, last, run):
    assert schedule.decide(now, SCHED, last).run is run


def test_stamp_round_trip(tmp_path):
    path = tmp_path / "stamp"
    assert schedule.read_stamp(path) is None
    schedule.write_stamp(path, date(2026, 11, 24))
    assert schedule.read_stamp(path) == date(2026, 11, 24)


def test_corrupt_stamp_counts_as_never_printed(tmp_path):
    path = tmp_path / "stamp"
    path.write_text("\x00\x00garbage")
    assert schedule.read_stamp(path) is None


def test_wait_for_clock_gives_up(monkeypatch):
    monkeypatch.setattr(schedule, "clock_is_synchronised", lambda: False)
    assert schedule.wait_for_clock(timeout=0, poll=0) is False


def test_shipped_config():
    assert [(s.days, s.time, s.catch_up_until) for s in config.load().schedule] == [(s.days, s.time, s.catch_up_until) for s in SCHED]


def test_a_day_without_a_slot_never_prints():
    assert not schedule.decide(datetime(2026, 11, 28, 10, 0), SCHED[:1], None).run


@pytest.mark.parametrize("slots", [
    [],
    [{"days": ["Mon"], "time": "08:00", "catch_up_until": "07:00"}],
    [{"days": ["Mon"], "time": "08:00", "catch_up_until": "10:00"}, {"days": ["Mon"], "time": "18:00", "catch_up_until": "20:00"}],
])
def test_bad_schedules_are_rejected(slots):
    with pytest.raises(ValueError):
        config._parse_schedule(slots)


def test_bad_day_name_is_rejected():
    with pytest.raises(ValueError):
        config._parse_days(["Mon", "Caturday"])
