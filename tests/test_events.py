import dataclasses
import os
from datetime import date, datetime

import pytest

from reporter import config, health, lists, render, report
from reporter.sections import events, reminders

NOW = datetime(2026, 11, 24, 8, 0)
TODAY = NOW.date()


def cfg_for(path):
    return dataclasses.replace(config.load(), events=config.EventsSettings(inbox=str(path)))


def test_parse_sorts_and_understands_all_day():
    got = events.parse("2026-11-24\n14:00-15:30 Dentist\n9:30 Stand-up\nAll day Parents visiting\n", TODAY)
    assert [(e.when, e.title) for e in got] == [
        ("All day", "Parents visiting"), ("09:30", "Stand-up"), ("14:00–15:30", "Dentist")]


@pytest.mark.parametrize("text", ["", "\n\n", "2026-11-23\n09:00 Yesterday", "no date\n09:00 X", "24/11/2026\n09:00 X"])
def test_stale_or_malformed_lists_are_rejected(text):
    assert events.parse(text, TODAY) is None


def test_empty_day_is_not_the_same_as_nothing_received():
    assert events.parse("2026-11-24\n", TODAY) == []


def test_hostile_text_is_harmless():
    text = "2026-11-24\n09:00 \x1b@\x1b7\xff\x00 bell\x07 🎉 " + "x" * 5000 + "\n" + "10:00 y\n" * 500
    got = events.parse(text, TODAY)
    assert not any(ch < " " for e in got for ch in e.title)
    img = events.render(events.Inbox(True, got), NOW)
    assert img.width == render.WIDTH and img.height < 700


def test_not_set_up_leaves_the_section_out(tmp_path):
    cfg = cfg_for(tmp_path / "missing" / "events.txt")
    assert events.fetch(cfg, None, NOW) is None
    assert events.render(None, NOW) is None
    cfg = dataclasses.replace(cfg, sections=("header", "events", "closing"))
    both = dataclasses.replace(cfg, sections=("header", "closing"))
    assert report.build(cfg, NOW).failed == []
    assert report.build(cfg, NOW).image.height == report.build(both, NOW).image.height


def test_fetch_and_clear(tmp_path):
    path = tmp_path / "events.txt"
    cfg = cfg_for(path)
    assert events.fetch(cfg, None, NOW) == events.Inbox(False, [])
    path.write_text("2026-11-24\n09:00 Meeting")
    assert events.fetch(cfg, None, NOW).events[0].title == "Meeting"
    assert lists.clear_old(cfg, TODAY) is False and path.exists()       # kept all day
    assert lists.clear_old(cfg, date(2026, 11, 25)) is True and not path.exists()
    assert lists.clear_old(cfg, date(2026, 11, 25)) is False            # twice is fine


@pytest.mark.parametrize("first, kept", [("2026-11-25", True), ("2026-11-24", True), ("2026-11-23", False), ("2026-11-20", False), ("rubbish", False)])
def test_only_lists_whose_day_is_over_are_deleted(tmp_path, first, kept):
    path = tmp_path / "events.txt"
    path.write_text(f"{first}\n09:00 Meeting")
    lists.clear_old(cfg_for(path), TODAY)
    assert path.exists() is kept


def test_only_the_first_8_kb_is_read(tmp_path):
    path = tmp_path / "events.txt"
    path.write_text("2026-11-24\n" + "09:00 Meeting\n" * 100_000)
    assert len(events.fetch(cfg_for(path), None, NOW).events) < 700


def test_tidy_survives_any_file_problem(tmp_path, monkeypatch):
    from reporter import button
    path = tmp_path / "events.txt"
    path.write_text("2020-01-01\n09:00 Old")
    button.tidy(cfg_for(path))
    assert not path.exists()
    path.mkdir()  # cannot be read as a file; the other one still goes
    (tmp_path / "reminders.txt").write_text("2020-01-01\nOld")
    button.tidy(cfg_for(path))
    assert not (tmp_path / "reminders.txt").exists()


@pytest.mark.parametrize("make", [lambda p: os.mkfifo(p), lambda p: p.symlink_to("/dev/zero"), lambda p: p.mkdir(), lambda p: p.symlink_to("/nowhere")])
def test_what_is_not_a_list_is_neither_waited_for_nor_followed(tmp_path, make):
    cfg = cfg_for(tmp_path / "events.txt")
    make(tmp_path / "events.txt")
    make(tmp_path / "reminders.txt")
    assert events.fetch(cfg, None, NOW) == events.Inbox(False, []) and reminders.fetch(cfg, None, NOW) == []
    assert "list at" not in str(health.collect(cfg, NOW.astimezone()))
    assert lists.clear_old(cfg, TODAY) is True and list(tmp_path.iterdir()) == []


def test_nothing_else_is_deleted_from_a_folder_of_ones_own(tmp_path, monkeypatch):
    other = tmp_path / "thesis.txt"
    other.write_text("x")
    os.utime(other, (0, 0))
    lists.clear_old(cfg_for(tmp_path / "events.txt"), TODAY)
    assert other.exists()
    monkeypatch.setattr(lists.os, "getuid", lambda: -1)  # somebody else's: the drop box
    lists.clear_old(cfg_for(tmp_path / "events.txt"), TODAY)
    assert not other.exists()


def test_a_list_that_only_half_arrived_is_deleted(tmp_path):
    half = tmp_path / ".in.12.34"
    half.write_text("2026-11-24\n09:00 Mee")
    assert lists.clear_old(cfg_for(tmp_path / "events.txt"), TODAY) is False and half.exists()  # may still be arriving
    os.utime(half, (0, 0))
    assert lists.clear_old(cfg_for(tmp_path / "events.txt"), TODAY) is True and not half.exists()
