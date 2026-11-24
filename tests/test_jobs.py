import dataclasses
import json
import os
import stat
import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from PIL import Image

from reporter import config, health, jobs, report, schedule
from reporter.printer import PrinterError
from reporter.sections import events


@pytest.fixture
def place(monkeypatch, tmp_path):
    for name in ("requests", "out"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(jobs, "REQUESTS", tmp_path / "requests")
    monkeypatch.setattr(jobs, "OUT", tmp_path / "out")
    monkeypatch.setattr(health, "CHECKS", (("Power", lambda c, n: "good"),))
    monkeypatch.setattr(report, "build", lambda cfg, now, on_screen=False, names=None: report.Report(Image.new("1", (384, 4), 1), ["news"] if on_screen else []))
    return tmp_path


def ask(place, *kinds):
    for kind in kinds:
        (place / "requests" / kind).touch()
    return jobs.run()


def result(place, kind):
    return json.loads((place / "out" / f"result-{kind}.json").read_text())


def test_each_request_is_done_once_and_removed(place, monkeypatch):
    printed = []
    monkeypatch.setattr(jobs, "print_receipt", lambda settings, image: printed.append(image) or True)
    ask(place, "receipt")
    assert len(printed) == 1 and os.listdir(place / "requests") == []
    jobs.run()
    assert len(printed) == 1
    assert result(place, "receipt")["state"] == "done"


def test_a_request_that_fails_is_not_tried_for_ever(place, monkeypatch):
    def out_of_paper(settings, image):
        raise PrinterError("printer is out of paper")
    monkeypatch.setattr(jobs, "print_receipt", out_of_paper)
    ask(place, "receipt")
    assert result(place, "receipt")["text"] == "printer is out of paper" and os.listdir(place / "requests") == []
    monkeypatch.setattr(jobs, "PAUSE", timedelta(0))
    monkeypatch.setattr(jobs, "print_receipt", lambda *a: 1 / 0)
    ask(place, "receipt")
    assert result(place, "receipt") == {"state": "failed", "text": "It went wrong (ZeroDivisionError)", "at": result(place, "receipt")["at"]}


def test_odd_things_in_the_folder_are_cleared_and_never_read(place, monkeypatch):
    done = []
    monkeypatch.setattr(jobs, "do", done.append)
    folder = place / "requests"
    (folder / "sub").mkdir()
    (folder / "full").mkdir()
    (folder / "full" / "x").touch()
    (folder / "shutdown").touch()
    (folder / "preview").symlink_to(place / "secret")
    os.mkfifo(folder / "trains")
    jobs.run()
    assert sorted(done) == ["preview", "trains"] and os.listdir(folder) == ["full"]


def test_previews_never_read_the_calendar(monkeypatch):
    cfg = dataclasses.replace(config.load(), sections=("events",))
    read = []
    monkeypatch.setattr(events, "fetch", lambda *a: read.append(a))
    report.build(cfg, datetime(2026, 11, 24, 8), on_screen=True)
    assert read == []
    report.build(cfg, datetime(2026, 11, 24, 8))
    assert len(read) == 1  # the trap works


def test_preview_is_drawn_for_the_screen(place):
    ask(place, "preview")
    assert Image.open(place / "out" / "preview.png").size == (384, 4)
    assert result(place, "preview") == {"state": "done", "text": "Unavailable now: Headlines", "at": result(place, "preview")["at"]}
    assert stat.S_IMODE((place / "out" / "preview.png").stat().st_mode) == 0o640


def test_a_train_token_is_tried_kept_and_never_written_elsewhere(place, monkeypatch, tmp_path, caplog):
    token, path = "a-train-token-0123456789", tmp_path / "rail.json"
    monkeypatch.setattr(jobs.trains, "PATH", path)
    monkeypatch.setattr(jobs.trains, "fetch", lambda *a: jobs.trains.Board("Leeds", []))
    (place / "requests/rail").write_text(token + "\n")
    jobs.run()
    assert result(place, "rail")["text"] == "Saved and working: 0 departures from Leeds" and json.loads(path.read_text())["token"] == token
    assert path.stat().st_mode & 0o777 == 0o600 and token not in caplog.text and jobs._handed == {}
    assert all(token.encode() not in p.read_bytes() for p in place.rglob("*") if p.is_file() and p != path)
    monkeypatch.setattr(jobs.trains, "fetch", lambda *a: (_ for _ in ()).throw(RuntimeError("no")))
    (place / "requests/rail").write_text("another-token-0123456789")
    jobs.run()
    assert result(place, "rail")["state"] == "failed" and json.loads(path.read_text())["token"] == token  # the old one stays
    (place / "requests/rail").touch()  # the content comes a moment later
    threading.Timer(0.3, lambda: (place / "requests/rail").write_text("a-late-token-0123456789")).start()
    monkeypatch.setattr(jobs.trains, "fetch", lambda *a: jobs.trains.Board("Leeds", []))
    jobs.run()
    assert json.loads(path.read_text())["token"] == "a-late-token-0123456789"
    (place / "requests/rail-forget").touch()
    jobs.run()
    assert not path.exists()


def test_an_older_answer_never_counts_for_a_newer_request(place, monkeypatch):
    (place / "out/result-rail.json").write_text(json.dumps({"state": "done", "text": "Saved and working", "at": datetime(2026, 1, 1).astimezone().isoformat()}))
    seen = []
    monkeypatch.setitem(jobs.KINDS, "preview", lambda cfg, now: seen.append(result(place, "rail")["state"]) or "Ready")
    monkeypatch.setattr(jobs.trains, "fetch", lambda *a: (_ for _ in ()).throw(RuntimeError("no")))
    (place / "requests/preview").touch()
    (place / "requests/rail").write_text("a-refused-token-0123456789")
    jobs.run()
    assert seen == ["working"] and result(place, "rail")["state"] == "failed"


def test_the_preview_names_feeds_that_gave_nothing(place, monkeypatch):
    monkeypatch.setattr(jobs.report, "build", lambda *a, **k: jobs.report.Report(Image.new("1", (384, 4), 1), [], ["BBC"]))
    assert "No headlines from: BBC" in jobs._preview(config.load(), datetime(2026, 11, 24, 12))


def test_status_holds_what_the_web_pages_need_and_nothing_private(place, monkeypatch, tmp_path):
    stamp = tmp_path / "stamp"
    schedule.write_stamp(stamp, date(2026, 11, 24))
    monkeypatch.setattr(health, "stamp", lambda: stamp)
    monkeypatch.setattr(jobs.trains, "load_token", lambda: SimpleNamespace(token="SECRET-TOKEN"))
    cfg = config.load()
    got = jobs.status(cfg, datetime(2026, 11, 24, 12, 0, tzinfo=cfg.tz))
    assert got["last_print"] == "2026-11-24" and got["rail_key"] is True
    assert got["defaults"] == config.as_settings(cfg) and got["health"] == [("Power", "good")]
    assert "SECRET" not in json.dumps(got)


def test_the_button_service_survives_without_a_web_interface(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "OUT", tmp_path / "none")
    jobs.refresh_status(config.load())
    monkeypatch.setattr(jobs, "OUT", tmp_path)
    monkeypatch.setattr(jobs, "write_status", lambda *a: 1 / 0)
    jobs.refresh_status(config.load())


def test_a_web_program_gone_wrong_cannot_empty_the_roll(place, monkeypatch):
    printed = []
    monkeypatch.setattr(jobs, "print_receipt", lambda *a: printed.append(a) or True)
    for _ in range(5):
        ask(place, "receipt")
    assert len(printed) == 1 and result(place, "receipt")["text"] == "that came out a moment ago"
    ask(place, "health")
    assert len(printed) == 2
    monkeypatch.setattr(jobs, "PAUSE", timedelta(0))
    for _ in range(jobs.PER_DAY + 10):
        ask(place, "receipt")
    assert len(printed) == jobs.PER_DAY and "is the limit" in result(place, "receipt")["text"]
    used = json.loads((place / "out/paper.json").read_text())
    (place / "out/paper.json").write_text(json.dumps({**used, "day": "2020-01-01"}))
    ask(place, "receipt")
    assert len(printed) == jobs.PER_DAY + 1  # a new day
    (place / "out/paper.json").write_text("damaged")
    ask(place, "receipt")
    assert len(printed) == jobs.PER_DAY + 2


def test_paper_kinds_agree_with_the_web_program():
    from reporter_web import store
    assert store.PAPER == jobs.PAPER


def test_nothing_is_created_or_logged_just_to_look(place, monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path / "never"))
    monkeypatch.setattr(health, "STAMP", tmp_path / "none" / "stamp")
    jobs.status(config.load(), datetime(2026, 11, 24, 12, 0, tzinfo=config.load().tz))
    assert not (tmp_path / "never").exists() and "web settings" not in caplog.text
