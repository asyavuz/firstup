from datetime import datetime

import pytest

from reporter import render, report
from reporter.sections import REGISTRY, closing, header, news, quote, tube, weather

NOW = datetime(2026, 11, 24, 8, 0)


def tfl(name, *statuses):
    return {"name": name, "lineStatuses": [
        {"statusSeverity": sev, "statusSeverityDescription": text, "reason": reason}
        for sev, text, reason in statuses]}


# --- tube: the section that crashed the old program ---

def test_unknown_lines_do_not_crash():
    status = tube.parse([tfl("Liberty", (10, "Good Service", None)),
                         tfl("Some Future Line", (6, "Severe Delays", "Signal failure"))], "Jubilee")
    assert [ln.name for ln in status.lines] == ["Liberty", "Some Future Line"]
    assert status.favourite is None
    assert tube.render(status, NOW).width == render.WIDTH


def test_worst_status_wins():
    status = tube.parse([tfl("Jubilee", (10, "Good Service", None), (6, "Severe Delays", "Trespasser"))], "jubilee")
    assert status.favourite.status == "Severe Delays"
    assert not status.favourite.good


def test_line_without_statuses():
    assert tube.parse([{"name": "DLR", "lineStatuses": []}], "x").lines[0].status == "No data"


def test_only_disrupted_lines_take_space():
    def height(bad):
        lines = [tfl("Jubilee", (10, "Good Service", None))]
        lines += [tfl(f"Line {i}", (6, "Severe Delays", "") if i < bad else (10, "Good Service", None)) for i in range(18)]
        return tube.render(tube.parse(lines, "Jubilee"), NOW).height
    assert height(0) < height(3) < height(18)


def test_longest_line_and_status_share_a_row():
    status = max(render.font("bold", 20).getlength(tube.SHORT_STATUS.get(s, s))
                 for s in ("No Step Free Access", "Change of frequency", "Planned Closure", "Part Suspended"))
    assert render.font("semibold", 20).getlength("Hammersmith & City") + 10 + status <= render.RIGHT - render.PAD


# --- news ---

def rss(*titles):
    return ("<rss><channel><title>Feed</title>" +
            "".join(f"<item><title>{t}</title></item>" for t in titles) +
            "</channel></rss>").encode()


def test_parse_feed_unescapes_and_strips():
    assert news.parse_feed(rss("PM &amp;amp; Chancellor  agree 🎉", "", "Two")) == ["PM & Chancellor agree", "Two"]


def test_pick_alternates_and_dedupes():
    got = news.pick({"A": ["one", "two", "three"], "B": ["ONE", "four"]}, 4)
    assert [(h.title, h.source) for h in got] == [("one", "A"), ("four", "B"), ("two", "A"), ("three", "A")]


def test_pick_with_too_few():
    assert len(news.pick({"A": ["x"], "B": []}, 5)) == 1


# --- weather ---

@pytest.mark.parametrize("deg, name", [(0, "N"), (359, "N"), (360, "N"), (11.25, "N"), (45, "NE"), (110, "ESE"),
                                       (180, "S"), (348, "NNW")])
def test_compass(deg, name):
    assert weather.compass(deg) == name


@pytest.mark.parametrize("kmh, force", [(0, 0), (1, 1), (12, 3), (61, 7), (117, 11), (118, 12), (250, 12)])
def test_beaufort(kmh, force):
    assert weather.beaufort(kmh) == force


def test_every_weather_icon_exists_and_label_fits():
    for code, (label, *icons) in weather.WMO.items():
        for name in icons:
            assert render.icon(name, 32)
        assert render.font("semibold", 22).getlength(label) <= weather.LABEL_WIDTH, label


def test_worst_case_grid_text_fits_its_cell():
    assert weather.CELL_TEXT + render.font("semibold", 20).getlength("188 km/h") <= weather.CELL


def test_unknown_weather_code():
    label, icon = weather.describe(1234, True)
    assert label == "Unknown" and render.icon(icon, 32)


def open_meteo(rain=(), snow=(), **current):
    base = {"temperature_2m": -3.6, "apparent_temperature": -9.1, "relative_humidity_2m": 100, "weather_code": 99,
            "pressure_msl": 1024.4, "wind_speed_10m": 119.0, "wind_gusts_10m": 160.2, "wind_direction_10m": 350,
            "is_day": 1}
    base.update(current)
    hours = [f"2026-11-24T{h:02d}:00" for h in range(24)]
    return {"current": base,
            "hourly": {"time": hours, "temperature_2m": [h / 2 for h in range(24)], "weather_code": [73 if h in snow else 2 for h in range(24)],
                       "precipitation_probability": [80 if h in (*rain, *snow) else 5 for h in range(24)],
                       "precipitation": [1.2 if h in (*rain, *snow) else 0.0 for h in range(24)],
                       "is_day": [int(8 <= h < 16) for h in range(24)]},
            "daily": {"sunrise": ["2026-11-24T07:33"], "sunset": ["2026-11-24T16:00"], "uv_index_max": [0.45],
                      "temperature_2m_max": [7.7], "temperature_2m_min": [3.0]}}


def test_weather_parse():
    data = weather.parse(open_meteo())
    assert (data.temp, data.feels_like, data.sunrise, data.sunset) == (-4, -9, "07:33", "16:00")
    assert [s.label for s in data.slots] == ["Morning", "Noon", "Afternoon", "Evening"]
    assert data.slots[0].icon != data.slots[3].icon  # day and night icons differ
    assert weather.render(data, NOW).width == render.WIDTH


@pytest.mark.parametrize("rain, hour, text", [
    ((), 8, "3 to 8°C, dry all day"),
    ((), 15, "3 to 8°C, dry for the rest of today"),
    ((15, 16, 17), 8, "3 to 8°C. Rain 15:00–18:00"),
    ((9, 15, 16), 8, "3 to 8°C. Rain 09:00–10:00 and 15:00–17:00"),
    ((9, 12, 15, 18), 8, "3 to 8°C. Rain on and off 09:00–19:00"),
    (range(24), 8, "3 to 8°C. Rain most of the day"),
    ((3, 4, 5), 8, "3 to 8°C, dry all day"),       # already over
    ((23,), 8, "3 to 8°C, dry all day"),           # too late to matter
])
def test_outlook(rain, hour, text):
    got, wet = weather.outlook(open_meteo(rain=rain), hour)
    assert got == text and wet == ("Rain" in text)


def with_uv(**by_hour):
    payload = open_meteo()
    payload["hourly"]["uv_index"] = [by_hour.get(f"h{h}", 0.0) for h in range(24)]
    return payload


@pytest.mark.parametrize("uv, hour, expected", [
    ({}, 8, None),
    ({"h12": 2.4}, 8, None),
    ({"h12": 2.5}, 8, (3, "moderate", "12:00–13:00")),
    ({"h11": 3, "h12": 5.4, "h13": 5.2, "h14": 3.1}, 8, (5, "moderate", "11:00–15:00")),
    ({"h12": 6}, 8, (6, "high", "12:00–13:00")),
    ({"h12": 8}, 8, (8, "very high", "12:00–13:00")),
    ({"h12": 11.2}, 8, (11, "extreme", "12:00–13:00")),
    ({"h11": 6, "h14": 3}, 13, (3, "moderate", "14:00–15:00")),   # only what is still to come
    ({"h12": 6}, 20, None),                                        # over for today
])
def test_sun_warning(uv, hour, expected):
    assert weather.sun_warning(with_uv(**uv), hour) == expected


def test_sun_warning_without_data():
    payload = open_meteo()
    assert weather.sun_warning(payload, 8) is None
    payload["hourly"]["uv_index"] = [None] * 24
    assert weather.sun_warning(payload, 8) is None


def test_sun_line_takes_space_only_when_needed():
    plain = weather.render(weather.parse(open_meteo()), NOW).height
    assert weather.render(weather.parse(with_uv(h12=2)), NOW).height == plain
    assert plain < weather.render(weather.parse(with_uv(h12=7)), NOW).height < plain + 70


def test_sun_text_never_reaches_the_icons():
    fnt = render.font("bold", 22)
    widest = max(fnt.getlength(f"UV {limit}, {level}") for limit, level in (*weather.UV_LEVELS, (10, "very high"), (12, "extreme")))
    assert weather.UV_TEXT_X + widest + 4 <= render.RIGHT - 3 * weather.UV_STEP
    assert weather.UV_ICON < weather.UV_STEP


def test_outlook_snow_and_missing_values():
    assert weather.outlook(open_meteo(snow=(10, 11)), 8)[0] == "3 to 8°C. Snow 10:00–12:00"
    payload = open_meteo()
    payload["hourly"]["precipitation_probability"] = [None] * 24
    payload["hourly"]["precipitation"] = [None] * 24
    assert weather.outlook(payload, 8) == ("3 to 8°C, dry all day", False)


def test_unlikely_or_trace_rain_is_not_rain():
    payload = open_meteo(rain=(12,))
    payload["hourly"]["precipitation_probability"][12] = 30
    assert weather.outlook(payload, 8)[1] is False
    payload = open_meteo(rain=(12,))
    payload["hourly"]["precipitation"][12] = 0.05
    assert weather.outlook(payload, 8)[1] is False


# --- quote, closing, drawing helpers ---

def test_long_quote_stays_on_paper():
    data = quote.parse([{"q": "word " * 80 + "x" * 200, "a": "Someone"}])
    img = quote.render(data, NOW)
    fnt = render.font("semibold", 21)
    assert all(fnt.getlength(ln) <= 300 for ln in render.wrap(data.text, fnt, 300))
    assert img.height > 100


@pytest.mark.parametrize("hour, word", [(8, "day"), (19, "evening"), (23, "night"), (2, "night")])
def test_part_of_day(hour, word):
    assert closing.part_of_day(datetime(2026, 1, 1, hour)) == word


def test_huge_words_are_quick_and_bounded():
    """One 5000-character word used to take minutes."""
    import time
    fnt = render.font("semibold", 20)
    started = time.monotonic()
    assert len(render.wrap("x" * 100_000, fnt, 300)) == render.MAX_LINES
    assert render.fit("y" * 100_000, fnt, 300).endswith("…")
    news.render([news.Headline("z" * 50_000, "w" * 50_000)], NOW)
    quote.render(quote.Quote("q" * 50_000, "a"), NOW)
    assert time.monotonic() - started < 2


def test_wrap_keeps_every_word_in_order():
    fnt = render.font("semibold", 20)
    text = "Restaurateur and sister cleared of murdering their 100-year-old mother in a long trial"
    lines = render.wrap(text, fnt, 200)
    assert " ".join(lines) == text
    assert all(fnt.getlength(line) <= 200 for line in lines)


def test_canvas_never_pads_with_black():
    canvas = render.Canvas()
    canvas.y = 9000
    assert canvas.finish().getextrema() == (255, 255)


def test_wrap_limits_lines():
    fnt = render.font("semibold", 20)
    lines = render.wrap("a fairly long headline that goes on and on and on", fnt, 100, max_lines=2)
    assert len(lines) == 2 and lines[-1].endswith("…")


def test_forecast_labels_do_not_touch():
    fnt = render.font("bold", 19)
    assert all(fnt.getlength(label) <= render.WIDTH / len(weather.SLOTS) - 4 for _, label in weather.SLOTS)


def test_right_aligned_text_keeps_off_the_pale_edge():
    edge = (render.RIGHT + 1, 0, render.WIDTH)
    for img in (header.render(None, NOW),
                quote.render(quote.Quote("Short.", "Colin Powell"), NOW),
                tube.render(tube.parse([tfl("Central", (9, "Minor Delays", ""))], "Jubilee"), NOW),
                news.render([news.Headline("word " * 30, "The Guardian")], NOW)):
        strip = render.to_bitmap(img).crop((edge[0], 0, edge[2], img.height))
        assert strip.convert("L").getextrema()[0] == 255


def test_the_degree_sign_is_kept_and_emoji_are_not():
    assert render.clean("48°C © ™ 🎉 ★ ok") == "48°C © ™ ok"


# --- one broken section must not stop the receipt ---

class Broken:
    @staticmethod
    def fetch(cfg, session, now):
        raise RuntimeError("API is down")


def test_failed_sections_are_reported_not_fatal(monkeypatch):
    from reporter import config
    import dataclasses
    for name in ("weather", "tube", "news", "quote"):
        monkeypatch.setitem(REGISTRY, name, Broken)
    cfg = dataclasses.replace(config.load(), sections=("header", "weather", "tube", "news", "quote", "closing", "typo"))
    result = report.build(cfg, NOW)
    assert result.failed == ["weather", "tube", "news", "quote", "typo"]
    assert result.image.mode == "1" and result.image.width == render.WIDTH


def test_the_log_says_where_it_failed_but_not_what_was_asked_for(monkeypatch, caplog):
    import requests

    class Secretive:
        @staticmethod
        def fetch(cfg, session, now):
            raise requests.ConnectionError("cannot reach https://weather.example/?latitude=51.5085&key=hidden")
    monkeypatch.setitem(REGISTRY, "weather", Secretive)
    report.build(config_with("weather"), NOW)
    assert "block weather failed: ConnectionError" in caplog.text and "report.py:" in caplog.text
    assert "latitude" not in caplog.text and "hidden" not in caplog.text


def config_with(*sections):
    import dataclasses
    from reporter import config
    return dataclasses.replace(config.load(), sections=sections)


def test_the_weather_place_is_asked_for_roughly():
    from reporter.config import WeatherSettings
    assert WeatherSettings(latitude=51.50849, longitude=-0.12571).position == {"latitude": 51.51, "longitude": -0.13}
