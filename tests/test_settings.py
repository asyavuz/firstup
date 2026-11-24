import copy
import json
import os
import re
import subprocess
import sys

import pytest

from reporter import config, settings, stations
from reporter.sections import REGISTRY

GOOD = config.as_settings(config.load())


def test_what_is_shipped_is_allowed():
    assert settings.check(GOOD) == (GOOD, [])
    assert set(GOOD) == set(settings.GROUPS)


def test_the_lists_match_the_program():
    assert set(settings.SECTIONS) == set(REGISTRY)
    assert settings.HEAT[1] < 90  # 90 smudges


def changed(group, **values):
    value = copy.deepcopy(GOOD[group])
    value.update(values)
    return {group: value}


BAD = [
    {"sections": []}, {"sections": ["header", "header"]}, {"sections": ["header", "../x"]}, {"sections": "header"}, {"sections": [["header"]]},
    {"schedule": [{"days": ["Mon"], "time": "08:01", "catch_up_until": "10:00"}]},
    {"schedule": [{"days": ["Mon"], "time": "08:00", "catch_up_until": "08:00"}]},
    {"schedule": [{"days": ["Mon"], "time": "24:00", "catch_up_until": "25:00"}]},
    {"schedule": [{"days": ["Mon"], "time": "8:00", "catch_up_until": "10:00"}]},
    {"schedule": [{"days": [], "time": "08:00", "catch_up_until": "10:00"}]},
    {"schedule": [{"days": ["Mon"], "time": "08:00", "catch_up_until": "10:00"}] * 2},
    {"schedule": [{"days": ["Mon"], "time": "08:00", "catch_up_until": "10:00", "x": 1}]}, {"schedule": {}},
    {"schedule": [{"days": ["Mon"], "time": "٠٨:٠٠", "catch_up_until": "10:00"}]},
    changed("weather", latitude=91), changed("weather", longitude="0"), changed("weather", latitude=float("nan")),
    changed("weather", latitude=float("inf")), changed("weather", latitude=True), changed("weather", uv_from=0),
    changed("weather", uv_from=12), changed("weather", uv_from=3.0), changed("weather", place=""), changed("weather", place="x" * 61),
    changed("weather", place="a‮b"), changed("tube", favourite="Northen"), changed("tube", modes=[]), changed("tube", modes=["tube/../x"]),
    changed("news", count=0), changed("news", count=9), changed("news", feeds=[]), changed("news", feeds=[{"name": "A", "url": "https://a.example/x"}] * 7),
    changed("news", feeds=[{"name": "A", "url": "https://a.example/x"}] * 2), changed("news", feeds=[{"name": "", "url": "https://a.example/x"}]),
    changed("trains", station="clj"), changed("trains", station="CL"), changed("trains", station="C?J"), changed("trains", station="ÉÉÉ"),
    changed("trains", towards="CLJ"), changed("trains", towards="x"), changed("button", taps={"shutdown": 1}), changed("button", taps={"wifi": 0}), changed("button", taps={"wifi": 10}), changed("button", taps=["wifi"]),
    changed("button", holds={"wifi": 5}), changed("button", holds={"wifi": 1.5}), changed("button", extra={}), changed("pollen", kinds=[]), changed("pollen", level="low"),
    changed("warnings", region="xx"), changed("sudoku", level="fiendish"), changed("warnings", region="../x"), changed("trains", offset=7), changed("trains", offset=125), changed("trains", count=0), changed("trains", days=["Caturday"]), changed("printer", heat_time=90), changed("printer", heat_time=44), changed("printer", heat_time="70"),
    {"printer": {"heat_time": 70, "port": "/dev/sda"}}, {"printer": 70}, {"nonsense": 1}, {"events": {"inbox": "/etc/passwd"}}, {"timezone": "UTC"},
]


@pytest.mark.parametrize("raw", BAD, ids=range(len(BAD)))
def test_bad_values_are_refused_and_cannot_stop_anything(raw, tmp_path):
    good, problems = settings.check(raw)
    assert good == {} and len(problems) == 1
    with pytest.raises(ValueError):
        settings.save(raw, tmp_path / "s.json")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({**raw, "tube": raw.get("tube", changed("tube", favourite="Central")["tube"])}))
    cfg = config.load(changes=path)
    assert cfg.problems
    assert cfg.sections == config.load().sections and cfg.printer == config.load().printer
    if "tube" not in raw:
        assert cfg.tube.favourite == "Central"  # the rest still counts


@pytest.mark.parametrize("url", [
    "http://feeds.example.com/", "https://192.168.1.1/x", "https://[::1]/x", "https://localhost/x", "https://router.local/x",
    "https://user:pw@feeds.example.com/", "https://feeds.example.com:8443/", "https://feeds.example.com/#x", "https://feeds.example.com/a b",
    "https://feeds.example.com/\n", "javascript:alert(1)//aaaa", "https://2130706433/x", "https://0x7f.1/x", "https://feeds.example.com/<b>",
    "https://feeds.example.com:99999/", "https://" + "a" * 300 + ".com/", "//feeds.example.com/", 5, None, "https://nas.home/rss", "https://a%2eb.example/rss",
])
def test_feed_addresses(url):
    with pytest.raises(ValueError):
        settings.feed_url(url)


@pytest.mark.parametrize("url", [f.url for f in config.load().news.feeds] + ["https://example.com/feed?a=1&b=2", "https://example.com:443/x"])
def test_ordinary_feed_addresses_are_fine(url):
    assert settings.feed_url(url) == url


def test_every_setting_reaches_the_program(tmp_path):
    path = tmp_path / "settings.json"
    new = {
        "sections": ["news", "header"],
        "schedule": [{"days": ["Sun", "Mon"], "time": "07:30", "catch_up_until": "09:00"}],
        "weather": {"place": "Leeds", "latitude": 53.8, "longitude": -1.55, "uv_from": 6},
        "tube": {"favourite": "", "modes": ["dlr"]},
        "news": {"count": 2, "feeds": [{"name": "X", "url": "https://x.example/rss"}]},
        "warnings": {"region": "yh"},
        "pollen": {"level": "high", "kinds": ["birch"]},
        "sudoku": {"level": "hard"},
        "trains": {"station": "LDS", "towards": "YRK", "offset": 25, "count": 5, "days": ["Mon", "Sat"]},
        "button": {"taps": {"receipt": 2, "sudoku": 4}, "holds": {"wifi": 3}},
        "printer": {"heat_time": 65},
    }
    settings.save(new, path)
    cfg = config.load(changes=path)
    assert cfg.problems == ()
    want = copy.deepcopy(new)
    want["schedule"][0]["days"] = ["Mon", "Sun"]
    assert config.as_settings(cfg) == want
    assert cfg.printer.row_time == config.load().printer.row_time and cfg.button.button_pin == 23


def test_no_automatic_prints_at_all_is_allowed(tmp_path):
    settings.save({"schedule": []}, tmp_path / "s.json")
    assert config.load(changes=tmp_path / "s.json").schedule == ()


@pytest.mark.parametrize("content", [b"", b"not json", b"[]", b'"x"', b"\xff\xfe\x00", b"[" * 60000, b"{" * 70000, b'{"sections": ' + b" " * 70000 + b"[]}"])
def test_a_damaged_file_is_ignored_and_reported(tmp_path, content):
    path = tmp_path / "s.json"
    path.write_bytes(content)
    cfg = config.load(changes=path)
    assert config.as_settings(cfg) == GOOD and len(cfg.problems) == 1


def test_problems_stay_few_however_many_there_are(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({f"x{i}": 1 for i in range(5000)}))
    assert len(config.load(changes=path).problems) == settings.MAX_PROBLEMS


def test_odd_files_are_not_followed_or_waited_for(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text(json.dumps({"printer": {"heat_time": 50}}))
    (tmp_path / "link").symlink_to(secret)
    os.mkfifo(tmp_path / "pipe")
    (tmp_path / "folder").mkdir()
    for name in ("link", "pipe", "folder"):
        values, problems = settings.load(tmp_path / name)
        assert values == {} and len(problems) == 1
    assert settings.load(tmp_path / "missing") == ({}, [])


def test_saving_replaces_whole_files_and_leaves_nothing_behind(tmp_path):
    path = tmp_path / "s.json"
    settings.save({"printer": {"heat_time": 60}}, path)
    settings.save({"printer": {"heat_time": 65}}, path)
    assert settings.load(path) == ({"printer": {"heat_time": 65}}, [])
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


@pytest.mark.parametrize("module", ["settings", "stations"])
def test_the_web_program_can_use_these_without_anything_installed(module):
    code = f"import sys; sys.path.insert(0, {str(config.ROOT)!r}); import reporter.{module}; " \
           "print(sorted(m for m in sys.modules if m.split('.')[0] in ('requests', 'PIL', 'serial', 'segno')))"
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


@pytest.mark.parametrize("text", ["CLJ", "clj", "Clapham Junction (CLJ)", "clapham  junction", " Clapham Junction "])
def test_stations_are_found_as_people_type_them(text):
    assert stations.find(text).code == "CLJ"


def test_stations_list():
    assert len(stations.all_stations()) > 2500 and stations.find("Nowhere") is None and stations.find("") is None
    for station in stations.all_stations().values():
        assert stations.find(station.label) == station
        settings._station(station.code, "x")
        settings.weather({"place": station.name, "latitude": station.latitude, "longitude": station.longitude, "uv_from": 3})


@pytest.mark.parametrize("text, says", [
    ("[weather]\nlatitud = 5", "latitud"), ("[trian]\nstation = 'X'", "trian"), ("sections = [", "local.toml"), ("timezone = 'Europe/Lodon'", "Lodon"),
    ("[[schedule]]\ndays = ['Mon']\ntime = '09:00'", "catch_up_until"), ("weather = 5", "[weather]"), ("[schedule]\ndays = ['Mon']", "double brackets"), ("[button]\ntaps = [1, 2]", "taps must look like"), ("[[news.feeds]]\nname = 'X'\nlink = 'y'", "link"),
])
def test_a_mistake_in_the_files_is_named(tmp_path, monkeypatch, text, says):
    (tmp_path / "local.toml").write_text(text)
    monkeypatch.setattr(config, "LOCAL", tmp_path / "local.toml")
    with pytest.raises((ValueError, KeyError), match=re.escape(says)):
        config.load(changes=config.NO_CHANGES)


def test_what_the_web_interface_does_not_offer_is_named(tmp_path, monkeypatch):
    assert config.not_offered() == []
    (tmp_path / "local.toml").write_text("[printer]\nheat_time = 90")
    monkeypatch.setattr(config, "LOCAL", tmp_path / "local.toml")
    assert "heat" in config.not_offered()[0]


def test_nothing_the_program_needs_is_hidden_from_git():
    files = [str(p.relative_to(config.ROOT)) for folder in ("reporter", "reporter_web", "deploy", "tests")
             for p in (config.ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store"]
    done = subprocess.run(["git", "check-ignore", "--no-index", *files], cwd=config.ROOT, capture_output=True, text=True)
    if done.returncode not in (0, 1):
        pytest.skip("not a git checkout")
    assert done.stdout == ""


def test_a_missing_settings_disk_is_reported(tmp_path):
    assert settings.load(tmp_path / "settings" / "settings.json") == ({}, ["the settings disk is missing"])
    (tmp_path / "settings").mkdir()
    assert settings.load(tmp_path / "settings" / "settings.json") == ({}, [])
    assert settings.load(config.NO_CHANGES) == ({}, [])


def test_groups_this_version_cannot_read_are_kept(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"sections": ["header", "from a newer version"], "moon": {"x": 1}, "tube": {"favourite": "", "modes": ["dlr"]}}))
    settings.change("printer", {"heat_time": 60}, path)
    assert json.loads(path.read_text())["sections"] == ["header", "from a newer version"] and "moon" in json.loads(path.read_text())
    assert settings.load(path)[0] == {"tube": {"favourite": "", "modes": ["dlr"]}, "printer": {"heat_time": 60}}
    settings.change("printer", None, path)
    assert "printer" not in json.loads(path.read_text())
    with pytest.raises(ValueError):
        settings.change("printer", {"heat_time": 90}, path)


def test_a_file_that_cannot_be_read_just_now_is_not_replaced(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    settings.change("printer", {"heat_time": 60}, path)
    monkeypatch.setattr(settings, "_read", lambda p: ({}, [settings.UNREADABLE]))
    with pytest.raises(OSError):
        settings.change("schedule", [], path)
    assert json.loads(path.read_text()) == {"printer": {"heat_time": 60}}


def test_the_order_in_a_list_is_not_a_change():
    assert settings.tube({"favourite": "", "modes": ["dlr", "tube"]}) == settings.tube({"favourite": "", "modes": ["tube", "dlr"]})
    slots = [{"days": ["Sun"], "time": "10:00", "catch_up_until": "12:00"}, {"days": ["Mon"], "time": "08:00", "catch_up_until": "10:00"}]
    assert settings.schedule(slots) == settings.schedule(slots[::-1])


def test_a_full_settings_file_can_still_be_changed(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"x" * 65520: 1}))
    settings.change("schedule", [], path)
    assert settings.load(path) == ({"schedule": []}, [])


def test_good_groups_count_however_many_bad_ones_come_before(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({**{f"x{i}": 1 for i in range(20)}, "printer": {"heat_time": 60}}))
    assert settings.load(path)[0] == {"printer": {"heat_time": 60}}


def test_older_train_settings_leave_the_rest_to_the_files(tmp_path, monkeypatch):
    (tmp_path / "local.toml").write_text("[trains]\noffset = 20\ncount = 5\ndays = ['Sat']")
    (tmp_path / "s.json").write_text('{"trains": {"station": "LDS", "towards": "YRK"}}')
    monkeypatch.setattr(config, "LOCAL", tmp_path / "local.toml")
    got = config.load(changes=tmp_path / "s.json").trains
    assert (got.station, got.towards, got.offset, got.count, got.days) == ("LDS", "YRK", 20, 5, ("Sat",))


def test_train_settings_saved_before_there_was_more_to_choose(tmp_path):
    (tmp_path / "s.json").write_text('{"trains": {"station": "CLJ", "towards": "VIC"}}')
    cfg = config.load(changes=tmp_path / "s.json")
    assert cfg.problems == () and cfg.trains == config.TrainSettings(towards="VIC")
