from datetime import datetime

from reporter import config, health, render

NOW = datetime(2026, 11, 24, 12, 0)


def test_page_prints_even_if_every_check_fails(monkeypatch):
    def broken(cfg, now):
        raise RuntimeError("x" * 500)
    monkeypatch.setattr(health, "CHECKS", tuple((label, broken) for label, _ in health.CHECKS))
    assert {text for _, text in health.collect(config.load(), NOW)} == {"cannot tell (RuntimeError)"}
    assert health.page(config.load(), NOW).width == render.WIDTH


def test_long_values_stay_on_the_paper(monkeypatch):
    monkeypatch.setattr(health, "CHECKS", (("Services", lambda c, n: "1 failed: " + "y" * 900),))
    img = health.page(config.load(), NOW)
    assert img.crop((render.RIGHT + 1, 0, render.WIDTH, img.height)).convert("L").getextrema()[0] == 255
