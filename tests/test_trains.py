import stat
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from reporter import http, render, trains
from reporter.config import TrainSettings

NOW = datetime(2026, 11, 24, 11, 31, tzinfo=ZoneInfo("Europe/London"))
TOKEN = trains.Token("a" * 40, "access")


def service(due, *places, forecast=None, platform="3", actual=None, cancelled=False, display="CALL",
            call="ADVERTISED_OPEN", passenger=True, mode="TRAIN", left=None):
    departure = {"scheduleAdvertised": f"2026-11-24T{due}:00Z", "isCancelled": cancelled}
    if forecast:
        departure["realtimeForecast"] = f"2026-11-24T{forecast}Z"
    if left:
        departure["realtimeActual"] = f"2026-11-24T{left}:00Z"
    return {"temporalData": {"departure": departure, "displayAs": display, "scheduledCallType": call, "realtimeCallType": call},
            "locationMetadata": {"platform": {"planned": platform, "actual": actual}},
            "scheduleMetadata": {"inPassengerService": passenger, "modeType": mode},
            "destination": [{"location": {"description": p}} for p in places]}


def rows(*services, now=NOW, minutes=60):
    board = trains.parse({"query": {"location": {"description": "Clapham Junction"}}, "services": list(services)}, now, minutes)
    assert board.station == "Clapham Junction"
    return [(f"{t.due:%H:%M}", t.place, t.platform, t.expected) for t in board.trains]


@pytest.mark.parametrize("given, row", [
    (service("11:34", "London Victoria", forecast="11:34:20"), ("11:34", "London Victoria", "3", "On time")),
    (service("11:36", "Guildford", forecast="11:41:30", actual="6"), ("11:36", "Guildford", "6", "11:41")),
    (service("11:40", "East Croydon", forecast="11:39:00"), ("11:40", "East Croydon", "3", "On time")),
    (service("11:45", "Epsom", cancelled=True, platform=None), ("11:45", "Epsom", "", "Cancelled")),
    (service("11:45", "Epsom", display="DIVERTED"), ("11:45", "Epsom", "3", "Cancelled")),
    (service("11:50", "Woking"), ("11:50", "Woking", "3", "")),                                   # nothing known yet
    (service("11:55", "Portsmouth", "Bognor Regis"), ("11:55", "Portsmouth & Bognor Regis", "3", "")),              # divides on the way
    (service("11:55", "Kingston", mode="REPLACEMENT_BUS"), ("11:55", "Kingston", "bus", "")),
    (service("11:20", "East Croydon", forecast="11:43:00"), ("11:20", "East Croydon", "3", "11:43")),       # late, still to come
    (service("11:58"), ("11:58", "Unknown", "3", "")),
])
def test_rows(given, row):
    assert rows(given) == [row]


@pytest.mark.parametrize("given", [
    service("11:25", "London Victoria", left="11:26"),              # gone
    service("11:25", "London Victoria"),                            # was due, nothing known
    service("11:20", "London Victoria", cancelled=True),
    service("11:40", "London Victoria", display="PASS"), service("11:40", "London Victoria", display=None),
    service("11:40", "London Victoria", display="TERMINATES"),
    service("11:40", "London Victoria", call="OPERATIONAL_ONLY"), service("11:40", "London Victoria", call="ADVERTISED_SET_DOWN"),
    service("11:40", "Depot", passenger=False),
    service("12:32", "London Victoria"), service("12:20", "London Victoria", forecast="12:40:00"),
    {}, {"temporalData": None}, {"temporalData": {"displayAs": "CALL", "departure": {}}},
])
def test_trains_nobody_can_catch_are_left_out(given):
    assert rows(given) == []


def test_in_order_and_across_midnight():
    late = datetime(2026, 11, 24, 23, 40, tzinfo=NOW.tzinfo)
    after = service("11:00", "Guildford")
    after["temporalData"]["departure"]["scheduleAdvertised"] = "2026-11-25T00:10:00Z"
    assert [r[0] for r in rows(after, service("23:50", "London Victoria"), now=late)] == ["23:50", "00:10"]


def test_summer_time_is_shown_as_local_time():
    summer = datetime(2026, 7, 1, 11, 31, tzinfo=NOW.tzinfo)
    one = service("11:00", "London Victoria")
    one["temporalData"]["departure"]["scheduleAdvertised"] = "2026-07-01T10:45:00Z"
    assert rows(one, now=summer)[0][0] == "11:45"


class Session:
    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    def get(self, url, timeout, stream, **kwargs):
        assert kwargs["allow_redirects"] is False
        self.asked.append((url, kwargs["headers"]["Authorization"], kwargs["params"]))
        status, body = self.replies.pop(0)
        response = requests.Response()
        response.status_code, response.url = status, url
        response.iter_content = lambda size: iter([body])
        response.close = lambda: None
        if status in (301, 302):
            response.headers["Location"] = "https://elsewhere.example/"
        return response


def test_asks_for_the_station_and_the_time():
    session = Session((200, b'{"services": []}'))
    trains.fetch(TrainSettings(towards="VIC"), TOKEN, session, NOW)
    url, auth, params = session.asked[0]
    assert url == "https://data.rtt.io/rtt/location" and auth == f"Bearer {TOKEN.token}"
    assert params == {"code": "gb-nr:CLJ", "filterTo": "gb-nr:VIC", "timeFrom": "2026-11-24T11:01:00", "timeWindow": 90}


def test_a_refresh_token_is_swapped_first():
    session = Session((200, b'{"token": "short-lived-token-123"}'), (204, b""))
    assert trains.fetch(TrainSettings(), trains.Token("r" * 40, "refresh"), session, NOW).trains == []
    assert [a[1] for a in session.asked] == ["Bearer " + "r" * 40, "Bearer short-lived-token-123"]
    assert [a[0].rsplit("/", 1)[1] for a in session.asked] == ["get_access_token", "location"]


@pytest.mark.parametrize("reply", [(401, b"{}"), (429, b""), (302, b""), (200, b"<html>"), (200, b'[]')])
def test_any_failure_prints_a_notice_and_never_the_token(monkeypatch, caplog, reply):
    session = Session(reply)
    monkeypatch.setattr(trains, "load_token", lambda: TOKEN)
    monkeypatch.setattr(http, "make_session", lambda: session)
    img = trains.build(TrainSettings(), NOW)
    assert img.mode == "1" and img.height < 60 and TOKEN.token not in caplog.text
    assert session.replies == [] and "no train times" in caplog.text and "data.rtt.io" not in caplog.text


def test_not_set_up(monkeypatch, tmp_path):
    monkeypatch.setattr(trains, "PATH", tmp_path / "rail.json")
    assert trains.load_token() is None and trains.build(TrainSettings(), NOW).height < 60
    (tmp_path / "rail.json").write_text('{"token": "x", "kind": "access"}')
    assert trains.load_token() is None


def test_page_fits_the_paper_however_odd():
    many = [service(f"11:{m:02d}", "Southampton Central & " + "W" * 300, platform="12345678", forecast="12:01:00") for m in range(31, 60)] * 3
    board = trains.parse({"query": {"location": {"description": "S" * 400}}, "services": many}, NOW)
    img = trains.page(TrainSettings(), board, NOW)
    assert img.mode == "1" and img.width == render.WIDTH and img.height < 1500
    assert img.crop((render.RIGHT + 1, 90, render.WIDTH, img.height)).convert("L").getextrema()[0] == 255
    assert trains.page(TrainSettings(minutes=90), trains.Board("", []), NOW).height < 200


@pytest.mark.parametrize("works_as, kind", [("refresh", "refresh"), ("access", "access")])
def test_setup_finds_out_which_token_it_is(monkeypatch, tmp_path, capsys, works_as, kind):
    path = tmp_path / "c" / "rail.json"
    monkeypatch.setattr(trains, "PATH", path)
    monkeypatch.setattr(trains.getpass, "getpass", lambda p: "t" * 40 + "\n")

    def fetch(settings, token, session, now):
        if token.kind != works_as:
            raise RuntimeError("no")
        return trains.Board("Clapham Junction", [])
    monkeypatch.setattr(trains, "fetch", fetch)
    assert trains.setup(TrainSettings(), NOW) == 0
    assert trains.load_token() == trains.Token("t" * 40, kind)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "t" * 40 not in capsys.readouterr().out


def test_setup_saves_nothing_that_does_not_work(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(trains, "PATH", tmp_path / "rail.json")
    monkeypatch.setattr(trains.getpass, "getpass", lambda p: "t" * 40)
    monkeypatch.setattr(trains, "fetch", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    assert trains.setup(TrainSettings(), NOW) == 1 and not (tmp_path / "rail.json").exists()
    monkeypatch.setattr(trains.getpass, "getpass", lambda p: "bad token\r\nX: y")
    assert trains.setup(TrainSettings(), NOW) == 1 and not (tmp_path / "rail.json").exists()


@pytest.mark.parametrize("towards, words", [("VIC", "Calling at London Victoria"), ("ZZZ", "Calling at ZZZ"), ("", None)])
def test_the_page_says_where_the_trains_must_call(monkeypatch, towards, words):
    said = []
    real = render.Canvas.text
    monkeypatch.setattr(render.Canvas, "text", lambda self, x, y, text, *a: (said.append(text), real(self, x, y, text, *a)))
    for board in (trains.Board("Clapham Junction", []), trains.Board("Clapham Junction", [trains.Train(NOW, "East Croydon", "2", "On time")])):
        said.clear()
        trains.page(TrainSettings(towards=towards), board, NOW)
        assert [t for t in said if t.startswith("Calling")] == ([words] if words else [])


def test_the_longest_station_name_fits():
    from reporter import stations
    longest = max(stations.all_stations().values(), key=lambda s: len(s.name))
    img = trains.page(TrainSettings(towards=longest.code), trains.Board("Clapham Junction", []), NOW)
    top = img.crop((0, 0, render.WIDTH, 60)).convert("L")
    assert top.crop((0, 0, 2, 60)).getextrema()[0] == 255 and top.crop((render.WIDTH - 2, 0, render.WIDTH, 60)).getextrema()[0] == 255
