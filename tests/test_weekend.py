import dataclasses
import json
from datetime import date, datetime

import pytest

from reporter import config, render
from reporter.sections import weekend



class FakeResponse:
    url = "https://example.test/"
    is_redirect = False

    def __init__(self, content):
        self.chunks = [content]

    def iter_content(self, size):
        yield from self.chunks

    def raise_for_status(self): pass
    def close(self): pass


SAT = date(2026, 11, 28)
BOTH = {"fromDate": "2026-11-28T04:30:00Z", "toDate": "2026-11-30T01:29:00Z"}
SAT_NIGHT = {"fromDate": "2026-11-28T21:00:00Z", "toDate": "2026-11-28T23:45:00Z"}
SUN_ONLY = {"fromDate": "2026-11-29T04:30:00Z", "toDate": "2026-11-30T01:29:00Z"}


def line(name, *statuses, id=None):
    return {"id": id or name.lower(), "name": name, "lineStatuses": [
        {"statusSeverity": sev, "statusSeverityDescription": text, "reason": f"{name}: details", "validityPeriods": [period]}
        for sev, text, period in statuses]}


@pytest.mark.parametrize("period, days", [(BOTH, ""), (SAT_NIGHT, "Sat"), (SUN_ONLY, "Sun"),
                                          ({"fromDate": "2026-11-28T01:00:00Z", "toDate": "2026-11-30T01:29:00Z"}, "")])
def test_days(period, days):
    assert weekend._touched([period], SAT) == ([days] if days else ["Sat", "Sun"])


def test_closed_on_one_day_and_part_closed_on_the_other():
    sunday = {"fromDate": "2026-11-29T04:30:00Z", "toDate": "2026-11-30T01:29:00Z"}
    saturday = {"fromDate": "2026-11-28T04:30:00Z", "toDate": "2026-11-29T01:29:00Z"}
    payload = [{"id": "central", "name": "Central", "lineStatuses": [
        {"statusSeverity": 4, "statusSeverityDescription": "Planned Closure", "reason": "a", "validityPeriods": [saturday]},
        {"statusSeverity": 5, "statusSeverityDescription": "Part Closure", "reason": "b", "validityPeriods": [sunday]}]}]
    assert [(c.status, c.days) for c in weekend.parse(payload, "", SAT).closures] == [("Closed", "Sat"), ("Part closed", "Sun")]


def test_parse_keeps_the_worst_and_skips_the_usual():
    got = weekend.parse([
        line("Windrush", (7, "Reduced Service", BOTH), (5, "Part Closure", BOTH)),
        line("Mildmay", (7, "Reduced Service", SAT_NIGHT)),
        line("Central", (10, "Good Service", BOTH)),
        line("Waterloo & City", (4, "Planned Closure", BOTH), id="waterloo-city"),
    ], "windrush", SAT)
    assert [(c.line, c.status, c.days) for c in got.closures] == [("Windrush", "Part closed", ""), ("Mildmay", "Reduced", "Sat")]
    assert got.favourite.reason == "Windrush: details"


@pytest.mark.parametrize("day", [23, 24, 25, 26])  # Monday to Thursday
def test_left_out_before_friday_without_any_request(day):
    assert weekend.fetch(config.load(), None, datetime(2026, 11, day, 8)) is None
    assert weekend.render(None, datetime(2026, 11, day, 8)) is None


def test_friday_asks_for_the_next_two_days():
    asked = []

    class Session:
        def get(self, url, timeout, stream, **kwargs):
            asked.append(url)
            body = [{"id": "jubilee"}, {"id": "windrush"}] if "/Mode/" in url else [line("Jubilee", (4, "Planned Closure", BOTH))]
            return FakeResponse(json.dumps(body).encode())
    cfg = dataclasses.replace(config.load(), tube=config.TubeSettings(favourite="Jubilee"))
    got = weekend.fetch(cfg, Session(), datetime(2026, 11, 27, 8))
    assert asked[1].endswith("/Line/jubilee,windrush/Status/2026-11-28/to/2026-11-30")
    assert got.favourite.status == "Closed"
    assert weekend.render(got, datetime(2026, 11, 27, 8)).width == render.WIDTH


def test_quiet_weekend():
    assert weekend.render(weekend.Weekend([], None), datetime(2026, 11, 27, 8)).height > 40


def test_longest_names_fit_beside_the_longest_status():
    names, statuses = render.font("semibold", 20), render.font("bold", 20)
    widest = max(statuses.getlength(f"{s} Sat") for s in weekend.SHORT.values())
    assert names.getlength("Hammersmith & City") + 10 + widest <= render.RIGHT - render.PAD
