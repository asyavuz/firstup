"""The web interface's server, started by reporter-web.socket. It listens on a local socket
only; deploy/reporter_web_tls.py stands before it, holds the certificate, says on the first
line who is calling, and limits how long and how much.

Every request must name exactly this host; every change needs a session, its token and an
Origin that is exactly this site."""

import hashlib
import hmac
import ipaddress
import json
import os
import re
import select
import socket
import sys
import threading
import time
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import BaseServer
from typing import Optional
from urllib.parse import parse_qs

from . import art, pages
from .auth import IDLE, Auth, Draft, Locked, Session, load_password
from .forms import FORMS, fingerprint
from .store import IMAGES, KEYS, PAPER, SCREEN, Store

MAX_BODY = 32768
MAX_DRAIN = 65536
MAX_FIELDS = 300
MAX_CLIENTS = 32
SOCKET_TIMEOUT = 10
TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]{16,4096}")
MAX_WAITS = 2
HOLD = 30  # seconds a picture waits; the TLS program ends a connection after 40
IDLE_EXIT = IDLE + 60  # sessions are kept in memory, so stay until they have run out
COOKIE = "__Host-session"

CREDENTIALS = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/nonexistent"))

HEADERS = (
    ("Content-Security-Policy", "default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; manifest-src 'self'; "
                                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),  # no-referrer would make browsers send "Origin: null"
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), geolocation=(), microphone=()"),
    ("Strict-Transport-Security", "max-age=31536000"),
)
PRIVATE, PUBLIC = ("Cache-Control", "no-store"), ("Cache-Control", "public, max-age=604800")


def static_files() -> dict:
    """What anybody may see: the look, not the content. Read once, from a root-owned folder."""
    folder = Path(__file__).resolve().parent
    manifest = {"name": pages.NAME, "short_name": pages.NAME, "start_url": "/", "display": "standalone",
                "background_color": "#1f5269", "theme_color": "#1f5269",
                "icons": [{"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                          {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}
    files = {"/style.css": ((folder / "style.css").read_bytes() + pages.block_rules().encode(), "text/css; charset=utf-8"),
             "/icon.svg": (art.app_icon().encode(), "image/svg+xml"),
             "/apple-touch-icon.png": ((folder / "static/apple-touch-icon.png").read_bytes(), "image/png"),
             "/manifest.webmanifest": (json.dumps(manifest).encode(), "application/manifest+json")}
    for font in sorted((folder / "static").glob("*.woff2")):
        files[f"/fonts/{font.name}"] = (font.read_bytes(), "font/woff2")
    return files


STATIC = static_files()
pages.VERSION = hashlib.sha256(b"".join(body for body, _ in STATIC.values())).hexdigest()[:10]


class Refused(Exception):
    """Carries the HTTP status to answer with."""


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "printer", ""
    timeout = SOCKET_TIMEOUT
    body_read = False

    # --- answering ---

    def drain(self) -> None:
        """Read what is left of a refused request, or the browser never sees the reply."""
        length = getattr(self, "headers", None) and self.headers.get("Content-Length", "")
        if not self.body_read and length and length.isdecimal() and length.isascii():
            self.rfile.read(min(int(length), MAX_DRAIN))

    def reply(self, status: int, body: bytes = b"", kind: str = "text/plain; charset=utf-8", *extra, cache=PRIVATE) -> None:
        self.drain()
        self.close_connection = True
        self.send_response_only(status)
        for name, value in HEADERS + (cache, ("Content-Type", kind), ("Content-Length", str(len(body))), ("Connection", "close")) + extra:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def page(self, html: str, status: int = 200) -> None:
        self.reply(status, html.encode(), "text/html; charset=utf-8")

    def go(self, where: str, *extra) -> None:
        self.reply(303, b"", "text/plain; charset=utf-8", ("Location", where), *extra)

    def send_error(self, code, message=None, explain=None) -> None:
        self.reply(code if code in (400, 408, 414, 431) else 405, b"Refused")

    def log(self, what: str) -> None:
        print(f"{what} from {self.client_address[0]}", file=sys.stderr, flush=True)

    def log_message(self, *args) -> None:
        pass  # never write request contents to the log

    # --- checking ---

    def single(self, name: str) -> str:
        values = self.headers.get_all(name) or []
        if len(values) != 1:
            raise Refused(400)
        return values[0]

    def token(self) -> str:
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return cookies[COOKIE].value if COOKIE in cookies else ""

    def session(self) -> Optional[Session]:
        return self.server.auth.session(self.token())

    def check_origin(self) -> None:
        if self.single("Origin") != f"https://{self.server.host}":
            raise Refused(403)
        if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            raise Refused(403)

    def form(self) -> dict:
        length = self.single("Content-Length")
        if not (length.isdecimal() and length.isascii()) or self.headers.get("Transfer-Encoding"):
            raise Refused(400)
        if int(length) > MAX_BODY:
            raise Refused(413)
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            raise Refused(415)
        self.body_read = True
        body = self.rfile.read(int(length))
        if len(body) != int(length):  # cut off on the way: half an address is not an address
            raise Refused(400)
        try:
            return parse_qs(body.decode("ascii"), keep_blank_values=True,
                            max_num_fields=MAX_FIELDS, errors="strict")
        except ValueError:
            raise Refused(400) from None

    def guarded(self, action) -> None:
        try:
            if self.single("Host") != self.server.host:
                raise Refused(421)
            path = self.path.partition("?")[0]
            action(path)
        except Refused as refused:
            if refused.args[0] == 404 and self.command == "GET":
                self.page(pages.missing(), 404)
            else:
                self.reply(refused.args[0], b"Refused")
            if refused.args[0] != 404:  # browsers ask for all sorts of icons
                self.log(f"refused {refused.args[0]}")
        except (ConnectionError, TimeoutError):
            raise
        except Exception as exc:
            self.log(f"failed with {type(exc).__name__}")
            self.reply(500, b"Something went wrong")

    # --- doing ---

    def do_GET(self) -> None:
        self.guarded(self.get)

    def do_POST(self) -> None:
        self.guarded(self.post)

    def get(self, path: str) -> None:
        store = self.server.store
        if path in STATIC:
            return self.reply(200, *STATIC[path], cache=PUBLIC)
        session = self.session()
        if path == "/login":
            return self.go("/") if session else self.page(pages.login(*self.asked()))
        if path not in pages.SHOW and path[1:] not in IMAGES:
            raise Refused(404)
        if session is None:
            return self.go(f"/login?back={path}" if path in pages.SHOW and path != "/" else "/login")
        if path in pages.SHOW:
            return self.page(pages.SHOW[path](store, session))
        if "wait" in self.path.partition("?")[2]:  # the new one, as soon as there is one
            self.wait(IMAGES[path[1:]], session)
        image = store.read(path[1:])
        if image is None:
            raise Refused(404)
        self.reply(200, image, "image/png")

    def wait(self, kind: str, session: Session) -> None:
        """Until it has been made, but not for a browser that has gone: each wait takes one of
        the few connections a device may have."""
        if session.waits >= MAX_WAITS:
            return
        session.waits += 1
        try:
            until = time.monotonic() + HOLD
            while self.server.store.result(kind).busy and time.monotonic() < until:
                if select.select([self.connection], [], [], 0.25)[0] and not self.connection.recv(1, socket.MSG_PEEK):
                    raise ConnectionError("gone")
        finally:
            session.waits -= 1

    def post(self, path: str) -> None:
        if path not in ("/login", "/logout", "/do", "/password", "/keys") and path not in pages.CHANGE:
            raise Refused(404)
        self.check_origin()
        form = self.form()
        if path == "/login":
            return self.log_in(form)
        session, page = self.session(), path if path in pages.SHOW else "/password" if path == "/keys" else "/"
        if session is None:
            return self.go("/login" if path == "/logout" else f"/login?lost={page}")
        if not hmac.compare_digest(form.get("csrf", [""])[0].encode(), session.csrf.encode()):
            session.notes = {"": ("bad", "That page was from before you signed in. Nothing was done: please try again.")}
            self.log("refused: an old page")
            return self.go(page)
        if path == "/logout":
            self.server.auth.log_out(self.token())
            return self.go("/login", ("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"))
        if path == "/password":
            return self.change_password(form, session)
        if path == "/keys":
            return self.keys(form, session)
        if path == "/do":
            return self.ask(form, session)
        self.change(path, form, session)

    def asked(self) -> tuple:
        """What the sign-in page is to say, and where to go from there: only from a fixed list."""
        query = parse_qs(self.path.partition("?")[2])
        lost, back = query.get("lost", [""])[0], query.get("back", ["/"])[0]
        if lost in pages.SHOW:
            return "You were signed out in the meantime. What you sent was not done.", lost
        return "", back if back in pages.SHOW else "/"

    def log_in(self, form: dict) -> None:
        back = form.get("back", ["/"])[0]
        back = back if back in pages.SHOW else "/"
        try:
            login = self.server.auth.log_in(form.get("password", [""])[0])
        except Locked:
            self.log("sign-in locked")
            return self.page(pages.login(pages.LOCKED, back), 429)
        if login is None:
            self.log("sign-in refused")
            return self.page(pages.login("That was not the password.", back), 403)
        self.log("signed in")
        self.go(back, ("Set-Cookie", f"{COOKIE}={login.token}; Path=/; Secure; HttpOnly; SameSite=Strict"))

    def change_password(self, form: dict, session: Session) -> None:
        current, new, again = (form.get(name, [""])[0] for name in ("current", "new", "again"))
        login, problem = None, "that was not the current password"
        try:
            if new != again:
                problem = "the new passwords differ"
            else:
                login = self.server.auth.change(current, new)
        except Locked:
            problem = "too many tries. Wait two minutes"
        except ValueError as exc:
            problem = f"{str(exc)[:1].lower()}{str(exc)[1:]}"
        except OSError:
            problem = "it could not be stored"
        if login is None:
            self.log("password change refused")
            session.notes = {"": ("bad", f"Not changed: {problem}.")}
            return self.page(pages.SHOW["/password"](self.server.store, session), 422)
        self.log("password changed")
        login.session.notes = {"": ("good", "Password changed. Other devices have to sign in again.")}
        self.go("/password", ("Set-Cookie", f"{COOKIE}={login.token}; Path=/; Secure; HttpOnly; SameSite=Strict"))

    def keys(self, form: dict, session: Session) -> None:
        """Tokens: a new one for the phone, shown once, or one for the trains, handed on."""
        store, what = self.server.store, form.get("what", [""])[0]
        note, where = ("bad", "The Pi could not take that down. Its small disk may be full or missing."), "phone" if what == "phone" else "rail"
        try:
            if what == "phone" and store.phone_ready():
                with store.phone_lock:  # what is shown last is what is in force
                    session.secret = store.new_phone_token()
                note = ("good", "A new token is in force. The old one no longer works.")
                self.log("made a new phone token")
            elif what in KEYS:
                text = form.get("token", [""])[0].strip()
                if what == "rail" and not TOKEN.fullmatch(text):
                    note = ("bad", "Not saved: that does not look like a token")
                elif store.ask(what, text if what == "rail" else ""):
                    self.log(f"asked for {what}")
                    until = time.monotonic() + HOLD
                    while store.result(what).busy and time.monotonic() < until:
                        time.sleep(0.25)
                    result = store.result(what)
                    if result.state == "waiting":
                        store.withdraw(what)
                        result = result._replace(state="failed", text="The printer program is not answering. Nothing was changed.")
                    note = ("good" if result.state == "done" else "bad", result.text or "It is taking long. Look again in a moment.")
                else:
                    note = ("bad", "That was asked for a moment ago. Wait a minute.")
            else:
                raise Refused(400)
        except OSError as exc:
            self.log(f"cannot store: {type(exc).__name__}")
        session.notes = {where: note}
        self.go(f"/password#{where}")

    def ask(self, form: dict, session: Session) -> None:
        kind, back = form.get("kind", [""])[0], form.get("back", ["/"])[0]
        if kind not in PAPER + SCREEN or back not in pages.SHOW:
            raise Refused(400)
        store = self.server.store
        try:
            if store.ask(kind):
                self.log(f"asked for {kind}")
            elif kind in PAPER:
                session.notes[""] = ("bad", "It is already on its way." if store.result(kind).busy else "Wait 20 seconds between two of the same.")
        except OSError as exc:
            self.log(f"cannot ask: {type(exc).__name__}")
            session.notes[""] = ("bad", "The Pi could not take that down. Its small disk may be full or missing.")
        self.go(f"{back}#{kind}" if kind in SCREEN else back)

    def change(self, page: str, form: dict, session: Session) -> None:
        """Saves every group of settings the form holds. What is refused is shown again as it
        was typed; the others are saved all the same."""
        store = self.server.store
        current, original = store.current(), store.defaults()
        groups = [group for group in dict.fromkeys(form.get("group", [])) if pages.GROUPS.get(group) == page]
        if not current:
            session.notes = {"": ("bad", "Not saved: the printer program has not reported yet. Try again in a moment.")}
            session.draft = Draft(page, frozenset(groups), form)
            return self.go(page)
        reset, wrong = form.get("reset", [""])[0], {}
        unusable, done = set(store.stored()) - set(store.changes()), []
        for group in groups:
            try:
                value = None if group == reset else FORMS[group](form, current[group], original[group])
                was = form.get(f"was-{group}", [""])[0]  # what another page has saved since then stays
                if group in unusable or value != current[group] and fingerprint(value) != was:
                    store.reset(group) if group == reset else store.change(group, value)
                    self.log(f"changed {group}")
                    done.append(group)
            except ValueError as exc:
                text = str(exc)
                wrong[group] = f"Not saved: {text[:1].lower()}{text[1:]}"
            except OSError as exc:
                self.log(f"cannot save: {type(exc).__name__}")
                wrong[group] = "Not saved: the Pi could not store it. Its small disk may be full or missing."
        def names(which) -> str:
            return ", ".join(pages.SHEETS[group] for group in which if group in pages.SHEETS)
        if wrong:
            others = f". Saved all the same: {names(done)}" if names(done) else ""
            session.notes = {group: ("bad", text + others) for group, text in wrong.items()}
            session.draft = Draft(page, frozenset(wrong), form)
            return self.go(f"{page}#{next(iter(wrong))}")
        move, preview = form.get("move", [""])[0], form.get("preview", [""])[0]
        if move and page == "/receipt":  # back to the arrow that was pressed, which gets the focus
            way, _, name = move.partition(":")
            chosen = store.current()["sections"]
            if name in chosen:
                place = chosen.index(name)
                session.notes = {f"row-{name}": ("good", f"Saved, now number {place + 1}")}
                stuck = place == (0 if way == "up" else len(chosen) - 1)  # that arrow is off now: one press more must not undo it
                return self.go(f"{page}#{'on' if stuck else way}-{name}" if way in ("up", "down") else page)
            return self.go(page)
        where = next((group for group in (reset, preview, form.get("save", [""])[0]) if group in groups), groups[0] if len(groups) == 1 else done[0] if done else "")
        also = names(group for group in done if group != where)
        session.notes = {where: ("good", ("Back to the original" if reset else "Saved") + (f". Also saved: {also}" if also and where else ""))}
        kind = "preview-trains" if preview == "trains" else "preview"
        if preview:
            session.notes = {kind: ("good", "Saved")}
        if preview or done and page == "/content":  # a new picture by itself; on Receipt nothing needs to be fetched
            try:
                store.ask(kind)
            except OSError:
                pass  # saved all the same; the old preview stays
        if preview:
            return self.go(f"{page}#{kind}")
        self.go(f"{page}#{where}" if where else page)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    address_family = socket.AF_UNIX

    def __init__(self, listener: socket.socket, host: str, auth: Auth, store: Store) -> None:
        BaseServer.__init__(self, "", Handler)  # the others would make a socket, which is not allowed here
        self.socket = listener
        self.host, self.auth, self.store = host, auth, store
        self.slots = threading.BoundedSemaphore(MAX_CLIENTS)
        self.last_used = time.monotonic()

    def process_request(self, request, address) -> None:
        self.last_used = time.monotonic()
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except RuntimeError:  # no threads left
            self.slots.release()
            request.close()

    def process_request_thread(self, request, address) -> None:
        try:
            with request:
                request.settimeout(SOCKET_TIMEOUT)
                self.RequestHandlerClass(request, (visitor(request), 0), self)
        except (OSError, ValueError):
            pass  # dropped connections
        finally:
            self.slots.release()
            self.last_used = time.monotonic()

    def service_actions(self) -> None:
        if time.monotonic() - self.last_used > IDLE_EXIT:
            threading.Thread(target=self.shutdown, daemon=True).start()


def visitor(request: socket.socket) -> str:
    """The first line, read byte by byte so nothing of the request is taken with it."""
    line = b""
    while not line.endswith(b"\n"):
        byte = request.recv(1)
        if not byte or len(line) > 60:
            raise ValueError("no address")
        line += byte
    return str(ipaddress.ip_address(line.decode("ascii").strip().split("%")[0]))


def main() -> None:
    os.umask(0o007)
    store = Store()
    try:
        auth = Auth(load_password(store.password, (CREDENTIALS / "password").read_text()), changed=store.password)
    except (ValueError, OSError) as exc:
        sys.exit(f"{exc}. On the Pi: cd reporter && bash deploy/setup-web.sh --new-password")
    if os.environ.get("LISTEN_FDS"):
        listener = socket.socket(fileno=3)
    else:  # tests only
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(os.environ["WEB_SOCKET"])
        listener.listen()
        print("ready", flush=True)
    host = os.environ["WEB_HOST"]  # exactly what browsers send, like printer.example.com:8444
    pages.DROP = f"{host.partition(':')[0]}:8443"
    Server(listener, host, auth, store).serve_forever(poll_interval=1)
