"""HTTP session with timeouts and retries; nothing here can hang the report."""

import ipaddress
import json
import logging
import queue
import socket
import threading
import time
import traceback
import zlib
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import __version__, settings

log = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
TIMEOUT = (5, 15)  # connect, read
MAX_BYTES, MAX_JSON = 5_000_000, 1_500_000  # JSON takes thirty times its size in memory
MAX_RUNNING = 20  # downloads, given up or not: those given up may go on for long, and threads are few
MAX_SECONDS = 60
AGAIN, PAUSE = (429, 500, 502, 503, 504), 1.5
MAX_REDIRECTS = 4


def make_session() -> requests.Session:
    # Status codes are retried in _get: here that would read the whole of a faulty reply.
    retry = Retry(total=3, connect=1, status=0, backoff_factor=1, allowed_methods=("GET",), respect_retry_after_header=False)
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.get_redirect_target = lambda response: None  # or requests reads the whole reply to look for it
    session.headers.update({"User-Agent": f"receipt-reporter/{__version__}", "Accept-Encoding": "gzip"})
    return session


class Reply:
    def __init__(self, content: bytes, redirect: str = "") -> None:
        self.content = content
        self.redirect = redirect  # only when redirects are not followed

    def json(self):
        if len(self.content) > MAX_JSON:
            raise ValueError(f"over {MAX_JSON} bytes")
        return json.loads(self.content)


_running = threading.BoundedSemaphore(MAX_RUNNING)


def limited(seconds: float, work: Callable):
    """The result of `work`, or TimeoutError. Nothing else stops a site that sends a byte
    now and then: every byte starts the usual timeouts again."""
    box: queue.SimpleQueue = queue.SimpleQueue()

    def run() -> None:
        try:
            box.put((True, work()))
        except BaseException as exc:
            box.put((False, exc))
        finally:
            _running.release()
    if not _running.acquire(blocking=False):
        raise TimeoutError("too many downloads that never end")
    try:
        threading.Thread(target=run, daemon=True).start()
    except RuntimeError:
        _running.release()
        raise
    try:
        ok, value = box.get(timeout=seconds)
    except queue.Empty:
        raise TimeoutError(f"no complete reply in {seconds:g} s") from None
    if ok:
        return value
    raise value


def _pieces(response) -> Iterator[bytes]:
    """As they come in, so that the deadline is looked at after each byte that drips."""
    raw = getattr(response, "raw", None)
    if not hasattr(raw, "read1"):
        yield from response.iter_content(16384)
        return
    coding = response.headers.get("Content-Encoding", "identity").lower()
    if coding not in ("identity", "gzip"):
        raise ValueError("unknown compression")
    unzip = zlib.decompressobj(47) if coding == "gzip" else None
    while piece := raw.read1(16384, decode_content=False):
        yield unzip.decompress(piece, MAX_BYTES + 1) if unzip else piece


def _get(session: requests.Session, url: str, deadline: float, **kwargs) -> Reply:
    """Once more if the site is busy or ill for a moment."""
    try:
        return _once(session, url, deadline, **kwargs)
    except requests.HTTPError as exc:
        if exc.response.status_code not in AGAIN or time.monotonic() + PAUSE > deadline:
            raise
    time.sleep(PAUSE)
    return _once(session, url, deadline, **kwargs)


def _once(session: requests.Session, url: str, deadline: float, **kwargs) -> Reply:
    body = bytearray()
    response = session.get(url, timeout=TIMEOUT, stream=True, **kwargs)
    try:
        response.raise_for_status()
        for chunk in _pieces(response):
            body += chunk
            if len(body) > MAX_BYTES:
                raise ValueError(f"reply from {response.url} is over {MAX_BYTES} bytes")
            if time.monotonic() > deadline:  # nobody is waiting any more
                raise TimeoutError(f"reply from {response.url} took too long")
    finally:
        response.close()
    return Reply(bytes(body), response.headers.get("Location", "") if response.is_redirect else "")


def get(session: requests.Session, url: str, seconds: float = MAX_SECONDS, redirects: bool = True, **kwargs) -> Reply:
    """Like session.get, but a faulty site can send neither too much nor for too long, and can
    only redirect to public https. Without `redirects`, the caller gets to see them."""
    deadline = time.monotonic() + seconds
    if redirects:
        return limited(seconds, lambda: _follow(session, url, deadline, **kwargs))
    return limited(seconds, lambda: _get(session, url, deadline, allow_redirects=False, **kwargs))


def _follow(session: requests.Session, url: str, deadline: float, **kwargs) -> Reply:
    where = url
    for _ in range(MAX_REDIRECTS + 1):
        reply = _get(session, where, deadline, allow_redirects=False, **kwargs)
        if not reply.redirect:
            return reply
        where, kwargs = urldefrag(urljoin(where, reply.redirect)).url, {}
        check_public(where)
    raise ValueError("too many redirects")


def check_public(url: str) -> None:
    """Refuse an address on the home network or on this Pi. Addresses people can type in
    must not be a way to reach what the router hides."""
    settings.feed_url(url)  # no odd characters that others might read differently
    found = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
    if not found or not all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in found):
        raise ValueError("not a public address")


def get_public(session: requests.Session, url: str, seconds: float = MAX_SECONDS) -> Reply:
    """`get` for an address somebody typed in: every step must be public https."""
    deadline = time.monotonic() + seconds

    def steps() -> Reply:
        check_public(url)
        return _follow(session, url, deadline)
    return limited(seconds, steps)


def reason(exc: BaseException) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"the service answered {status}" if status else type(exc).__name__


def trace(exc: BaseException) -> str:
    """For the log: what and where, but not the message. That holds the address asked for, and
    so the position, the station or a feed's key."""
    ours = [frame for frame in traceback.extract_tb(exc.__traceback__) if Path(frame.filename).is_relative_to(HERE)]
    return f"{reason(exc)} ({Path(ours[-1].filename).name}:{ours[-1].lineno})" if ours else reason(exc)


def wait_for_network(host: str = "api.open-meteo.com", timeout: float = 300, poll: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            socket.create_connection((host, 443), timeout=5).close()
            return True
        except OSError as exc:
            if time.monotonic() >= deadline:
                log.error("no network after %.0fs: %s", timeout, exc)
                return False
            time.sleep(poll)
