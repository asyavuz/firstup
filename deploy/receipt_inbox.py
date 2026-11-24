#!/usr/bin/python3 -I
"""Write-only HTTPS drop box for one day's calendar and reminders. Standard library only.

    POST /calendar        (or /reminders)
    Authorization: Bearer <token>
    {"list": "2026-11-24\\n09:30-10:00 Dentist\\nAll day Parents visiting"}

Started by receipt-inbox.socket when something connects, and exits when idle. It can
write one file for each and read nothing back: replies hold only a date and a count taken from
the request itself. The token is not stored on the Pi, only its SHA-256.
"""

import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MAX_BODY = 8192
MAX_DRAIN = 65536
MAX_CLIENTS, PER_ADDRESS = 10, 4
SOCKET_TIMEOUT, LIFETIME = 8, 20  # seconds
IDLE_EXIT = 45
DAYS_AHEAD = 2
PLACES = {"/calendar": ("events.txt", "event"), "/reminders": ("reminders.txt", "reminder")}

# The fingerprint of a token made in the web interface, which only leaves that here.
NEWER = Path(os.environ.get("INBOX_TOKEN", "/var/lib/reporter-web/phone/token.sha256"))
DROP = Path(os.environ.get("INBOX_DROP", "/var/lib/receipt-inbox/drop"))
CREDENTIALS = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/nonexistent"))


REASONS = {
    400: "Refused: the first line must be the date, like 2026-11-24, for today or the next two days",
    401: "Refused: wrong token",
    413: "Refused: list too long",
}


class Rejected(Exception):
    """Carries the HTTP status to answer with."""


def authorised(header, token_hash: str) -> bool:
    scheme, _, token = (header or "").partition(" ")
    given = hashlib.sha256(token.strip().encode()).hexdigest()
    return hmac.compare_digest(given, token_hash) and scheme.lower() == "bearer"


def token_hash(first: str) -> str:
    """The one that counts now. A damaged newer one lets nobody in: the first must not come back."""
    try:
        handle = os.open(NEWER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except (FileNotFoundError, NotADirectoryError):
        return first
    except OSError:
        return ""
    try:
        text = os.read(handle, 100).decode("ascii", "replace").strip()
    except OSError:
        return ""
    finally:
        os.close(handle)
    return text if re.fullmatch("[0-9a-f]{64}", text) else ""


def accept(body: bytes, today: date) -> str:
    """The text to store, or Rejected. Checks shape only; the printer side cleans it."""
    try:
        text = json.loads(body)["list"]
    except (ValueError, KeyError, TypeError, RecursionError):
        raise Rejected(400)
    if not isinstance(text, str) or "\x00" in text:
        raise Rejected(400)
    try:
        day = date.fromisoformat(text.strip().split("\n", 1)[0].strip())
    except ValueError:
        raise Rejected(400)
    if not today <= day <= today + timedelta(days=DAYS_AHEAD):
        raise Rejected(400)
    return text.strip() + "\n"


def summary(text: str, thing: str = "event") -> str:
    first, *rest = text.strip().split("\n")
    count = sum(1 for line in rest if line.strip())
    day = date.fromisoformat(first.strip())
    things = f"1 {thing}" if count == 1 else f"{count or 'no'} {thing}s"
    return f"Stored {things} for {day:%A} {day.day} {day:%B}"


def store(text: str, drop: Path, name: str = "events.txt") -> None:
    tmp = drop / f".in.{os.getpid()}.{threading.get_ident()}"
    try:
        tmp.write_text(text, encoding="utf-8", errors="replace")
        tmp.chmod(0o660)
        tmp.replace(drop / name)
    finally:
        tmp.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "inbox", ""
    timeout = SOCKET_TIMEOUT
    body_read = False

    def drain(self) -> None:
        """Read what is left of a refused request, or the client never sees the reply."""
        length = getattr(self, "headers", None) and self.headers.get("Content-Length", "")
        if not self.body_read and length and length.isdecimal():
            self.rfile.read(min(int(length), MAX_DRAIN))

    def reply(self, status: int, message: str = "") -> None:
        self.drain()
        body = (message or REASONS.get(status, "Refused")).encode()
        self.close_connection = True
        self.send_response_only(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            if self.path not in PLACES:
                raise Rejected(404)
            if not authorised(self.headers.get("Authorization"), token_hash(self.server.token_hash)):
                time.sleep(1)  # slows guessing; a 256-bit token cannot be guessed anyway
                raise Rejected(401)
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal():
                raise Rejected(411)
            if int(length) > MAX_BODY:
                raise Rejected(413)
            self.body_read = True
            text = accept(self.rfile.read(int(length)), datetime.now().date())
            name, thing = PLACES[self.path]
            store(text, DROP, name)
            self.reply(200, summary(text, thing))
            self.log("stored")
        except Rejected as rejected:
            self.reply(rejected.args[0])
            self.log(f"refused {rejected.args[0]}")

    def send_error(self, code, message=None, explain=None) -> None:
        self.reply(code if code in (400, 408, 414, 431) else 405)

    def log(self, what: str) -> None:
        print(f"{what} from {self.client_address[0]}", file=sys.stderr, flush=True)

    def log_message(self, *args) -> None:
        pass  # never write request contents to the log


def group(address: str) -> str:
    """One device can have any number of IPv6 addresses with the same first half."""
    ip = ipaddress.ip_address(address.removeprefix("::ffff:").split("%")[0])
    return str(ipaddress.ip_network((ip, 64), strict=False)) if ip.version == 6 else str(ip)


class Server(HTTPServer):
    def __init__(self, listener: socket.socket, context: ssl.SSLContext, token_hash: str) -> None:
        super().__init__(listener.getsockname()[:2], Handler, bind_and_activate=False)
        self.socket.close()
        self.socket = listener
        self.context, self.token_hash = context, token_hash
        self.lock = threading.Lock()
        self.clients: dict = {}  # a copy of each connection, with whose it is and until when
        self.last_used = time.monotonic()

    def process_request(self, request, address) -> None:
        self.last_used = time.monotonic()
        device = group(address[0])
        with self.lock:
            theirs = [each for each, _ in self.clients.values() if each == device]
            full = len(self.clients) >= MAX_CLIENTS or len(theirs) >= PER_ADDRESS
            copy = None if full else request.dup()
            if copy:
                self.clients[copy] = (device, time.monotonic() + LIFETIME)
        if copy:
            threading.Thread(target=self.serve, args=(request, address, copy), daemon=True).start()
        else:
            request.close()

    def serve(self, request, address, copy) -> None:
        try:
            request.settimeout(SOCKET_TIMEOUT)
            # The handshake happens here, in the worker, so a slow client blocks nobody.
            with self.context.wrap_socket(request, server_side=True) as secure:
                self.RequestHandlerClass(secure, address, self)
        except (OSError, ValueError):
            pass  # port scans, plain HTTP, dropped connections
        finally:
            with self.lock:
                self.clients.pop(copy, None)
            copy.close()
            self.last_used = time.monotonic()

    def service_actions(self) -> None:
        now = time.monotonic()
        with self.lock:
            late = [copy for copy, (_, until) in self.clients.items() if now > until]
            for copy in late:  # one byte now and then must not keep others out
                try:
                    copy.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if time.monotonic() - self.last_used > IDLE_EXIT:
            threading.Thread(target=self.shutdown, daemon=True).start()


def main() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(CREDENTIALS / "cert.pem", CREDENTIALS / "key.pem")
    first = (CREDENTIALS / "token.sha256").read_text().strip()
    if len(first) != 64:
        raise SystemExit("token hash is missing or malformed")
    listener = socket.socket(fileno=3) if os.environ.get("LISTEN_FDS") else socket.create_server(("127.0.0.1", 0))
    if not os.environ.get("LISTEN_FDS"):
        print(listener.getsockname()[1], flush=True)  # tests only
    Server(listener, context, first).serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
