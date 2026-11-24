import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PIL import ImageOps

from reporter import config, lists, render, report, settings, trains
from reporter.sections import REGISTRY, TITLES, ahead, events, history, mytrains, quote, reminders, sudoku, tube, warnings

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 24, 8, 0, tzinfo=LONDON)


def fits(image):
    return image.width == render.WIDTH and image.convert("L").crop((render.RIGHT + 1, 0, render.WIDTH, image.height)).getextrema()[0] == 255


def test_every_block_is_known_everywhere():
    assert list(settings.SECTIONS) and set(settings.SECTIONS) == set(REGISTRY) == set(TITLES)
    assert set(config.load().sections) <= set(REGISTRY)


# --- bank holidays and clocks ---

def test_a_holiday_moved_to_another_day_is_named_after_it():
    payload = {"england-and-wales": {"events": [{"title": "Boxing Day", "date": "2026-12-28", "notes": "Substitute day"}]}}
    assert ahead.holidays(payload, date(2026, 12, 28)) == [ahead.Notice("calendar", "Bank holiday for Boxing Day", "Today")]


def bank(*days):
    return {"england-and-wales": {"events": [{"title": t, "date": d} for d, t in days]}}


@pytest.mark.parametrize("today, words", [(date(2026, 12, 25), "Today"), (date(2026, 12, 24), "Tomorrow"), (date(2026, 12, 18), "Friday 25 December"), (date(2026, 12, 17), None), (date(2026, 12, 26), None)])
def test_holidays_a_week_before(today, words):
    got = ahead.holidays(bank(("2026-12-25", "Christmas Day")), today)
    assert [(n.strong, n.detail) for n in got] == ([("Christmas Day, bank holiday", words)] if words else [])
    assert ahead.holidays(bank((str(today), "Spring bank holiday")), today)[0].strong == "Spring bank holiday"


@pytest.mark.parametrize("day, words", [((2026, 10, 22), "Clocks go back"), ((2026, 10, 25), "Clocks go back"), ((2026, 10, 21), None), ((2026, 10, 26), None), ((2027, 3, 27), "Clocks go forward")])
def test_clock_changes(day, words):
    got = ahead.clock_change(datetime(*day, 8, tzinfo=LONDON))
    assert (got.strong if got else None) == words


def test_the_clocks_survive_a_site_that_is_down(monkeypatch):
    monkeypatch.setattr(ahead.http, "get", lambda *a: 1 / 0)
    assert len(ahead.fetch(None, None, datetime(2026, 10, 24, 8, tzinfo=LONDON))) == 1
    with pytest.raises(ZeroDivisionError):
        ahead.fetch(None, None, NOW)
    assert ahead.render([], NOW) is None and fits(ahead.render([ahead.Notice("clock", "X" * 90, "Y" * 300)] * 5, NOW))


# --- weather warnings ---

def rss(*items):
    return ("<rss><channel>" + "".join(f"<item><title>{t}</title><description>{d}</description></item>" for t, d in items) + "</channel></rss>").encode()


def test_warnings_as_the_met_office_sends_them():
    got = warnings.parse(rss(("Yellow warning of rain affecting South West England", "Yellow warning of rain affecting South West England: Cornwall valid from 0801 Tue 24 Nov to 2359 Tue 24 Nov"),
                             ("Amber warning of wind affecting Wales", "... valid from 1800 Tue 24 Nov to 0600 Wed 25 Nov"), ("Something new", "")))
    amber, yellow, odd = got.worst
    assert yellow == ("Yellow warning: rain", "Tue 24, 08:01 to 23:59", "wi-umbrella.svg.png")
    assert amber.times == "Tue 24, 18:00 to Wed 25, 06:00" and odd == ("Something new", "", "") and got.more == 0
    assert fits(warnings.render(got, NOW)) and warnings.render(warnings.parse(rss()), NOW) is None


def test_the_worst_warnings_come_first_and_the_rest_are_counted():
    got = warnings.parse(rss(*[(f"{level} warning of {kind} affecting Wales", "") for level, kind in
                               (("Yellow", "rain"), ("Yellow", "wind"), ("Yellow", "snow"), ("Red", "wind"), ("Amber", "ice"))]))
    assert [alert.strong for alert in got.worst] == ["Red warning: wind", "Amber warning: ice", "Yellow warning: rain"] and got.more == 2
    assert fits(warnings.render(got, NOW))


@pytest.mark.parametrize("kind", ["thunderstorms", "snow and ice", "extreme heat", "wind and rain and some more"])
def test_a_warning_keeps_clear_of_its_picture(kind):
    got = warnings.parse(rss((f"Yellow warning of {kind} affecting Wales", "valid from 0801 Tue 24 Nov to 2359 Wed 25 Nov")))
    plain = warnings.Alerts([got.worst[0]._replace(icon="wi-na.svg.png")], 0)
    beside = warnings.render(plain, NOW).crop((render.RIGHT - warnings.ICON - 6, 0, render.RIGHT - warnings.ICON - 1, 60))
    assert beside.convert("L").getextrema()[0] > 200  # nothing between the words and the picture


def test_a_warning_icon_exists_for_each_kind():
    for _, name in warnings._ICONS:
        assert (config.ROOT / f"assets/icons/{name}.svg.png").is_file()


# --- on this day ---

def day(*entries):
    return {"selected": [{"year": y, "text": t} for y, t in entries]}


def test_history_is_short_kind_and_changes_with_the_year():
    some = day((1900, "A bomb killed many."), (1925, "A theatre (pictured) opened on Broadway."), (1950, "A bridge was finished."), (1960, "x" * 400))
    assert {history.parse(some, y) for y in range(2026, 2030)} == {(1925, "A theatre opened on Broadway."), (1950, "A bridge was finished.")}
    assert history.parse(day((1900, "A battle was fought.")), 2026).year == 1900  # better than nothing
    with pytest.raises(RuntimeError):
        history.parse(day(), 2026)
    assert fits(history.render(history.Moment(1925, "word " * 200), NOW))


def test_on_this_day_is_laid_out_like_the_quote():
    def ink(image, *box):
        return ImageOps.invert(image.convert("L").crop(box)).getbbox()
    words = "Nothing much happened, but it was written down all the same."
    moment, said = history.render(history.Moment(1925, words), NOW), quote.render(quote.Quote(words, "Anon"), NOW)
    assert fits(moment) and fits(said)
    left, _, right, _ = ink(moment, 0, 0, render.WIDTH, 34)
    assert abs((left + right) / 2 - render.WIDTH / 2) <= 4 and right - left <= render.font("bold", 26).getlength("On this day") + 2
    column = render.PAD + 38 + 7  # between the picture and the text
    starts = [column + ink(image, column, 40, render.WIDTH, 100)[0] for image in (moment, said)]
    assert abs(starts[0] - starts[1]) <= 3 and starts[0] > render.PAD + 38 + 10
    middles = [sum(ink(image, 0, 40, column, 90)[::2]) / 2 for image in (moment, said)]
    assert abs(middles[0] - middles[1]) <= 1


def test_the_year_stands_above_what_happened():
    def top(year):
        return history.render(history.Moment(year, "Something happened."), NOW).convert("L").crop((50, 36, render.WIDTH, 66)).tobytes()
    assert len({top(y) for y in (1925, 1926, 44, -44)}) == 4
    assert fits(history.render(history.Moment(-2560, "word " * 200), NOW))
    longest = ("The Wednesday Women's Museum in Wimbledon won much admiration. " * 3)[:history.LONGEST]  # none of it may be cut off
    assert len(render.wrap(longest, render.font("semibold", 21), render.RIGHT - render.PAD - 38 - 14, 99)) <= history.MOST


# --- reminders ---

@pytest.fixture
def drop(tmp_path):
    cfg = SimpleNamespace(events=SimpleNamespace(inbox=str(tmp_path / "events.txt")))
    return cfg, tmp_path / "reminders.txt"


def test_reminders(drop):
    cfg, path = drop
    assert reminders.fetch(cfg, None, NOW) == [] and reminders.render([], NOW) is None
    path.write_text("2026-11-24\nPut the bins out\n09:30 Call the dentist\n")
    got = reminders.fetch(cfg, None, NOW)
    assert got == [("Call the dentist", "09:30"), ("Put the bins out", "")]
    assert fits(reminders.render(got, NOW)) and fits(reminders.render([reminders.Item("word " * 90, "overdue")] * 40, NOW))
    path.write_text("2026-11-23\nYesterday's\n")
    assert reminders.fetch(cfg, None, NOW) == []


@pytest.mark.parametrize("line, shown", [
    ("2026-11-24 09:30 Ring the dentist", ("Ring the dentist", "09:30")),
    ("2026-11-24 00:00 Put the bins out", ("Put the bins out", "today")),  # what Shortcuts makes of a day without a time
    ("2026-11-24 Put the bins out", ("Put the bins out", "today")),
    ("00:00 Put the bins out", ("Put the bins out", "today")),
    ("2026-11-23 23:59 Pay the rent", ("Pay the rent", "overdue")),
    ("2025-01-01 00:00 Pay the rent", ("Pay the rent", "overdue")),
    (" Buy a bulb", ("Buy a bulb", "")),  # no due date: nothing but the space before the title
    ("All day Buy a bulb", ("Buy a bulb", "")),
    ("2026-11-24 00:00 09:30 is too early", ("09:30 is too early", "today")),
    ("2026-13-40 00:00 No such day", ("2026-13-40 00:00 No such day", "")),
    ("2026-11-24", ("2026-11-24", "")),
    ("2026-11-240 pieces", ("2026-11-240 pieces", "")),
    ("2 eggs", ("2 eggs", "")),
])
def test_when_a_reminder_is_due(line, shown):
    assert reminders.parse(f"2026-11-24\n{line}", NOW.date()) == [shown]


def test_reminders_come_in_the_order_they_press_and_later_ones_wait():
    text = """2026-11-24
 Sort the photographs
2026-11-24 00:00 Put the bins out
2026-11-25 00:00 Tomorrow's
2027-01-01 09:00 Next year's
2026-11-24 17:00 Collect the parcel
 Buy a bulb
2026-11-24 09:30 Ring the dentist
2026-11-23 08:00 Pay the rent
2026-11-01 12:00 Pay the council tax"""
    assert reminders.parse(text, NOW.date()) == [
        ("Pay the council tax", "overdue"), ("Pay the rent", "overdue"), ("Ring the dentist", "09:30"), ("Collect the parcel", "17:00"),
        ("Put the bins out", "today"), ("Sort the photographs", ""), ("Buy a bulb", "")]
    assert reminders.parse(text, NOW.date() + timedelta(days=1)) == []  # a list for another day
    assert reminders.parse("2026-11-24\n2026-11-25 00:00 Tomorrow's", NOW.date()) == []


def test_a_list_sent_the_evening_before_is_read_for_its_own_day():
    text = "2026-11-25\n2026-11-24 00:00 Put the bins out\n2026-11-25 00:00 Ring the dentist"
    assert reminders.parse(text, date(2026, 11, 25)) == [("Put the bins out", "overdue"), ("Ring the dentist", "today")]


def test_a_deadline_is_at_the_right_and_the_title_keeps_away_from_it():
    def right_hand_ink(due):
        image = reminders.render([reminders.Item("word " * 40, due)], NOW).convert("L")
        assert fits(image)
        strip = image.crop((render.RIGHT - int(render.font("bold", 20).getlength("overdue")) - 8, 44, image.width, image.height))
        return ImageOps.invert(strip).getbbox()
    with_one, without = right_hand_ink("overdue"), right_hand_ink("")
    assert with_one[0] >= 6 and with_one[3] <= 30  # only on the first line, and a gap before it
    assert without[0] < 6  # nothing there: the title has the whole width


def test_old_lists_of_both_kinds_are_deleted(drop, tmp_path):
    cfg, path = drop
    (tmp_path / "events.txt").write_text("2026-11-24\n")
    path.write_text("2026-11-23\nOld")
    assert lists.clear_old(cfg, date(2026, 11, 24)) and not path.exists() and (tmp_path / "events.txt").exists()
    assert lists.clear_old(cfg, date(2026, 11, 25)) and not (tmp_path / "events.txt").exists()
    assert not lists.clear_old(cfg, date(2026, 11, 25))


@pytest.mark.parametrize("words, image", [
    ("Today", events.render(events.Inbox(True, [events.Event("", "All day", "x")]), NOW)),
    ("To do", reminders.render([reminders.Item("x", "")], NOW))])
def test_the_phones_lists_have_plain_headings(words, image):
    left, _, right, _ = ImageOps.invert(image.convert("L").crop((0, 0, image.width, 34))).getbbox()
    assert abs((left + right) / 2 - render.WIDTH / 2) <= 4 and right - left <= render.font("bold", 26).getlength(words) + 2


# --- my trains ---

def board(*rows):
    return trains.Board("Clapham Junction", [trains.Train(NOW.replace(hour=h, minute=m), "Brighton", "2", e, NOW.replace(hour=h, minute=m)) for h, m, e in rows])


def test_trains_too_soon_to_catch_are_skipped(monkeypatch):
    asked = []
    monkeypatch.setattr(trains, "fetch", lambda s, t, session, now: asked.append(s.minutes) or board((8, 5, "On time"), (8, 30, "Cancelled"), (8, 35, "On time"), (8, 40, "On time"), (8, 50, "On time"), (9, 0, "On time")))
    monkeypatch.setattr(trains, "load_token", lambda: trains.Token("t" * 20, "access"))
    cfg = SimpleNamespace(trains=config.TrainSettings(towards="VIC", offset=30, count=3))
    got = mytrains.fetch(cfg, None, NOW)
    assert [f"{t.due:%H:%M}" for t in got.board.trains] == ["08:30", "08:35", "08:40", "08:50"] and asked == [150]
    assert fits(mytrains.render(got, NOW)) and f"{got.start:%H:%M}" == "08:30"
    cfg = SimpleNamespace(trains=config.TrainSettings(offset=0, count=1))
    assert [f"{t.due:%H:%M}" for t in mytrains.fetch(cfg, None, NOW).board.trains] == ["08:05"]


def test_my_trains_is_headed_in_the_middle_like_the_other_lists():
    def ink(name, towards="VIC"):
        mine = mytrains.Mine(trains.Board(name, board((8, 30, "On time")).trains), towards, NOW)
        image = mytrains.render(mine, NOW).convert("L")
        assert fits(image)
        return ImageOps.invert(image.crop((0, 0, image.width, 60))).getbbox()  # above the trains
    for name in ("Clapham Junction", "Ely", "London St Pancras International, all of its many platforms", ""):
        left, _, right, _ = ink(name)
        assert abs((left + right) / 2 - render.WIDTH / 2) <= 4, name
    assert ink("Ely", "")[0] > render.PAD + 60  # not at the left edge


def test_trains_are_left_out_on_other_days_or_without_a_token(monkeypatch):
    monkeypatch.setattr(trains, "load_token", lambda: None)
    cfg = SimpleNamespace(trains=config.TrainSettings())
    assert mytrains.fetch(cfg, None, NOW) is None and mytrains.render(None, NOW) is None
    monkeypatch.setattr(trains, "load_token", lambda: trains.Token("t" * 20, "access"))
    assert mytrains.fetch(cfg, None, NOW + timedelta(days=4)) is None  # Saturday


# --- sudoku ---

@pytest.mark.parametrize("seed", range(8))
def test_sudoku_is_fair(seed):
    grid = sudoku.make(seed)
    assert sum(1 for v in grid if v) == sudoku.CLUES["medium"] and len(sudoku._solutions(list(grid), 2)) == 1
    answer = sudoku._solutions(list(grid), 1)[0]
    for i in range(9):
        for cells in (answer[i * 9:i * 9 + 9], answer[i::9], [answer[i // 3 * 27 + i % 3 * 3 + r * 9 + c] for r in range(3) for c in range(3)]):
            assert sorted(cells) == list(range(1, 10))


def test_sudoku_is_the_same_all_day():
    assert sudoku.fetch(config.load(), None, NOW) == sudoku.fetch(config.load(), None, NOW + timedelta(hours=9)) != sudoku.fetch(config.load(), None, NOW + timedelta(days=1))
    assert sudoku.render(sudoku.make(1), NOW).width == render.WIDTH


@pytest.mark.parametrize("text", ["(pictured" * 60_000, "(" * 200_000, "x" * 2_000_000, "(a) " * 100_000])
def test_a_hostile_answer_does_not_hold_everything_up(text):
    started = time.monotonic()
    history.parse({"selected": [{"year": 1900, "text": text}]}, 2026)
    quote.render(quote.parse([{"q": text, "a": text}]), NOW)
    tube.render(tube.parse([{"name": text, "lineStatuses": [{"statusSeverity": 5, "statusSeverityDescription": text, "reason": text}]}] * 500, ""), NOW)
    assert time.monotonic() - started < 2


# --- blocks on their own ---

def test_any_block_can_be_printed_alone_and_nothing_prints_a_notice(monkeypatch):
    cfg = config.load()
    assert report.build(cfg, NOW, names=["sudoku", "poster"]).image.height > 900
    monkeypatch.setattr(reminders, "fetch", lambda *a: [])
    assert 20 < report.build(cfg, NOW, names=["reminders"]).image.height < 60


def test_private_blocks_never_reach_a_screen(monkeypatch):
    read = []
    for section in report.PRIVATE:
        monkeypatch.setattr(section, "fetch", lambda *a: read.append(a))
    report.build(config.load(), NOW, on_screen=True, names=["events", "reminders", "wifi"])
    assert read == []


@pytest.mark.parametrize("level, least, most", [("easy", 40, 40), ("medium", 32, 32), ("hard", 24, 30)])
def test_sudoku_levels(level, least, most):
    for seed in range(4):
        grid = sudoku.make(seed, level)
        assert least <= sum(1 for v in grid if v) <= most and len(sudoku._solutions(list(grid), 2)) == 1


def test_everything_fits_with_the_open_font_too():
    """What people without Apple's fonts get."""
    if not (config.ROOT / "assets/fonts" / render._FONT_FILES["bold"]).is_file():
        pytest.skip("already tested with it")
    import subprocess
    import sys
    tests = ["test_sections.py", "test_blocks.py", "test_pollen.py", "test_trains.py", "test_weekend.py", "test_events.py", "test_health.py", "test_wifi.py"]
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-k", "not open_font", *(str(config.ROOT / "tests" / t) for t in tests)],
                          env={**__import__("os").environ, "REPORTER_OPEN_FONTS": "1"}, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-1500:]
