"""The web interface, as a real HTTPS server in its own process."""

import asyncio
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.client import HTTPSConnection
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from reporter import config, jobs, settings
from reporter_web import art, auth, markup, pages, server, store, sun

PASSWORD = "correct horse battery"
HOST = "printer.example.com:8444"
ORIGIN = f"https://{HOST}"
DEFAULTS = config.as_settings(config.load())


def status(**changes):
    return {"at": datetime.now(timezone.utc).isoformat(), "health": [["Power", "good"], ["Odd", "<b>&"]], "defaults": DEFAULTS,
            "last_print": "", "problems": [], "rail_key": False, **changes}


def make_base(root):
    for name in ("settings", "requests", "out", "phone"):
        (root / name).mkdir(parents=True)
    (root / "out/status.json").write_text(json.dumps(status()))
    return root


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """Both programs: the one with the key and, behind it, the one with the pages."""
    root = tmp_path_factory.mktemp("web")
    cred, base, short = root / "cred", make_base(root / "base"), tempfile.mkdtemp(dir="/tmp")  # local socket names must be short
    cred.mkdir()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=localhost",
                    "-keyout", str(cred / "key.pem"), "-out", str(cred / "cert.pem")], check=True, capture_output=True)
    (cred / "password").write_text(auth.hash_password(PASSWORD) + "\n")
    env = {"PATH": os.environ["PATH"], "CREDENTIALS_DIRECTORY": str(cred), "REPORTER_WEB": str(base), "WEB_HOST": HOST,
           "WEB_SOCKET": f"{short}/app.sock"}
    code = f"import sys; sys.path.insert(0, {str(config.ROOT)!r}); from reporter_web import server, store; store.A_MINUTE = dict.fromkeys(store.SCREEN + store.KEYS, 999); server.HOLD = 3; server.main()"
    log = open(root / "log", "w")
    app = subprocess.Popen([sys.executable, "-I", "-c", code], env=env, stdout=subprocess.PIPE, stderr=log, text=True)
    assert app.stdout.readline() == "ready\n"
    tls = subprocess.Popen([sys.executable, "-I", str(config.ROOT / "deploy/reporter_web_tls.py")], env=env,
                           stdout=subprocess.PIPE, stderr=log, text=True)
    port = int(tls.stdout.readline())
    yield SimpleNamespace(port=port, base=base, proc=app, tls=tls, log=root / "log", socket=env["WEB_SOCKET"])
    app.kill(), tls.kill()
    shutil.rmtree(short)


def call(site, method="GET", path="/", form=None, cookie=None, headers=None, body=None):
    conn = HTTPSConnection("127.0.0.1", site.port, timeout=15, context=ssl._create_unverified_context())
    head = {"Host": HOST}
    if method == "POST":
        head.update({"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"})
    if cookie:
        head["Cookie"] = cookie
    head.update(headers or {})
    head = {k: v for k, v in head.items() if v is not None}
    conn.request(method, path, body=body if body is not None else urlencode(form or {}, doseq=True) if method == "POST" else None, headers=head)
    reply = conn.getresponse()
    return SimpleNamespace(status=reply.status, text=reply.read().decode("utf-8", "replace"), headers=reply.headers)


def sign_in(site, password=PASSWORD):
    reply = call(site, "POST", "/login", {"password": password})
    return reply, (reply.headers.get("Set-Cookie") or "").split(";")[0]


@pytest.fixture
def user(site):
    """A signed-in browser: `user(method, path, form)` adds the cookie and the page's token."""
    reply, cookie = sign_in(site)
    assert reply.status == 303, reply.text
    token = re.search(r'name="csrf" value="([^"]+)"', call(site, path="/button", cookie=cookie).text)[1]

    def browse(method="GET", path="/", form=None, **kwargs):
        if method == "POST":
            form = {"csrf": token, **(form or {})}
        return call(site, method, path, form, cookie=cookie, **kwargs)
    browse.cookie, browse.token = cookie, token
    saved = site.base / "settings/settings.json"
    saved.unlink(missing_ok=True)
    for path in (site.base / "requests").iterdir():
        path.unlink()
    (site.base / "out/status.json").write_text(json.dumps(status()))
    yield browse
    saved.unlink(missing_ok=True)


def refused(user, path, form):
    """What the page says afterwards: it goes back there, to the sheet, with what was typed."""
    reply = user("POST", path, form)
    assert reply.status == 303 and "#" in reply.headers["Location"], reply.text
    return user(path=reply.headers["Location"].partition("#")[0]).text


def saved(site):
    return json.loads((site.base / "settings/settings.json").read_text())


# --- getting in ---

@pytest.mark.parametrize("path", list(pages.SHOW) + ["/preview.png", "/trains.png"])
def test_nothing_without_signing_in(site, path):
    (site.base / "out/preview.png").write_bytes(b"private")
    for cookie in (None, "__Host-session=", "__Host-session=guess", "__Host-session=\xe9", "x=1; ;;="):
        reply = call(site, path=path, cookie=cookie)
        back = f"?back={path}" if path in pages.SHOW and path != "/" else ""
        assert (reply.status, reply.headers["Location"], reply.text) == (303, f"/login{back}", "")


@pytest.mark.parametrize("path", list(pages.CHANGE) + ["/do", "/logout"])
def test_nothing_can_be_changed_without_signing_in(site, path):
    before = sorted((site.base / "requests").iterdir())
    reply = call(site, "POST", path, {"kind": "receipt", "back": "/", "heat_time": "65", "csrf": ""})
    assert (reply.status, reply.headers["Location"]) == (303, "/login" if path == "/logout" else f"/login?lost={path if path in pages.SHOW else '/'}")
    assert sorted((site.base / "requests").iterdir()) == before and not (site.base / "settings/settings.json").exists()


def test_the_sign_in_page_says_what_to_do_if_the_password_is_forgotten(site):
    assert "setup-web.sh --new-password" in call(site, path="/login").text
    assert "setup-web.sh --new-password" in call(site, "POST", "/login", {"password": "wrong"}).text


def test_cookie_is_locked_down(site):
    reply, _ = sign_in(site)
    parts = [p.strip() for p in reply.headers["Set-Cookie"].split(";")]
    assert parts[0].startswith("__Host-session=") and len(parts[0]) > 50
    assert set(parts[1:]) == {"Path=/", "Secure", "HttpOnly", "SameSite=Strict"}


def test_wrong_passwords_all_look_the_same(site):
    replies = [call(site, "POST", "/login", {"password": p}) for p in ("", "wrong", "x" * 5000)]
    assert len({(r.status, r.text) for r in replies}) == 1 and replies[0].status == 403
    assert all("Set-Cookie" not in r.headers for r in replies)
    assert sign_in(site)[0].status == 303  # and a right one still works


def test_signing_out_ends_the_session(site):
    _, cookie = sign_in(site)
    token = re.search(r'name="csrf" value="([^"]+)"', call(site, path="/", cookie=cookie).text)[1]
    assert call(site, path="/times", cookie=cookie).status == 200
    call(site, "POST", "/logout", {"csrf": token}, cookie=cookie)
    assert call(site, path="/times", cookie=cookie).status == 303


# --- requests from elsewhere ---

@pytest.mark.parametrize("host", ["evil.example", "printer.example.com", "printer.example.com:8443", "192.168.1.50:8444", "localhost", "",
                                  HOST + ".evil.example", "PRINTER.example.com:8444"])
def test_only_its_own_name(site, host):
    assert call(site, headers={"Host": host}).status in (400, 421)
    assert call(site, path="/login", headers={"Host": host}).status in (400, 421)


@pytest.mark.parametrize("headers", [
    {"Origin": None}, {"Origin": "null"}, {"Origin": "https://evil.example"}, {"Origin": "https://printer.example.com"},
    {"Origin": "https://printer.example.com:8443"}, {"Origin": "http://" + HOST}, {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "none"},
])
def test_other_sites_cannot_send_forms(site, user, headers):
    assert user("POST", "/printer", {"heat_time": "65"}, headers=headers).status in (400, 403)
    assert call(site, "POST", "/login", {"password": PASSWORD}, headers=headers).status in (400, 403)
    assert not (site.base / "settings/settings.json").exists()


@pytest.mark.parametrize("token", ["", "wrong", "é", None])
def test_forms_need_their_token(site, user, token):
    form = {"heat_time": "65"}
    if token is not None:
        form["csrf"] = token
    reply = call(site, "POST", "/printer", {**form, "group": "printer"}, cookie=user.cookie)
    assert (reply.status, reply.headers["Location"]) == (303, "/printer") and not (site.base / "settings/settings.json").exists()


def test_another_sessions_token_does_not_work(site, user):
    _, other = sign_in(site)
    call(site, "POST", "/printer", {"group": "printer", "heat_time": "65", "csrf": user.token}, cookie=other)
    assert "before you signed in" in call(site, path="/printer", cookie=other).text and not (site.base / "settings/settings.json").exists()
    assert call(site, "POST", "/do", {"kind": "receipt", "back": "/", "csrf": "old"}, cookie=other).headers["Location"] == "/"
    assert list((site.base / "requests").iterdir()) == []


@pytest.mark.parametrize("method, path, status_code", [
    ("GET", "/nothing", 404), ("GET", "/../settings/settings.json", 404), ("GET", "/out/status.json", 404), ("GET", "//etc/passwd", 404),
    ("GET", "/status.json", 404), ("GET", "/%2e%2e/out", 404), ("GET", "https://evil.example/", 404), ("POST", "/", 404),
    ("POST", "/preview.png", 404), ("PUT", "/printer", 405), ("DELETE", "/", 405), ("OPTIONS", "/", 405), ("TRACE", "/", 405),
    ("GET", "/do", 404), ("GET", "/logout", 404), ("GET", "/favicon.ico", 404),
])
def test_everything_else_is_refused(site, user, method, path, status_code):
    assert user(method, path).status == status_code


@pytest.mark.parametrize("body, headers", [
    (b"x" * 40000, {}), (b"a=%ff", {}), (b"\xff", {}), (b"a&" * 400, {}), (b"a=1", {"Content-Type": "application/json"}),
    (b"a=1", {"Content-Type": "multipart/form-data; boundary=x"}),
])
def test_odd_bodies(site, user, body, headers):
    assert call(site, "POST", "/printer", cookie=user.cookie, body=body, headers=headers).status in (400, 403, 413, 415)
    assert user(path="/printer").status == 200


@pytest.mark.parametrize("length", [b"-1", b"\xb2", b"1e3", b"0x10", b"", b"5, 5", b"5\r\nContent-Length: 6", b"9" * 400])
def test_lengths_that_make_no_sense(site, user, length):
    context = ssl._create_unverified_context()
    with socket.create_connection(("127.0.0.1", site.port), timeout=15) as raw, context.wrap_socket(raw) as conn:
        conn.sendall(b"POST /printer HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\nOrigin: " + ORIGIN.encode() +
                     b"\r\nContent-Type: application/x-www-form-urlencoded\r\nCookie: " + user.cookie.encode() +
                     b"\r\nContent-Length: " + length + b"\r\n\r\ncsrf=" + user.token.encode() + b"&heat_time=65")
        try:
            assert conn.recv(100).split(b" ")[1:2] in ([b"400"], [b"413"], [b"403"], [])
        except OSError:
            pass  # simply dropped
    assert user(path="/printer").status == 200 and not (site.base / "settings/settings.json").exists()


def test_every_reply_carries_the_protective_headers(site, user):
    style = call(site, path="/style.css?x")
    for reply in (user(), call(site, path="/login"), style, call(site, path="/none"), call(site), user(path="/content")):
        csp = reply.headers["Content-Security-Policy"]
        assert csp.startswith("default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; manifest-src 'self'; form-action 'self'") and "frame-ancestors 'none'" in csp
        assert "script" not in csp and "unsafe" not in csp
        assert reply.headers["Cache-Control"] == ("no-store" if reply is not style else "public, max-age=604800") and reply.headers["X-Content-Type-Options"] == "nosniff"
        assert reply.headers["Referrer-Policy"] == "same-origin" and "Server" not in reply.headers
        assert "Python" not in str(reply.headers)


# --- the pages ---

@pytest.mark.parametrize("path", list(pages.SHOW))
def test_pages_work_without_scripts_or_outside_help(user, path):
    reply = user(path=path)
    assert reply.status == 200 and 'lang="en"' in reply.text and "<h1>" in reply.text
    assert "<script" not in reply.text and " style=" not in reply.text and " on" + "click" not in reply.text
    assert not re.search(r'(src|href|action)="(?!/|#)', reply.text)
    for value in ("<b>&", "{", "}"):
        assert value not in reply.text
    assert reply.text.count("<form") == reply.text.count('name="csrf"') == reply.text.count("</form>")


def test_labels_belong_to_something(user):
    for path in pages.SHOW:
        text = user(path=path).text
        ids = set(re.findall(r' id="([^"]+)"', text))
        assert set(re.findall(r' for="([^"]+)"', text)) <= ids
        assert set(re.findall(r' list="([^"]+)"', text)) <= ids


def test_what_is_typed_never_becomes_markup(site, user):
    nasty = '"><script>alert(1)</script>'
    text = refused(user, "/content", {"group": "news", "count": "5", "name-0": nasty, "url-0": nasty})
    assert "<script" not in text and html.escape(nasty) in text
    assert "<script" not in refused(user, "/content", {"group": "weather", "place": nasty, "uv_from": nasty})
    assert user("POST", "/content", {"group": "news", "count": "5", "name-0": "<i>{x}</i>", "url-0": "https://a.example/x"}).status == 303
    text = user(path="/content").text
    assert "&lt;i&gt;{x}&lt;/i&gt;" in text and "<i>" not in text


def test_what_the_reporter_says_never_becomes_markup(site, user):
    (site.base / "out/status.json").write_text(json.dumps(status(problems=["<u>bad</u>"], health=[["<u>", "<u>"], "x", [1, 2, 3]], last_print="<u>")))
    (site.base / "out/result-receipt.json").write_text(json.dumps({"state": "failed", "text": "<u>oops</u>", "at": datetime.now(timezone.utc).isoformat()}))
    reply = user()
    assert reply.status == 200 and "<u>" not in reply.text and "&lt;u&gt;" in reply.text
    (site.base / "out/result-receipt.json").unlink()


@pytest.mark.parametrize("content", [b"", b"[]", b"{", b'{"defaults": 5, "health": 5, "problems": 5, "at": 5, "last_print": 5}',
                                     b'{"defaults": {"sections": ["x"]}}', b"\xff" * 20, b'{"health": {"a": 1}, "problems": "x", "at": "x", "rail_key": []}'])
def test_a_damaged_status_is_survived(site, user, content):
    (site.base / "out/status.json").write_bytes(content)
    for path in pages.SHOW:
        reply = user(path=path)
        assert reply.status == 200 and ("Waiting for the printer program" in reply.text) == (path not in pages.STILL)
    assert (site.base / "requests/status").exists()
    assert user("POST", "/printer", {"group": "printer", "heat_time": "65"}).status == 303  # nothing saved, nothing broken
    assert not (site.base / "settings/settings.json").exists()


def test_nothing_is_asked_for_again_and_again(tmp_path):
    """systemd gives up on reporter-requests.path after 20 in a minute."""
    asked, shop = 0, store.Store(make_base(tmp_path / "base"))
    for _ in range(50):
        for kind in store.SCREEN:
            asked += shop.ask(kind)
            (shop.requests / kind).unlink(missing_ok=True)  # as if answered at once
    assert asked == sum(store.A_MINUTE[kind] for kind in store.SCREEN)
    burst = int(re.search(r"TriggerLimitBurst=(\d+)", (config.ROOT / "deploy/reporter-requests.path").read_text())[1])
    assert sum(store.A_MINUTE.values()) + 60 // store.PAUSE * len(store.PAPER) < burst


def test_a_value_the_pages_do_not_offer_is_named_and_the_password_can_still_be_changed(site, user):
    (site.base / "out/status.json").write_text(json.dumps(status(defaults={**DEFAULTS, "printer": {"heat_time": 90}}, problems=["config.local.toml, printer: the heat"])))
    reply = user(path="/times")
    assert "Settings to put right" in reply.text and "the heat" in reply.text and "http-equiv" not in reply.text
    assert 'name="current"' in user(path="/password").text


# --- changing things ---

def test_sections_are_chosen_and_moved(site, user):
    form = {"group": "sections", "order": list(settings.SECTIONS), "on": ["header", "news", "weather"]}
    assert user("POST", "/receipt", form).status == 303
    assert saved(site)["sections"] == ["header", "weather", "news"]
    user("POST", "/receipt", {**form, "order": ["header", "weather", "news"], "move": "up:news"})
    assert saved(site)["sections"] == ["header", "news", "weather"]
    user("POST", "/receipt", {**form, "order": ["header", "news", "weather"], "move": "down:weather"})
    user("POST", "/receipt", {**form, "order": ["header", "news", "weather", "../x"], "move": "up:header"})
    assert saved(site)["sections"] == ["header", "news", "weather"]
    assert user("POST", "/receipt", {**form, "order": ["header", "news", "weather"], "move": "down:header"}).headers["Location"] == "/receipt#down-header"
    assert user("POST", "/receipt", {**form, "order": ["news", "header", "weather"], "move": "up:header"}).headers["Location"] == "/receipt#on-header"  # at the top: no arrow up
    assert user("POST", "/receipt", {**form, "move": "x:<b>"}).headers["Location"] == "/receipt" and 'id="down-header"' in user(path="/receipt").text
    assert "keep at least one block" in refused(user, "/receipt", {"group": "sections", "order": list(settings.SECTIONS)})


def test_a_block_switched_on_again_comes_back_where_it_was():
    original = DEFAULTS["sections"]
    without = [name for name in original if name not in ("weekend", "header")]
    places = pages._places(without, original + [name for name in settings.SECTIONS if name not in original])
    assert [name for name in places if name in original] == original and sorted(places) == sorted(settings.SECTIONS)


def test_refused_choices_are_shown_again(site, user):
    text = refused(user, "/receipt", {"group": "sections", "order": ["quote", "header"], "on": []})
    assert "checked" not in text.split('class="sections"')[1].split("</ol>")[0]
    form = times_form(Tue=(7, 0, 120), Mon=(23, 55, 30))
    text = refused(user, "/times", form)
    assert re.search(r'name="hour-Tue".*?value="7" selected', text, re.S) and "on Mon, choose a time" in text
    assert 'value="7" selected' not in re.search(r'name="hour-Tue".*?</select>', user(path="/times").text, re.S)[0]  # shown once
    text = refused(user, "/button", {"group": "button", "taps-sudoku": "4", "hold-wifi": "9"})
    assert re.search(r'name="taps-sudoku".*?value="4" selected', text, re.S)

def times_form(**days):
    form = {"group": "schedule"}
    for day in settings.DAYS:
        hour, minute, keep = days.get(day, (8, 0, 120))
        form.update({f"hour-{day}": hour, f"minute-{day}": minute, f"keep-{day}": keep})
        if days.get(day, True):
            form[f"on-{day}"] = "1"
    return form


def test_times(site, user):
    form = times_form(Sat=(9, 30, 60), Sun=(9, 30, 60))
    del form["on-Wed"]
    assert user("POST", "/times", form).status == 303
    assert saved(site)["schedule"] == [{"days": ["Mon", "Tue", "Thu", "Fri"], "time": "08:00", "catch_up_until": "10:00"},
                                       {"days": ["Sat", "Sun"], "time": "09:30", "catch_up_until": "10:30"}]
    text = user(path="/times").text
    assert re.search(r'name="on-Wed" value="1">', text) and re.search(r'name="on-Mon" value="1" checked>', text)
    user("POST", "/times", times_form(Mon=(23, 30, 30)))
    assert saved(site)["schedule"][0] == {"days": ["Mon"], "time": "23:30", "catch_up_until": "23:55"}
    assert "on Mon it cannot keep trying past 23:55" in refused(user, "/times", times_form(Mon=(23, 30, 240)))
    assert "before 23:55" in refused(user, "/times", times_form(Mon=(23, 55, 30)))
    assert "multiples of 5" in refused(user, "/times", times_form(Mon=(8, 1, 30)))
    user("POST", "/times", {"group": "schedule"})
    assert saved(site)["schedule"] == []
    assert user(path="/times").status == 200


def test_several_days_at_once(site, user):
    user("POST", "/times", {**times_form(), "all": ["Mon", "Tue"], "all-hour": "6", "all-minute": "40"})
    assert saved(site)["schedule"][0] == {"days": ["Mon", "Tue"], "time": "06:40", "catch_up_until": "08:40"}


def test_a_move_says_so(site, user):
    user("POST", "/receipt", {"group": "sections", "order": ["header", "news"], "on": ["header", "news"], "move": "up:news"})
    text = user(path="/receipt").text
    assert "<title>Saved, now number 1: Receipt" in text and 'class="moved"' in text


def test_a_refused_feed_is_marked(site, user):
    text = refused(user, "/content", {"group": "news", "count": "3", "name-0": "A", "url-0": "https://a.example/x", "name-1": "B", "url-1": "www.b.example"})
    assert text.count('aria-invalid="true"') == 2 and "Not saved: feed 2: " in text


def test_content(site, user):
    def send(group, **form):
        return user("POST", "/content", {"group": group, **form})

    def wrong(group, **form):
        return refused(user, "/content", {"group": group, **form})
    assert send("weather", place="Clapham Junction (CLJ)", uv_from="5").headers["Location"] == "/content#weather"
    assert saved(site)["weather"] == {"place": "Clapham Junction", "latitude": 51.4641, "longitude": -0.1703, "uv_from": 5}
    send("weather", place="Clapham Junction", uv_from="6")
    assert saved(site)["weather"]["uv_from"] == 6 and saved(site)["weather"]["latitude"] == 51.4641
    send("weather", place="53.8, -1.55", uv_from="3")
    assert saved(site)["weather"]["latitude"] == 53.8
    assert "Not saved" in wrong("weather", place="99.9, 0", uv_from="3") and 'value="Atlantis"' in wrong("weather", place="Atlantis", uv_from="3")
    send("weather", place="london", uv_from="3")  # the original can always be typed again
    assert "weather" not in saved(site)
    send("tube", favourite="Northern", modes=["dlr", "tube"])
    assert saved(site)["tube"] == {"favourite": "Northern", "modes": ["tube", "dlr"]}
    assert 'class="line-northern sky-' in user(path="/content").text
    assert "at least one kind of line" in wrong("tube", favourite="Northern")
    send("news", **{"count": "3", "name-2": "X", "url-2": "https://x.example/rss"})
    assert saved(site)["news"] == {"count": 3, "feeds": [{"name": "X", "url": "https://x.example/rss"}]}
    text = wrong("news", **{"count": "3", "name-0": "Home", "url-0": "https://192.168.1.1/rss"})
    assert "must be a name" in text and "https://192.168.1.1/rss" in text
    more = {"offset": "30", "trains": "4", "days": ["Sat", "Mon"]}
    send("trains", station="clapham junction", towards="Guildford (GLD)", **more)
    assert saved(site)["trains"] == {"station": "CLJ", "towards": "GLD", "offset": 30, "count": 4, "days": ["Mon", "Sat"]}
    assert "Choose a station" in wrong("trains", station="nowhere", towards="", **more).replace("choose a", "Choose a")
    send("warnings", region="wl")
    send("pollen", level="high", kinds=["birch", "grass"])
    assert saved(site)["warnings"] == {"region": "wl"} and saved(site)["pollen"] == {"level": "high", "kinds": ["grass", "birch"]}
    assert "at least one kind of pollen" in wrong("pollen", level="high")


def test_one_save_saves_the_whole_page_and_names_what_it_could_not(site, user):
    form = {"group": ["weather", "sudoku", "news"], "place": "London", "uv_from": "6", "sudoku": "hard", "count": "3", "name-0": "", "url-0": "https://a.example/x", "save": "sudoku"}
    reply = user("POST", "/content", form)
    assert reply.headers["Location"] == "/content#news"
    assert saved(site)["weather"]["uv_from"] == 6 and saved(site)["sudoku"] == {"level": "hard"} and "news" not in saved(site)
    text = user(path="/content").text
    news = text.split('id="news"')[1].split("</section>")[0]
    assert "Not saved: feed 1: a feed" in news and "https://a.example/x" in news and text.count("Not saved:") == 2  # there and in the title
    assert "Saved all the same: Weather, Sudoku" in news
    assert user("POST", "/content", {**form, "name-0": "A"}).headers["Location"] == "/content#sudoku"
    assert re.search("<title>Saved[^<]*: Content", user(path="/content").text)


def fields(text, *groups):
    return {name: html.unescape(value) for name, value in re.findall(r'name="(was-\w+)" value="([^"]*)"', text) if name[4:] in groups}


def test_two_tabs_do_not_undo_each_other(site, user):
    first = fields(user(path="/content").text, "sudoku", "news")
    user("POST", "/content", {"group": "sudoku", "sudoku": "hard", **fields(user(path="/content").text, "sudoku")})
    user("POST", "/content", {"group": ["sudoku", "news"], "sudoku": "medium", "count": "2", "name-0": "A", "url-0": "https://a.example/x", **first})
    assert saved(site)["sudoku"] == {"level": "hard"} and saved(site)["news"]["count"] == 2


def test_a_saved_group_that_can_no_longer_be_used_can_be_put_right(site, user):
    (site.base / "settings/settings.json").write_text('{"printer": {"heat_time": 95}}')
    text = user(path="/printer").text
    assert 'name="reset" value="printer"' in text
    user("POST", "/printer", {"group": "printer", "heat_time": "70", **fields(text, "printer")})
    assert saved(site) == {}


def test_pages_older_than_the_reporter_say_so(site, user):
    newer = {**DEFAULTS, "sudoku": {"level": "fiendish"}}
    (site.base / "out/status.json").write_text(json.dumps(status(defaults=newer)))
    text = user(path="/times").text
    assert "./deploy.sh --web" in text and "http-equiv" not in text


def test_a_draft_waits_for_its_page(site, user):
    user("POST", "/content", {"group": "weather", "place": "Atlantis", "uv_from": "3"})
    user(path="/"), user(path="/times")
    assert 'value="Atlantis"' in user(path="/content").text and 'value="Atlantis"' not in user(path="/content").text


def test_only_the_groups_of_that_page_are_saved(site, user):
    user("POST", "/printer", {"group": ["button", "printer", "nonsense", "sections"], "heat_time": "65", "on": ["header"]})
    assert list(saved(site)) == ["printer"]


def test_saving_and_looking(site, user):
    assert user("POST", "/receipt", {"group": "sections", "order": ["header"], "on": ["header"], "preview": "sections"}).headers["Location"] == "/receipt#preview"
    assert (site.base / "requests/preview").exists() and saved(site)["sections"] == ["header"]
    text = user(path="/receipt").text
    assert "appears here by itself" in text and re.search(r'src="/preview.png\?wait\d+"', text) and "http-equiv" not in text


def test_a_picture_waits_for_the_new_one(site, user):
    (site.base / "out/preview.png").write_bytes(b"old")
    (site.base / "requests/preview").touch()

    def finish():
        (site.base / "out/preview.png").write_bytes(b"new")
        (site.base / "requests/preview").unlink()
    threading.Timer(1, finish).start()
    started = time.monotonic()
    assert user(path="/preview.png?wait1").text == "new" and 0.5 < time.monotonic() - started < 5
    assert user(path="/preview.png?1").text == "new"


def test_a_browser_that_has_gone_is_not_waited_for(site, user):
    (site.base / "requests/preview").touch()
    for _ in range(6):  # as many as one device may have
        conn = HTTPSConnection("127.0.0.1", site.port, timeout=5, context=ssl._create_unverified_context())
        conn.request("GET", "/preview.png?wait", headers={"Host": HOST, "Cookie": user.cookie})
        conn.sock.close()
    time.sleep(1.2)
    started = time.monotonic()
    assert call(site, path="/login").status == 200 and time.monotonic() - started < 1
    (site.base / "requests/preview").unlink()


def test_a_train_token_nobody_takes_does_not_lie_about(site, user):
    user("POST", "/keys", {"what": "rail", "token": "a-train-token-0123456789"})
    assert not (site.base / "requests/rail").exists() and "not answering" in user(path="/password").text


def test_many_new_phone_tokens_at_once_leave_the_last_one_shown_in_force(tmp_path):
    shop, shown = store.Store(make_base(tmp_path / "base")), []

    def make():
        with shop.phone_lock:
            shown.append(shop.new_phone_token())
    threads = [threading.Thread(target=make) for _ in range(12)]
    [t.start() for t in threads], [t.join() for t in threads]
    assert shop.phone.read_text().strip() == hashlib.sha256(shown[-1].encode()).hexdigest()


def test_the_paper_follows_the_switches_and_the_order(site, user):
    (site.base / "out/blocks.json").write_text(json.dumps({"height": 90, "places": {"weather": [0, 40], "header": [40, 20], "sudoku": [60, 30], "<x>": [0, 1], "news": ["a", 1]}}))
    (site.base / "out/preview.png").write_bytes(b"x")
    paper = user(path="/receipt").text.split('class="paper"')[1]
    assert paper.index("strip-header") < paper.index("strip-weather") < paper.index("strip-sudoku") and 'viewBox="0 40 384 20"' in paper and "strip-news" not in paper
    assert "body:has(#on-sudoku:not(:checked)) .strip-sudoku" in call(site, path="/style.css").text
    (site.base / "out/blocks.json").write_text('{"height": -1, "places": 5}')
    assert "strip-" not in user(path="/receipt").text.split('class="paper"')[1]


def test_content_draws_anew_after_every_save(site, user):
    user("POST", "/content", {"group": "sudoku", "sudoku": "hard"})
    assert (site.base / "requests/preview").exists()


def test_button_and_printer(site, user):
    assert user("POST", "/button", {"group": "button", "taps-receipt": "1", "taps-sudoku": "4", "hold-sudoku": "3", "hold-wifi": "0", "taps-health": ""}).status == 303
    assert saved(site)["button"] == {"taps": {"receipt": 1, "sudoku": 4}, "holds": {"sudoku": 3}}
    for bad in ({"taps-receipt": "10"}, {"hold-wifi": "5"}, {"taps-wifi": "x"}, {"taps-wifi": "-1"}):
        assert "Not saved" in refused(user, "/button", {"group": "button", **bad})
    user("POST", "/button", {"group": "button", "taps-shutdown": "1"})
    assert saved(site)["button"] == {"taps": {}, "holds": {}}
    user("POST", "/printer", {"group": "printer", "heat_time": "65"})
    assert saved(site)["printer"] == {"heat_time": 65}
    for heat in ("90", "0", "-70", "7e1", "", "70; rm"):
        assert "Not saved" in refused(user, "/printer", {"group": "printer", "heat_time": heat})
    assert saved(site)["printer"] == {"heat_time": 65}


def test_going_back_to_the_original(site, user):
    user("POST", "/printer", {"group": "printer", "heat_time": "65"})
    assert 'name="reset"' in user(path="/printer").text
    user("POST", "/printer", {"group": "printer", "heat_time": "80", "reset": "printer"})
    assert "Back to the original" in user(path="/printer").text
    assert saved(site) == {} and 'name="reset"' not in user(path="/printer").text
    user("POST", "/printer", {"group": "printer", "heat_time": str(DEFAULTS["printer"]["heat_time"])})
    assert saved(site) == {}  # the same as config.toml is not kept


def test_every_form_saves_what_the_page_shows(site, user):
    """Pressing Save without touching anything changes nothing."""
    seen = []
    for path in pages.SHOW:
        text = user(path=path).text
        for action, fields in re.findall(r'<form class="sheets" id="settings" method="post" action="(/\w+)">(.*?)</form>', text, re.S):
            form = {}
            for tag in re.findall(r"<input[^>]*>", fields):
                name = re.search(r'name="([^"]+)"', tag)
                if name and (not re.search(r'type="(checkbox|radio)"', tag) or " checked" in tag):
                    form.setdefault(name[1], []).append(html.unescape(re.search(r'value="([^"]*)"', tag)[1]))
            for name, choices in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', fields, re.S):
                form[name] = [html.unescape(re.search(r'value="([^"]*)" selected', choices)[1])]
            form.pop("csrf")
            assert user("POST", action, form).status == 303, action
            assert not (site.base / "settings/settings.json").exists(), action
            assert "Not saved:" not in user(path=action).text
            seen.append(action)
    assert seen == ["/receipt", "/times", "/content", "/button", "/printer"]


def test_everything_the_pages_save_is_accepted_by_the_printer(site, user):
    user("POST", "/content", {"group": "tube", "favourite": "DLR", "modes": ["dlr"]})
    user("POST", "/times", times_form(Mon=(7, 5, 30)))
    cfg = config.load(changes=site.base / "settings/settings.json")
    assert cfg.problems == () and cfg.tube.favourite == "DLR" and cfg.schedule[0].time.isoformat() == "07:05:00"


@pytest.mark.parametrize("last, moment, due", [
    ("", "2026-11-24T07:00", "2026-11-24 08:00"), ("", "2026-11-24T09:15", "2026-11-24 09:15"), ("", "2026-11-24T10:01", "2026-11-25 08:00"),
    ("2026-11-24", "2026-11-24T08:30", "2026-11-25 08:00"), ("2026-11-27", "2026-11-27T12:00", "2026-11-28 10:00"),
])
def test_when_the_next_receipt_is_due(last, moment, due):
    got = pages.next_due(DEFAULTS["schedule"], last, datetime.fromisoformat(moment).astimezone())
    assert f"{got:%Y-%m-%d %H:%M}" == due
    assert pages.next_due([], last, got) is None
    monday = [{"days": ["Mon"], "time": "08:00", "catch_up_until": "09:00"}]
    assert pages.next_due(monday, "2026-11-23", datetime(2026, 11, 23, 8, 30).astimezone()).day == 30


def test_today_and_the_clock_are_right_as_soon_as_something_is_saved(site, user):
    user("POST", "/times", {"group": "schedule"})
    assert "Nothing is due" in user().text and "Next up" not in user().text
    assert "without hands" in user(path="/times").text


# --- asking for things ---

def test_the_web_and_the_reporter_agree_on_what_can_be_asked():
    assert set(store.PAPER + store.SCREEN + store.KEYS) == set(jobs.KINDS)


def test_asking(site, user):
    reply = user("POST", "/do", {"kind": "preview", "back": "/receipt"})
    assert reply.headers["Location"] == "/receipt#preview"
    request = site.base / "requests/preview"
    assert request.read_bytes() == b""
    assert 'http-equiv="refresh"' in user(path="/").text
    for path in pages.SHOW:  # never where something could be typed
        assert path == "/" or 'http-equiv="refresh"' not in user(path=path).text
    request.unlink()


@pytest.mark.parametrize("form", [{"kind": "shutdown"}, {"kind": "../x"}, {"kind": ""}, {"kind": "wifi"}, {"kind": "preview", "back": "https://evil.example"},
                                  {"kind": "preview", "back": "//evil.example"}])
def test_only_listed_things_can_be_asked_for(site, user, form):
    assert user("POST", "/do", {"back": "/", **form}).status == 400
    assert list((site.base / "requests").iterdir()) == []


def test_paper_is_not_wasted_by_pressing_twice(site, user):
    user("POST", "/do", {"kind": "receipt", "back": "/"})
    (site.base / "requests/receipt").unlink()  # as if it had been picked up
    user("POST", "/do", {"kind": "receipt", "back": "/"})
    assert list((site.base / "requests").iterdir()) == []
    assert "Wait 20 seconds" in user(path="/").text


def test_a_request_nobody_picks_up_stops_the_waiting(site, user):
    old = site.base / "requests/preview"
    old.touch()
    os.utime(old, (time.time() - 300, time.time() - 300))
    text = user(path="/receipt").text
    assert "not answering" in text and 'http-equiv="refresh"' not in text


def test_waiting_behind_another_job_is_not_a_failure(site, user):
    old = site.base / "requests/preview"
    old.touch()
    os.utime(old, (time.time() - 300, time.time() - 300))
    busy = site.base / "out/result-receipt.json"
    busy.write_text(json.dumps({"state": "working", "text": "", "at": datetime.now(timezone.utc).isoformat()}))
    assert "appears here by itself" in user(path="/receipt").text
    busy.unlink()
    assert "not answering" in user(path="/receipt").text


def test_the_guide_for_the_phone_knows_the_address_and_what_has_come(site, user):
    (site.base / "out/status.json").write_text(json.dumps(status(health=[["Calendar", "list at Tue 07:00"], ["Reminders", "none today"]])))
    text = user(path="/phone").text
    assert "https://printer.example.com:8443/calendar" in text and "https://printer.example.com:8443/reminders" in text and "list at Tue 07:00" in text
    assert "yyyy-MM-dd HH:mm" in text and "Due Date <b>is today</b>" not in text  # the printer sorts them out
    assert 'class="bag full"' in text and 'class="bag empty"' in text and 'href="/phone"' in user(path="/times").text
    assert user(path="/phone").status == 200 and call(site, path="/phone").status == 303


def test_a_new_phone_token_is_shown_once_and_only_its_fingerprint_is_kept(site, user):
    reply = user("POST", "/keys", {"what": "phone"})
    assert reply.headers["Location"] == "/password#phone"
    text = user(path="/password").text
    token = re.search(r"<code>([A-Za-z0-9_-]{43})</code>", text)[1]
    kept = site.base / "phone/token.sha256"
    assert kept.read_text().strip() == hashlib.sha256(token.encode()).hexdigest() and kept.stat().st_mode & 0o777 == 0o640
    assert token not in user(path="/password").text and "made here on" in user(path="/password").text
    assert token not in site.log.read_text() and all(token.encode() not in p.read_bytes() for p in site.base.rglob("*") if p.is_file())
    assert [p.name for p in kept.parent.iterdir()] == ["token.sha256"]
    kept.unlink()


def test_a_train_token_is_handed_over_and_never_shown(site, user):
    token = "a-train-token-0123456789"
    request, answer = site.base / "requests/rail", site.base / "out/result-rail.json"
    seen = []

    def reporter():
        for _ in range(100):
            if request.exists() and request.read_text():
                seen.append((request.read_text(), request.stat().st_mode & 0o777))
                answer.write_text(json.dumps({"state": "done", "text": "Saved and working: 9 departures from X", "at": datetime.now(timezone.utc).isoformat()}))
                request.unlink()
                return
            time.sleep(0.02)
    worker = threading.Thread(target=reporter)
    worker.start()
    assert user("POST", "/keys", {"what": "rail", "token": f" {token} "}).headers["Location"] == "/password#rail"
    worker.join()
    text = user(path="/password").text
    assert seen == [(token, 0o640)] and "Saved and working" in text and token not in text and token not in site.log.read_text()
    answer.unlink()
    for bad in ("", "short", "x" * 5000, "with space inside it", "<script>alert(1)</script>"):
        user("POST", "/keys", {"what": "rail", "token": bad})
        assert "does not look like a token" in user(path="/password").text and not request.exists()
    assert user("POST", "/keys", {"what": "cloudflare"}).status == 400
    assert call(site, "POST", "/keys", {"what": "phone"}).headers["Location"] == "/login?lost=/password"


def test_pictures(site, user):
    (site.base / "out/preview.png").write_bytes(b"\x89PNG data")
    reply = user(path="/preview.png?1")
    assert reply.headers["Content-Type"] == "image/png" and "PNG data" in reply.text
    (site.base / "out/trains.png").symlink_to("/etc/hosts")
    assert user(path="/trains.png").status == 404
    (site.base / "out/trains.png").unlink()


def test_the_log_says_who_and_what_kind_but_never_what(site, user):
    user("POST", "/content", {"group": "news", "count": "5", "name-0": "SECRETNAME", "url-0": "https://secret.example/x"})
    user("POST", "/login", {"password": "SECRETPASSWORD"})
    log = site.log.read_text()
    assert "changed news from 127.0.0.1" in log and "signed in" in log and "sign-in refused" in log
    assert "SECRET" not in log and "secret" not in log and user.cookie.split("=")[1] not in log and "Traceback" not in log


def test_garbage_and_idle_connections_do_not_break_it(site, user):
    for payload in (b"GET / HTTP/1.0\r\n\r\n", b"\x00" * 500, b""):
        with socket.create_connection(("127.0.0.1", site.port), timeout=5) as raw:
            raw.sendall(payload)
    time.sleep(0.3)
    idle = [socket.create_connection(("127.0.0.1", site.port), timeout=5) for _ in range(4)]
    assert user(path="/times").status == 200
    for raw in idle:
        raw.close()
    assert site.proc.poll() is None and site.tls.poll() is None


def test_one_visitor_cannot_hold_every_place(site, user):
    idle = [socket.create_connection(("127.0.0.1", site.port), timeout=5) for _ in range(20)]
    time.sleep(0.3)
    idle[-1].settimeout(1)
    assert idle[-1].recv(1) == b""  # turned away at once
    for raw in idle:
        raw.close()
    time.sleep(0.5)
    assert user(path="/times").status == 200


def memory(proc):
    return int(subprocess.run(["ps", "-o", "rss=", "-p", str(proc.pid)], capture_output=True, text=True).stdout) // 1024


def test_endless_headers_are_cut_off(site, user):
    """The review pushed it from 28 to 206 MB like this, without signing in."""
    before = memory(site.proc), memory(site.tls)
    context, held = ssl._create_unverified_context(), []
    for _ in range(5):
        conn = context.wrap_socket(socket.create_connection(("127.0.0.1", site.port), timeout=10))
        try:
            conn.sendall(b"GET /login HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\n")
            for i in range(95):
                conn.sendall(b"X-%d: " % i + os.urandom(32000).hex().encode() + b"\r\n")
        except OSError:
            pass
        held.append(conn)
    assert memory(site.proc) - before[0] < 30 and memory(site.tls) - before[1] < 30
    for conn in held:
        conn.close()
    time.sleep(0.5)
    assert user(path="/times").status == 200


def test_the_program_with_the_pages_never_has_the_key(site):
    source = "".join((config.ROOT / f"reporter_web/{n}.py").read_text() for n in ("server", "auth", "store", "pages", "forms"))
    assert "key.pem" not in source and "import ssl" not in source
    unit = (config.ROOT / "deploy/reporter-web.service").read_text()
    assert "PrivateNetwork=yes" in unit and "RestrictAddressFamilies=none" in unit and "privkey" not in unit
    proxy = (config.ROOT / "deploy/reporter_web_tls.py").read_text()
    assert "reporter_web." not in proxy and "reporter-web.service" not in proxy


@pytest.mark.parametrize("first", [b"", b"nonsense\n", b"1.2.3.4", b"x" * 500 + b"\n", b"\xff\n"])
def test_a_caller_without_an_address_is_dropped(site, first):
    with socket.socket(socket.AF_UNIX) as raw:
        raw.settimeout(5)
        raw.connect(site.socket)
        raw.sendall(first + b"GET /login HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\n\r\n")
        raw.shutdown(socket.SHUT_WR)
        try:
            assert raw.recv(10) == b""
        except ConnectionResetError:
            pass


def test_a_form_cut_off_on_the_way_is_not_saved(site, user):
    body = urlencode({"csrf": user.token, "count": "5", "name-0": "X", "url-0": "https://feeds.example.com/london.xml"}).encode()
    context = ssl._create_unverified_context()
    with socket.create_connection(("127.0.0.1", site.port), timeout=15) as raw, context.wrap_socket(raw) as conn:
        conn.sendall(b"POST /news HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\nOrigin: " + ORIGIN.encode() +
                     b"\r\nContent-Type: application/x-www-form-urlencoded\r\nCookie: " + user.cookie.encode() +
                     b"\r\nContent-Length: %d\r\n\r\n" % len(body) + body[:-10])
    time.sleep(0.5)
    assert not (site.base / "settings/settings.json").exists() and user(path="/times").status == 200


def test_dropped_visitors_do_not_hold_places(site, user):
    for _ in range(60):
        with socket.create_connection(("127.0.0.1", site.port), timeout=5) as raw:
            raw.sendall(b"\x16\x03\x01")
    context = ssl._create_unverified_context()
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", site.port), timeout=5) as raw, context.wrap_socket(raw):
                pass
        except OSError:
            pass
    time.sleep(1)
    assert user(path="/times").status == 200


def load_relay():
    spec = importlib.util.spec_from_file_location("tls", config.ROOT / "deploy/reporter_web_tls.py")
    tls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tls)
    return tls


@pytest.mark.parametrize("addresses", [("192.168.1.5",), ("fe80::1%eth0", "fe80::2", "fe80::ffff:1"), ("2001:db8:1:2::1", "2001:db8:1:2:ffff::9")])
def test_one_device_counts_once(addresses):
    assert len({load_relay().group(a) for a in addresses}) == 1
    assert load_relay().group("2001:db8:1:3::1") != load_relay().group("2001:db8:1:2::1")


def test_old_tls_is_refused(site):
    context = ssl._create_unverified_context()
    context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    context.maximum_version = ssl.TLSVersion.TLSv1_1
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", site.port), timeout=5) as raw:
        context.wrap_socket(raw)


def test_an_unfinished_request_is_dropped(monkeypatch):
    tls = load_relay()
    assert tls.LIFETIME <= 60 and tls.MAX_UP >= server.MAX_BODY * 1.5 and tls.MAX_CLIENTS <= server.MAX_CLIENTS
    monkeypatch.setattr(tls, "LIFETIME", 1)

    class Slow(tls.Proxy):
        async def relay(self, connection, name, opened):
            await asyncio.sleep(30)
    proxy = Slow(socket.create_server(("127.0.0.1", 0)), None, "")
    ours, theirs = socket.socketpair()
    proxy.clients["x"] = 1
    started = time.monotonic()
    asyncio.run(proxy.serve(theirs, "x", "x"))
    assert time.monotonic() - started < 3 and proxy.clients == {} and ours.recv(1) == b""


# --- the parts ---

def test_passwords(monkeypatch):
    stored = auth.hash_password("pässword long enough")
    assert auth.verify("pässword long enough", stored)  # typed on another keyboard
    assert not auth.verify("password long enough", stored) and not auth.verify("x" * 100_000, stored)
    assert stored != auth.hash_password("pässword long enough")
    for bad in ("short", "x" * 201):
        with pytest.raises(ValueError):
            auth.hash_password(bad)
    for damaged in ("", "scrypt:aa:bb", "plain:text", "scrypt:" + "z" * 32 + ":" + "0" * 64):
        with pytest.raises(ValueError):
            auth.Auth(damaged)


def test_guessing_gets_slower_and_then_waits():
    now = [0.0]
    throttle = auth.Throttle(lambda: now[0])
    waits = []
    for _ in range(20):
        assert throttle.open()
        throttle.failed()
        waits.append(max(0.0, throttle.blocked_until - now[0]))
        now[0] = max(now[0], throttle.blocked_until)
    assert waits[:4] == [0, 0, 0, 0] and waits[4:8] == [2, 4, 8, 16] and waits[-1] == auth.MAX_DELAY
    throttle.succeeded()
    assert throttle.open() and throttle.failures == 0


def test_a_blocked_sign_in_does_not_even_check_the_password(monkeypatch):
    now = [0.0]
    gate = auth.Auth(auth.hash_password(PASSWORD), lambda: now[0])
    monkeypatch.setattr(auth, "verify", lambda p, s: p == PASSWORD)
    for _ in range(auth.FREE_TRIES):
        assert gate.log_in("wrong") is None
    with pytest.raises(auth.Locked):
        gate.log_in(PASSWORD)
    now[0] += auth.MAX_DELAY
    assert gate.log_in(PASSWORD) is not None


def test_sessions_end(monkeypatch):
    now = [0.0]
    gate = auth.Auth(auth.hash_password(PASSWORD), lambda: now[0])
    monkeypatch.setattr(auth, "verify", lambda p, s: True)
    token = gate.log_in("x").token
    assert all(token not in key for key in gate.sessions)  # only a fingerprint is kept
    for _ in range(30):
        now[0] += auth.IDLE - 1
        if gate.session(token) is None:
            break
    assert auth.LONGEST - auth.IDLE < now[0] <= auth.LONGEST + auth.IDLE  # even when used all the time
    token = gate.log_in("x").token
    now[0] += auth.IDLE + 1
    assert gate.session(token) is None
    tokens = [gate.log_in("x").token for _ in range(auth.MAX_SESSIONS + 3)]
    assert len(gate.sessions) == auth.MAX_SESSIONS and gate.session(tokens[-1]) and gate.session("") is None


def test_only_html_is_trusted():
    assert markup.h("<p>{x}</p>", x="<b>{y}'\"&") == "<p>&lt;b&gt;{y}&#x27;&quot;&amp;</p>"
    assert markup.h("{x}", x=markup.h("<i>{y}</i>", y="<")) == "<i>&lt;</i>"
    with pytest.raises(TypeError):
        markup.join(["<b>"])


def test_no_template_is_filled_by_hand():
    """Html(...) around anything but a fixed piece of text would skip the escaping."""
    for name in ("pages", "markup", "server", "art"):
        source = (config.ROOT / f"reporter_web/{name}.py").read_text()
        for use in re.findall(r"(?<!class )Html\((.*)", source):
            assert use.startswith(("'", '"', ")", 'f" {name}"', "template.format", '"".join', "str)", "...) around")), use
        assert "f'<" not in source and 'f"<' not in source


@pytest.mark.parametrize("module", ["server"])
def test_needs_nothing_installed(module):
    code = f"import sys; sys.path.insert(0, {str(config.ROOT)!r}); import reporter_web.{module}; " \
           "print(sorted(m for m in sys.modules if m.split('.')[0] in ('requests', 'PIL', 'serial', 'segno', 'reporter')))"
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['reporter', 'reporter.settings', 'reporter.stations']"


# --- First Up ---

def test_the_look_is_served_to_anybody_and_nothing_else_is(site):
    for path, kind in (("/style.css", "text/css"), ("/icon.svg", "image/svg+xml"), ("/apple-touch-icon.png", "image/png"),
                       ("/manifest.webmanifest", "application/manifest+json"), ("/fonts/cabin-latin.woff2", "font/woff2")):
        reply = call(site, path=path + "?v=1")
        assert reply.status == 200 and reply.headers["Content-Type"].startswith(kind) and "public" in reply.headers["Cache-Control"], path
    for path in ("/fonts/", "/fonts/../server.py", "/fonts/OFL-cabin.txt", "/static/cabin-latin.woff2", "/fonts/%2e%2e/auth.py"):
        assert call(site, path=path).status == 404


def test_every_font_and_picture_the_style_sheet_names_exists():
    css = (config.ROOT / "reporter_web/style.css").read_text()
    assert set(re.findall(r"url\(([^)]+)\)", css)) <= set(server.STATIC)
    assert "http" not in css.replace("http-equiv", "") and "@import" not in css


def test_every_choice_has_its_colour_or_reaction():
    css = server.STATIC["/style.css"][0].decode()
    for name in settings.LINES:
        assert f".{pages.line_class(name)} " in css
    for name in settings.SECTIONS:
        assert f".car-{name}" in css and name in art._PATHS, f"draw an icon called {name} in reporter_web/art.py"
    for heat in range(settings.HEAT[0], settings.HEAT[1] + 1, 5):
        angle = art.gauge_angle(heat)
        assert f"#heat_time-{heat}:checked) .needle {{ transform: rotate({angle:g}deg)" in css
    assert set(settings.PRESSABLE) <= set(art._PATHS)
    for sky in ("dawn", "day", "dusk", "night"):
        assert f".sky-{sky} {{ --s1" in css


def test_drawings_say_what_is_true():
    train = art.receipt(["news", "weather"])
    assert train.index("car-news") < train.index("car-weather") and "car-tube" not in train
    assert re.search(r'car-news" transform="translate\(720 ', train) and re.search(r'car-weather" transform="translate\(616 ', train)
    clock = art.times(10, 30, "Monday at 10:30")
    assert 'class="hand" d="M0 14V-58" transform="rotate(315.0)"' in clock and 'transform="rotate(180)"' in clock
    assert "Monday at 10:30" in clock and 'class="hand' not in art.times(0, 0, "")
    assert art.content([("news", "headlines", True)]).count('class="arm clear"') == 1 and art.content([("news", "headlines", False)]).count('class="arm stop"') == 1
    assert "in use: headlines" in art.content([("news", "headlines", True), ("tube", "Underground", False)])
    bells = art.button({"receipt": 1, "wifi": 2, "sudoku": 2, "poster": 5}, {"health": 3})
    assert "for: 1 tap, 2 taps, 5 taps, hold 3 seconds" in bells and bells.count('<circle class="beat"') == 8 and bells.count('<rect class="beat"') == 1
    assert "for: none" in art.button({}, {})
    assert art.gauge_angle(70) == 0


@pytest.mark.parametrize("drawing", [art.today(), art.receipt(list(settings.SECTIONS)), art.times(8, 0, "Monday at 08:00"), art.content([("weather", "weather", True)] * 7), art.button({n: i for i, n in enumerate(settings.SECTIONS, 1) if i < 10}, {"wifi": 4}), art.heat(70), art.app_icon()])
def test_drawings_are_well_formed_and_carry_no_styles_or_links(drawing):
    import xml.etree.ElementTree as ET
    ET.fromstring(drawing)
    assert "style=" not in drawing and "href" not in drawing and "url(" not in drawing and "<script" not in drawing


@pytest.mark.parametrize("day, rise, set_", [("2026-11-24", "07:33", "16:00"), ("2026-06-21", "03:43", "20:21"), ("2026-12-21", "08:04", "15:53")])
def test_sun_times_for_london(day, rise, set_):
    got = sun.sun(datetime.fromisoformat(day).date(), 51.5085, -0.1257)
    for moment, known in ((got.rise, rise), (got.set, set_)):
        assert abs((moment - datetime.fromisoformat(f"{day}T{known}:00+00:00")).total_seconds()) < 180


@pytest.mark.parametrize("clock, sky", [("05:00", "night"), ("07:00", "dawn"), ("08:30", "dawn"), ("12:00", "day"), ("15:00", "dusk"), ("16:30", "dusk"), ("17:00", "night"), ("23:59", "night")])
def test_the_sky_follows_the_sun(clock, sky):
    assert sun.sky(datetime.fromisoformat(f"2026-11-24T{clock}:00+00:00"), 51.5085, -0.1257) == sky


@pytest.mark.parametrize("latitude", [89.9, -89.9, 71.0, 0.0, 90, -90])
def test_places_without_a_sunrise(latitude):
    for month in range(1, 13):
        moment = datetime(2026, month, 15, 12, tzinfo=timezone.utc)
        assert sun.sky(moment, latitude, 179.9) in ("dawn", "day", "dusk", "night")
        assert isinstance(sun.beside_sunrise(moment, latitude, 179.9), str)


@pytest.mark.parametrize("clock, words", [("08:00", "27 minutes after sunrise"), ("07:00", "33 minutes before sunrise"), ("09:33", "2 hours after sunrise"),
                                          ("08:43", "1 hour 10 minutes after sunrise"), ("13:00", ""), ("07:33", "at sunrise")])
def test_words_about_sunrise(monkeypatch, clock, words):
    monkeypatch.setattr(sun, "sun", lambda *a: sun.Sun(datetime.fromisoformat("2026-11-24T07:33:00+00:00"), None))
    assert sun.beside_sunrise(datetime.fromisoformat(f"2026-11-24T{clock}:00+00:00"), 0, 0) == words


def test_a_message_does_not_push_the_page_aside():
    css = (config.ROOT / "reporter_web/style.css").read_text()
    assert ".with-slip > .flash, .with-slip > .body { grid-column: 1; } .with-slip > aside { grid-column: 2; grid-row: 1 / span 2; }" in css


# --- the password page ---

@pytest.fixture
def new_auth(tmp_path):
    def make(password=PASSWORD):
        return auth.Auth(auth.load_password(tmp_path / "password", auth.hash_password(password)), changed=tmp_path / "password")
    return make, tmp_path / "password"


def test_changing_the_password(new_auth):
    make, path = new_auth
    gate = make()
    first, other = gate.log_in(PASSWORD), gate.log_in(PASSWORD)
    login = gate.change(PASSWORD, "another long password")
    assert gate.session(first.token) is None and gate.session(other.token) is None and gate.session(login.token)
    assert gate.log_in(PASSWORD) is None and gate.log_in("another long password")
    assert os.stat(path).st_mode & 0o777 == 0o600 and "another" not in path.read_text() and [p.name for p in path.parent.iterdir()] == ["password"]
    assert make().log_in("another long password") and make().log_in(PASSWORD) is None  # after a restart


@pytest.mark.parametrize("current, new", [("wrong", "another long password"), (PASSWORD, "short"), (PASSWORD, "x" * 201), (PASSWORD, PASSWORD), ("", "another long password")])
def test_a_password_change_that_is_refused_changes_nothing(new_auth, current, new):
    make, path = new_auth
    gate = make()
    session = gate.log_in(PASSWORD)
    try:
        assert gate.change(current, new) is None
    except ValueError:
        pass
    assert not path.exists() and gate.session(session.token) and gate.log_in(PASSWORD)


def test_the_current_password_cannot_be_guessed_on_that_page(new_auth, monkeypatch):
    gate = new_auth[0]()
    for _ in range(auth.FREE_TRIES):
        assert gate.change("wrong", "another long password") is None
    with pytest.raises(auth.Locked):
        gate.change(PASSWORD, "another long password")
    with pytest.raises(auth.Locked):
        gate.log_in(PASSWORD)


def test_a_damaged_password_file_does_not_bring_the_old_one_back(new_auth):
    make, path = new_auth
    path.write_text("damaged")
    with pytest.raises(ValueError):
        make()


def test_a_damaged_password_file_says_what_to_do(tmp_path, monkeypatch):
    (make_base(tmp_path / "base") / "settings/password").write_text("damaged")
    (tmp_path / "password").write_text(auth.hash_password(PASSWORD))
    monkeypatch.setattr(server, "CREDENTIALS", tmp_path)
    monkeypatch.setattr(server, "Store", lambda: store.Store(tmp_path / "base"))
    monkeypatch.setattr(os, "umask", lambda mask: 0)
    with pytest.raises(SystemExit) as stop:
        server.main()
    assert "--new-password" in str(stop.value)


def test_a_full_disk_leaves_the_password_alone(new_auth, monkeypatch):
    make, path = new_auth
    gate = make()
    monkeypatch.setattr(auth, "save_password", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        gate.change(PASSWORD, "another long password")
    assert gate.log_in(PASSWORD)


def test_the_password_page(site, user):
    page = user(path="/password").text
    assert page.count('type="password"') == 4 and 'autocomplete="new-password"' in page
    bad = [{"current": PASSWORD, "new": "another long password", "again": "different password"}, {"current": "wrong", "new": "another long password", "again": "another long password"},
           {"current": PASSWORD, "new": "short", "again": "short"}, {}]
    for form in bad:
        assert user("POST", "/password", form).status == 422
    assert not (site.base / "settings/password").exists()
    assert call(site, "POST", "/password", {"current": PASSWORD, "new": "another long password", "again": "another long password"}, cookie=user.cookie).status == 303
    assert "before you signed in" in user(path="/password").text and not (site.base / "settings/password").exists()
    reply = user("POST", "/password", {"current": PASSWORD, "new": "another long password", "again": "another long password"})
    assert reply.status == 303 and "HttpOnly" in reply.headers["Set-Cookie"] and user(path="/times").status == 303
    _, cookie = sign_in(site, "another long password")
    token = re.search(r'name="csrf" value="([^"]+)"', call(site, path="/button", cookie=cookie).text)[1]
    assert call(site, "POST", "/password", {"csrf": token, "current": "another long password", "new": PASSWORD, "again": PASSWORD}, cookie=cookie).status == 303
    (site.base / "settings/password").unlink()
    log = site.log.read_text()
    assert "password changed from 127.0.0.1" in log and "another long" not in log
