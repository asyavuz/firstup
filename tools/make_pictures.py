"""Makes the pictures that are kept as files, from the drawings in reporter_web/art.py:
the First Up poster for thermal paper, the home-screen icon and the README's pictures (with
made-up data). Run on a Mac, needs Chrome:

    .venv/bin/python tools/make_pictures.py
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
# What anybody gets: fonts that may be passed on, and nobody's own station.
os.environ.update(REPORTER_OPEN_FONTS="1", REPORTER_LOCAL="/nonexistent")
sys.path.insert(0, str(ROOT))
from reporter import config, render, trains  # noqa: E402
from reporter.sections import events, history, mytrains, news, quote, reminders, tube, weather  # noqa: E402
from reporter_web import art, pages, store  # noqa: E402
from reporter_web.auth import Session  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTH, HEIGHT, PERIOD = 384, 560, 8
# Two layers: greys, which become slanting lines of different thickness as in an engraving
# (slanting, so that no row of dots is much heavier than the next), and the crisp outlines.
TONES = """.s1{fill:#8a8a8a}.s2{fill:#b0b0b0}.s3{fill:#d0d0d0}.s4{fill:#efefef}.rays{fill:#fff;opacity:.5}.sun,.puff,.lamp,.cream,.wheel circle{fill:#fff}.bite,.stars{display:none}
.far{fill:#8c8c8c}.hill{fill:#a6a6a6}.land{fill:#c6c6c6}.stone{fill:#6a6a6a}.arch{fill:#e8e8e8}.rail,.black{fill:#000}.coach{fill:#7a7a7a}.linee{fill:#a8a8a8}.linel{fill:#fff}.lined{fill:#909090}.linedd{fill:#3c3c3c}.puff2{fill:#dcdcdc}.word,.frame{display:none}"""
LINES = """path,circle,rect{fill:#fff;stroke:#000;stroke-width:3.2;stroke-linejoin:round}.s1,.s2,.s3,.s4,.hill{stroke:none}.rays,.bite,.stars,.puff2,.linel,.linedd{display:none}
.rail,.black,.chimney{fill:#000}.lining{stroke:#000;fill:none;stroke-width:2.4}.lamp{stroke-width:2.4}.wheel path{stroke-width:2.2;fill:none}.rod path{stroke-width:5;fill:none}.frame{fill:none}.word{fill:#000;stroke:none}"""
BASE = 'body{margin:0;background:#fff}svg{display:block}text{font-family:"Hammersmith One";text-anchor:middle}'


def shoot(markup: str, width: int, height: int, scale: int = 1) -> Image.Image:
    with tempfile.TemporaryDirectory() as folder:
        page, shot = Path(folder) / "p.html", Path(folder) / "s.png"
        page.write_text(f"<!doctype html><meta charset=utf-8>{markup}")
        command = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                        "--timeout=6000", "--allow-file-access-from-files", f"--user-data-dir={folder}/c", f"--window-size={width},{height}",
                        f"--screenshot={shot}", page.as_uri()]
        for _ in range(3):  # Chrome sometimes hangs after taking the picture
            try:
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            except subprocess.TimeoutExpired:
                pass
            if shot.exists():
                return Image.open(shot).convert("RGB")
        raise RuntimeError("Chrome made no picture")


def layer(style: str) -> Image.Image:
    font = (ROOT / "reporter_web/static/hammersmith-one-latin.woff2").as_uri()
    scene = art.join([art._SKY, art._RAYS, art._SUN, art._CITY, art._HILLS, art._viaduct(440), art._steam(774, 372), art._coach(80, 440), art._engine(424, 440)])
    inside = WIDTH - 40
    return shoot(f"""<style>@font-face{{font-family:"Hammersmith One";src:url({font})}}{BASE}{style}</style><svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
<svg x="20" y="20" width="{inside}" height="392" viewBox="330 0 530 520" preserveAspectRatio="xMidYMax slice">{scene}</svg>
<rect class="frame" x="4" y="4" width="{WIDTH - 8}" height="{HEIGHT - 8}" style="stroke-width:6"/><rect class="frame" x="12" y="12" width="{WIDTH - 24}" height="{HEIGHT - 24}" style="stroke-width:2"/>
<rect class="frame" x="20" y="20" width="{inside}" height="392" style="stroke-width:3"/><text class="word" x="192" y="488" font-size="76" letter-spacing="-1">First Up</text><text class="word" x="192" y="525" font-size="20">The day ahead, by the first train in.</text></svg>""",
                 WIDTH, HEIGHT, 3).convert("L").resize((WIDTH, HEIGHT), Image.LANCZOS)


def poster() -> Image.Image:
    tones, lines = layer(TONES).load(), layer(LINES).load()
    out = Image.new("1", (WIDTH, HEIGHT), 1)
    dots = out.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            ink = 1 - tones[x, y] / 255
            screen = ink > .04 and ((x + y) % PERIOD + .5) / PERIOD < ink
            dots[x, y] = 0 if lines[x, y] < 140 or screen else 1
    return out


def sample_receipt(now: datetime) -> Image.Image:
    sky = [weather.Slot(n, t, i) for n, t, i in (("Morning", 9, "wi-day-sunny.svg.png"), ("Noon", 12, "wi-day-sunny-overcast.svg.png"), ("Afternoon", 11, "wi-rain.svg.png"), ("Evening", 8, "wi-cloudy.svg.png"))]
    today = weather.Weather("07:33", "16:00", 9, 7, "Mostly Clear", "wi-day-sunny.svg.png", 14, 26, "SW", 71, 1018, 1.2, sky, "6 to 12°C. Rain 14:00–17:00", True, None)
    at = lambda h, m: now.replace(hour=h, minute=m)  # noqa: E731
    board = trains.Board("Clapham Junction", [trains.Train(at(8, 34), "London Victoria", "14", "On time"), trains.Train(at(8, 41), "London Victoria", "12", "08:45"), trains.Train(at(8, 49), "London Victoria", "14", "On time")])
    lines = [tube.Line("Piccadilly", "Good Service", ""), tube.Line("District", "Minor Delays", ""), tube.Line("Jubilee", "Good Service", "")]
    from reporter.sections import header
    parts = [header.render(header.fetch(None, None, now), now), weather.render(today, now),
             events.render(events.Inbox(True, [events.Event("09:30", "09:30–10:00", "Dentist"), events.Event("18:30", "18:30", "Dinner with Sam")]), now),
             reminders.render([reminders.Item("Put the bins out", "today"), reminders.Item("Post the parcel", "")], now),
             mytrains.render(mytrains.Mine(board, "VIC", at(8, 20)), now), tube.render(tube.Status(lines, lines[0]), now),
             news.render([news.Headline("Council opens a new park beside the canal", "Example Times"), news.Headline("Scientists count more butterflies than last summer", "Daily Sample")], now),
             history.render(history.Moment(1952, "Agatha Christie’s The Mousetrap opened in London’s West End."), now),
             quote.render(quote.Quote("Well begun is half done.", "Aristotle"), now)]
    return render.to_bitmap(render.stack(parts))


def sample_site(folder: Path, now: datetime, receipt: Image.Image) -> store.Store:
    for name in ("settings", "requests", "out"):
        (folder / name).mkdir(parents=True)
    cfg = config.load(changes=config.NO_CHANGES)
    values = config.as_settings(cfg)
    health = [["Services", "all running"], ["Power", "good"], ["Wi-Fi", "72% signal"], ["Calendar", "list at Wed 07:00"], ["Temperature", "48°C"], ["Storage", "53 GB free"]]
    (folder / "out/status.json").write_text(json.dumps({"at": now.isoformat(), "health": health, "last_print": now.date().isoformat(),
                                                        "defaults": values, "problems": [], "rail_key": True}))
    receipt.save(folder / "out/preview.png")
    return store.Store(folder)


def readme(receipt: Image.Image, now: datetime) -> None:
    css = (ROOT / "reporter_web/style.css").read_text().replace("url(/fonts/", f"url({(ROOT / 'reporter_web/static').as_uri()}/")
    out = ROOT / "docs/images"
    out.mkdir(exist_ok=True)
    pages.sun.sky = lambda *a: "dawn"
    pages.now = lambda: now
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        site = sample_site(folder / "site", now, receipt)
        picture = folder / "r.png"
        receipt.save(picture)

        def page(path: str) -> str:
            text = pages.SHOW[path](site, Session(0))
            start, end = text.index("<link rel=\"stylesheet\""), text.index("</head>")
            text = text[:start] + f"<style>{css}*{{animation:none!important;transition:none!important}}</style>" + text[end:]
            return text.replace('src="/preview.png', f'src="{picture.as_uri()}').replace("<!doctype html>", "")
        for path, name in (("/", "today"), ("/receipt", "receipt-page"), ("/times", "times")):
            shoot(page(path), 1280, 860).save(out / f"{name}.png", optimize=True)
        hero = f"""<style>{css}body{{margin:0}}.poster.hero{{height:760px}}.poster.hero>h1,.poster.hero>.sub,.poster.hero>.strip{{position:absolute}}.train,.train *{{animation:none!important}}.poster.hero h1{{font-size:150px;top:58px;left:84px}}.hero .sub{{top:336px;left:90px;font-size:30px;max-width:22ch}}
.strip{{position:absolute;right:90px;top:54px;width:372px;height:760px;overflow:hidden;background:#fdfcfa;padding:26px 20px;box-shadow:0 24px 50px rgba(10,25,40,.5)}}.strip img{{width:330px;display:block}}</style>
<body class="sky-dawn line-none"><div class="poster hero">{art.today()}<h1>First<br>Up</h1><p class="sub">A morning receipt, printed by a Raspberry Pi.</p><div class="strip"><img src="{picture.as_uri()}"></div></div>"""
        shoot(hero, 1600, 760).save(out / "hero.png", optimize=True)
        grid = "".join(f'<img src="{(out / f"{n}.png").as_uri()}" style="width:780px;display:block">' for n in ("receipt-page", "times"))
        shoot(f'<body style="margin:0;display:flex;gap:40px;background:#fff">{grid}', 1600, 524).save(out / "pages.png", optimize=True)
        for name in ("receipt-page", "times"):
            (out / f"{name}.png").unlink()


if __name__ == "__main__":
    picture = poster()
    picture.save(ROOT / "assets/gfx/first-up.png", optimize=True)
    dark = sum(1 for v in picture.convert("L").tobytes() if v == 0) / (picture.width * picture.height)
    print(f"first-up.png {picture.size}, {dark:.0%} black")
    icon = shoot(f"<style>body{{margin:0}}svg{{width:180px;height:180px;display:block}}</style>{art.app_icon()}", 180, 180)
    icon.save(ROOT / "reporter_web/static/apple-touch-icon.png", optimize=True)
    morning = datetime(2026, 11, 25, 8, 0, tzinfo=config.load().tz)
    readme(sample_receipt(morning), morning)
