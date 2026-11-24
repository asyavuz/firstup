import gzip
import re
import socket
import threading
import time
import tracemalloc
from types import SimpleNamespace
from xml.parsers import expat

import pytest
from test_weekend import FakeResponse

from reporter import config, feeds, http, settings
from reporter.sections import news


class Session:
    def __init__(self, chunks):
        self.response = FakeResponse(b"")
        self.response.chunks = chunks
        self.response.close = lambda: setattr(self, "closed", True)

    def get(self, url, timeout, stream, **kwargs):
        assert stream and timeout
        return self.response


def test_normal_reply():
    session = Session([b'{"a":', b" 1}"])
    assert http.get(session, "https://x.test").json() == {"a": 1}
    assert session.closed


def test_endless_reply_is_cut_off():
    def endless():
        while True:
            yield b"x" * 65536
    session = Session(endless())
    with pytest.raises(ValueError, match="over"):
        http.get(session, "https://x.test")
    assert session.closed


@pytest.fixture(params=["headers", "body"])
def drip(request):
    """A real site that sends one byte now and then, which starts every read timeout again."""
    listener = socket.create_server(("127.0.0.1", 0))
    stop = threading.Event()

    def serve():
        conn, _ = listener.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nX: " if request.param == "headers" else b"HTTP/1.1 200 OK\r\nContent-Length: 900\r\n\r\n")
        while not stop.wait(0.2):
            try:
                conn.sendall(b"x")
            except OSError:
                break
        conn.close()
    threading.Thread(target=serve, daemon=True).start()
    yield f"http://127.0.0.1:{listener.getsockname()[1]}/"
    stop.set()
    listener.close()


def test_a_dripping_site_is_given_up(drip):
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        http.get(http.make_session(), drip, seconds=1)
    assert time.monotonic() - started < 2


def test_a_dripping_feed_is_given_up_and_the_others_still_count(drip, monkeypatch):
    monkeypatch.setattr(http, "check_public", lambda url: None)
    monkeypatch.setattr(news, "FEED_SECONDS", 1)
    real = http._get
    feed = b"<rss><channel><item><title>Fine</title></item></channel></rss>"
    monkeypatch.setattr(http, "_get", lambda session, url, deadline, **kw: real(session, url, deadline, **kw) if url == drip else http.Reply(feed))
    cfg = SimpleNamespace(news=SimpleNamespace(count=3, feeds=(config.Feed("A", drip), config.Feed("B", "https://b.example/"))))
    started = time.monotonic()
    assert [h.title for h in news.fetch(cfg, http.make_session(), None)] == ["Fine"]
    assert time.monotonic() - started < 3


def test_downloads_that_never_end_do_not_use_up_the_threads():
    stop = threading.Event()
    for _ in range(http.MAX_RUNNING):
        with pytest.raises(TimeoutError):
            http.limited(0.01, lambda: stop.wait(20))
    before = threading.active_count()
    with pytest.raises(TimeoutError, match="too many"):
        http.limited(5, lambda: 7)
    assert threading.active_count() == before
    stop.set()
    time.sleep(0.2)
    assert http.limited(5, lambda: 7) == 7


def test_a_download_that_was_given_up_ends_at_the_next_byte(drip):
    before = threading.active_count()
    with pytest.raises(TimeoutError):
        http.get(http.make_session(), drip, seconds=0.5)
    for _ in range(50):  # slow headers are only bounded by MAX_RUNNING
        if threading.active_count() <= before:
            break
        time.sleep(0.1)
    assert threading.active_count() <= before + 1


@pytest.fixture
def site():
    """A real one that answers with what is put into `reply`; counts the bytes it got rid of."""
    listener, state = socket.create_server(("127.0.0.1", 0)), SimpleNamespace(reply=b"", asked=0, sent=0)

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            state.asked += 1
            conn.recv(4096)
            try:
                for piece in [state.reply] if isinstance(state.reply, bytes) else state.reply():
                    conn.sendall(piece)
                    state.sent += len(piece)
            except OSError:
                pass
            conn.close()
    threading.Thread(target=serve, daemon=True).start()
    state.url = f"http://127.0.0.1:{listener.getsockname()[1]}/"
    yield state
    listener.close()


def zipped(data):
    body = gzip.compress(data)
    return b"HTTP/1.1 %s\r\nContent-Encoding: gzip\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


def test_compressed_replies_are_read(site):
    site.reply = zipped(b'{"a": 1}').replace(b"%s", b"200 OK")
    assert http.get(http.make_session(), site.url).json() == {"a": 1}


@pytest.mark.parametrize("start", [b"200 OK", b"302 Found\r\nLocation: https://127.0.0.1/"])
def test_a_small_reply_cannot_grow_huge(site, start):
    site.reply = zipped(b"x" * 300_000_000).replace(b"%s", start)
    tracemalloc.start()
    with pytest.raises(ValueError):
        http.get(http.make_session(), site.url)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 40_000_000


def test_an_endless_error_is_neither_read_nor_asked_for_again_and_again(site, monkeypatch):
    monkeypatch.setattr(http, "PAUSE", 0.1)
    site.reply = lambda: (b"HTTP/1.1 503 Busy\r\n\r\n" if not i else b"x" * 65536 for i in range(2000))
    with pytest.raises(Exception, match="503"):
        http.get(http.make_session(), site.url, seconds=10)
    time.sleep(0.5)
    assert site.sent < 20_000_000 and site.asked == 2


def test_a_site_that_is_ill_for_a_moment_is_asked_once_more(site, monkeypatch):
    monkeypatch.setattr(http, "PAUSE", 0.3)
    site.reply = b"HTTP/1.1 503 Busy\r\nContent-Length: 0\r\n\r\n"
    threading.Timer(0.15, lambda: setattr(site, "reply", b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")).start()
    assert http.get(http.make_session(), site.url).content == b"ok" and site.asked == 2


def test_json_that_would_take_all_the_memory_is_refused():
    with pytest.raises(ValueError, match="over"):
        http.Reply(b"[" + b'{"":0},' * 300_000 + b"0]").json()


def test_errors_come_through_unchanged():
    with pytest.raises(KeyError):
        http.limited(5, lambda: {}["x"])
    assert http.limited(5, lambda: 7) == 7


def test_the_whole_report_fits_in_the_time_the_unit_allows():
    unit = (config.ROOT / "deploy/reporter.service").read_text()
    allowed = int(re.search(r"TimeoutStartSec=(\d+)min", unit)[1]) * 60
    others = 6 * http.MAX_SECONDS  # weather, tube, weekend twice, quote, and one to spare
    assert others + settings.MAX_FEEDS * news.FEED_SECONDS < allowed / 2


def resolves_to(monkeypatch, *addresses):
    monkeypatch.setattr(http.socket, "getaddrinfo",
                        lambda host, port, **kw: [(0, 0, 0, "", (a, port)) for a in addresses])


@pytest.mark.parametrize("address", ["192.168.1.1", "10.0.0.1", "172.16.0.9", "127.0.0.1", "169.254.1.1", "100.64.0.1",
                                     "0.0.0.0", "::1", "fe80::1%eth0", "fd00::1", "::ffff:192.168.1.1"])
def test_home_addresses_are_refused(monkeypatch, address):
    resolves_to(monkeypatch, address)
    with pytest.raises(ValueError):
        http.check_public("https://feeds.example.com/rss")
    resolves_to(monkeypatch, "151.101.0.81", address)  # one good answer does not help
    with pytest.raises(ValueError):
        http.check_public("https://feeds.example.com/rss")


@pytest.mark.parametrize("url", ["http://feeds.example.com/", "https://feeds.example.com:8443/", "file:///etc/passwd", "https:///x", "ftp://a.example/"])
def test_only_plain_https(monkeypatch, url):
    resolves_to(monkeypatch, "151.101.0.81")
    with pytest.raises(ValueError):
        http.check_public(url)


class Redirects:
    """Answers with the given steps: a Location, or b"..." to finish."""

    def __init__(self, *steps):
        self.steps, self.asked = list(steps), []

    def get(self, url, timeout, stream, allow_redirects, **kwargs):
        assert allow_redirects is False
        self.asked.append(url)
        step = self.steps.pop(0)
        response = FakeResponse(step if isinstance(step, bytes) else b"")
        response.is_redirect = not isinstance(step, bytes)
        response.headers = {"Location": step} if response.is_redirect else {}
        return response


def test_redirects_are_followed_one_checked_step_at_a_time(monkeypatch):
    resolves_to(monkeypatch, "151.101.0.81")
    session = Redirects("/new", "https://other.example/feed", b"<rss/>")
    assert http.get_public(session, "https://feeds.example.com/rss").content == b"<rss/>"
    assert session.asked == ["https://feeds.example.com/rss", "https://feeds.example.com/new", "https://other.example/feed"]


@pytest.mark.parametrize("target", ["https://127.0.0.1:9\\@public.example/feed", "https://127.0.0.1\\@public.example/feed",
                                    "//127.0.0.1\\@public.example/", "http://feeds.example.com/", "https://feeds.example.com:8444/", "https://192.168.1.1/"])
def test_a_redirect_cannot_lead_home(monkeypatch, target):
    monkeypatch.setattr(http.socket, "getaddrinfo",
                        lambda host, port, **kw: [(0, 0, 0, "", (host if host[0].isdigit() else "151.101.0.81", port))])
    with pytest.raises(ValueError):
        http.get_public(Redirects(target, b"secret"), "https://feeds.example.com/rss")


@pytest.mark.parametrize("target", ["http://printer.example/", "https://192.168.1.1/", "https://router.local/"])
def test_the_usual_sources_cannot_redirect_home_either(monkeypatch, target):
    resolves_to(monkeypatch, "151.101.0.81")
    session = Redirects(target, b"secret")
    with pytest.raises(ValueError):
        http.get(session, "https://source.example/data", params={"a": 1})
    assert session.asked == ["https://source.example/data"]


def test_endless_redirects_stop(monkeypatch):
    resolves_to(monkeypatch, "151.101.0.81")
    with pytest.raises(ValueError, match="too many"):
        http.get_public(Redirects(*["/again"] * 20), "https://feeds.example.com/rss")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_feeds_cannot_define_entities(encoding):
    bomb = f'<?xml version="1.0" encoding="{encoding}"?><!DOCTYPE r [<!ENTITY a "{"A" * 1000}">]><rss><channel><item><title>{"&a;" * 95}</title></item></channel></rss>'
    with pytest.raises(ValueError, match="of its own"):
        news.parse_feed(bomb.encode(encoding))
    plain = f'<?xml version="1.0" encoding="{encoding}"?><!DOCTYPE rss><rss><channel><item><title>A &amp; B</title></item></channel></rss>'
    assert news.parse_feed(plain.encode(encoding)) == ["A & B"]


def test_huge_feeds_stay_cheap():
    many = b"<rss><channel>" + b"<item><title>x</title></item>" * 100_000 + b"</channel></rss>"
    started = time.monotonic()
    titles = news.parse_feed(many)
    assert len(titles) == feeds.MAX_ITEMS and len(news.pick({"A": titles}, 5)) == 1
    long = b"<rss><channel><item><title>" + b"y" * 2_000_000 + b"</title></item></channel></rss>"
    assert len(news.parse_feed(long)[0]) == feeds.MAX_TEXT
    assert time.monotonic() - started < 5


def feed(inner, head="<rss>"):
    return (head + "<channel>" + inner + "</channel></rss>").encode()


HOSTILE = {
    "long namespace": lambda: feed("<a/>" * 400_000 + "<item><title>T</title></item>", f'<rss xmlns="{"n" * 2_000_000}">'),
    "many names": lambda: feed("".join(f"<a{i}/>" for i in range(200_000)), f'<rss xmlns="{"n" * 1_000_000}">'),
    "defaults": lambda: f'<!DOCTYPE rss [<!ATTLIST i x CDATA "{"d" * 1_000_000}">]><rss>{"<i/>" * 300}</rss>'.encode(),
    "deep": lambda: b"<a>" * 1_000_000,
    "long title": lambda: feed("<item><title>" + "t" * 4_000_000 + "</title></item>"),
    "pieces": lambda: feed("<item><title>" + "&amp;" * 800_000 + "</title></item>"),
    "attributes": lambda: feed("<item " + " ".join(f'a{i}="x"' for i in range(200_000)) + "><title>T</title></item>"),
}


@pytest.mark.parametrize("kind", HOSTILE)
def test_hostile_feeds_take_neither_time_nor_memory(kind):
    content = HOSTILE[kind]()
    assert len(content) < http.MAX_BYTES
    waits, stop = [0.0], threading.Event()

    def other_work():
        while not stop.is_set():
            started = time.monotonic()
            time.sleep(0.01)
            waits.append(time.monotonic() - started)
    thread = threading.Thread(target=other_work)
    thread.start()
    started = time.monotonic()
    try:
        news.parse_feed(content)
    except (ValueError, expat.ExpatError):
        pass
    took = time.monotonic() - started
    stop.set()
    thread.join()
    assert took < 3 and max(waits) < 2


@pytest.mark.parametrize("content, titles", [
    (feed("<title>Channel</title><item><title>A</title><link>x</link></item><item><title><![CDATA[B & <b>]]></title></item>"), ["A", "B & <b>"]),
    (feed("<item><title>One &amp;amp; two</title></item><item><title> </title></item><item><media:title>no</media:title></item>"), ["One & two"]),
    (feed("<item><title>a<b>bold</b>c</title></item>"), ["ac"]),
    ('<?xml version="1.0" encoding="ISO-8859-1"?><rss><channel><item><title>caf\u00e9</title></item></channel></rss>'.encode("latin-1"), ["caf\u00e9"]),
    (b"<feed><entry><title>not RSS</title></entry></feed>", []),
])
def test_ordinary_feeds(content, titles):
    assert news.parse_feed(content) == titles
