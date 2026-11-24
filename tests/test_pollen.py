from datetime import datetime

import pytest

from reporter import config, render, settings
from reporter.sections import REGISTRY, pollen

NOW = datetime(2026, 6, 10, 8, 0)
ALL = tuple(settings.POLLENS)


def payload(**kinds):
    """Hours given as {hour: grains}; the rest is 0."""
    data = {f"{kind}_pollen": [values.get(h, 0) for h in range(24)] for kind, values in kinds.items()}
    return {"hourly": {"time": [f"2026-06-10T{h:02d}:00" for h in range(24)], **data}}


def got(data, least="moderate", hour=8, kinds=ALL):
    return [(p.kind, pollen.LEVELS[p.level], p.hours) for p in pollen.parse(data, kinds, least, hour)]


def test_the_lists_match():
    assert set(pollen.BANDS) == set(settings.POLLENS) and pollen.LEVELS == tuple(settings.POLLEN_LEVELS) and "pollen" in REGISTRY
    assert config.load().pollen == config.PollenSettings() and "pollen" in config.load().sections


@pytest.mark.parametrize("grains, level", [(29.9, None), (30, "moderate"), (49.9, "moderate"), (50, "high"), (149, "high"), (150, "very high")])
def test_grass_levels(grains, level):
    assert got(payload(grass={13: grains})) == ([("grass", level, "13:00–14:00")] if level else [])


@pytest.mark.parametrize("grains, level", [(39, None), (40, "moderate"), (80, "high"), (200, "very high")])
def test_tree_levels(grains, level):
    assert [g[1] for g in got(payload(birch={13: grains}))] == ([level] if level else [])


def test_only_what_is_still_to_come_counts():
    data = payload(grass={6: 200, 7: 200, 12: 35, 19: 40})
    assert got(data) == [("grass", "moderate", "12:00–20:00")]
    assert got(data, hour=20) == [] and got(data, hour=5) == [("grass", "very high", "06:00–20:00")]


def test_the_worst_comes_first_and_mild_ones_are_left_out():
    data = payload(grass={12: 35}, mugwort={14: 90}, birch={9: 10}, alder={10: 300})
    assert [g[0] for g in got(data)] == ["alder", "mugwort", "grass"]
    assert [g[0] for g in got(data, "high")] == ["alder", "mugwort"] and [g[0] for g in got(data, "very high")] == ["alder"]
    assert got(data, kinds=("grass",)) == [("grass", "moderate", "12:00–13:00")]


def test_missing_values_are_no_pollen():
    assert got({"hourly": {"time": ["2026-06-10T09:00"], "grass_pollen": [None]}}) == []
    assert got({"hourly": {"time": ["2026-06-10T09:00"]}}) == []


def test_drawing():
    assert pollen.render([], NOW) is None
    one = pollen.render([pollen.Pollen("grass", 1, "09:00–20:00")], NOW)
    four = pollen.render([pollen.Pollen(k, 2, "09:00–20:00") for k in ALL], NOW)
    assert one.width == render.WIDTH and one.height <= four.height < 130
    assert four.crop((render.RIGHT + 1, 0, render.WIDTH, four.height)).getextrema()[0] == 255


def test_asks_only_for_what_is_wanted(monkeypatch):
    asked = {}
    monkeypatch.setattr(pollen.http, "get", lambda session, url, params: asked.update(params) or type("R", (), {"json": lambda self: payload(grass={12: 60})})())
    cfg = config.load()
    assert pollen.fetch(cfg, None, NOW)[0].kind == "grass"
    assert asked["hourly"] == "grass_pollen,birch_pollen,alder_pollen,mugwort_pollen" and asked["latitude"] == round(cfg.weather.latitude, 2)
