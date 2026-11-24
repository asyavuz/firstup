"""Password, sessions and slowing down guesses."""

import getpass
import hashlib
import hmac
import os
import re
import secrets
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, NamedTuple, Optional, Tuple

from reporter import settings

N, R, P, SIZE = 2 ** 15, 8, 1, 32  # 32 MB and a good fraction of a second on a Pi 3
MIN_LENGTH, MAX_LENGTH = 12, 200
IDLE, LONGEST = 30 * 60, 12 * 3600  # seconds
MAX_SESSIONS = 8
FREE_TRIES, MAX_DELAY = 5, 120


def _scrypt(password: str, salt: bytes) -> bytes:
    text = unicodedata.normalize("NFC", password).encode()
    return hashlib.scrypt(text, salt=salt, n=N, r=R, p=P, dklen=SIZE, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise ValueError(f"use {MIN_LENGTH} to {MAX_LENGTH} characters")
    salt = secrets.token_bytes(16)
    return f"scrypt:{salt.hex()}:{_scrypt(password, salt).hex()}"


def check_stored(stored: str) -> Tuple[bytes, bytes]:
    parts = re.fullmatch(rf"scrypt:([0-9a-f]{{32}}):([0-9a-f]{{{2 * SIZE}}})", stored.strip())
    if parts is None:
        raise ValueError("the stored password is damaged")
    return bytes.fromhex(parts[1]), bytes.fromhex(parts[2])


def verify(password: str, stored: str) -> bool:
    salt, digest = check_stored(stored)
    return len(password) <= MAX_LENGTH and hmac.compare_digest(_scrypt(password, salt), digest)


def load_password(changed: Path, original: str) -> str:
    """The password changed on the web page if there is one, else the one set on the Pi. A
    damaged file is not skipped: that could bring an old password back."""
    try:
        stored = changed.read_text()
    except FileNotFoundError:
        stored = original
    check_stored(stored)
    return stored


def save_password(path: Path, stored: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as out:
            out.write(stored + "\n")
            out.flush()
            os.fsync(out.fileno())
        settings.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Locked(Exception):
    """Too many wrong passwords; nothing was even checked."""


class Throttle:
    """After a few wrong passwords, each further one costs more waiting, for everybody:
    there is one user, and addresses on a home network are easily changed."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock, self.failures, self.blocked_until = clock, 0, 0.0

    def open(self) -> bool:
        return self.clock() >= self.blocked_until

    def failed(self) -> None:
        self.failures += 1
        if self.failures >= FREE_TRIES:
            delay = min(MAX_DELAY, 2 ** min(self.failures - FREE_TRIES + 1, 20))
            self.blocked_until = self.clock() + delay

    def succeeded(self) -> None:
        self.failures, self.blocked_until = 0, 0.0


class Draft(NamedTuple):
    path: str
    groups: FrozenSet[str]
    form: Dict[str, List[str]]


class Session:
    def __init__(self, now: float) -> None:
        self.csrf = secrets.token_urlsafe(32)
        self.started = self.used = now
        self.notes: Dict[str, Tuple[str, str]] = {}  # where to say it: ("good" or "bad", text); shown once
        self.secret = ""  # a new phone token, until it has been shown once
        self.waits = 0  # pictures that wait for a new one
        self.draft: Optional[Draft] = None  # what was typed, if it was refused; shown once


class Login(NamedTuple):
    token: str
    session: Session


def _key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()


class Auth:
    def __init__(self, stored: str, clock: Callable[[], float] = time.monotonic, changed: Optional[Path] = None) -> None:
        check_stored(stored)
        self.stored, self.clock, self.changed = stored, clock, changed
        self.throttle = Throttle(clock)
        self.sessions: Dict[str, Session] = {}
        self.lock = threading.Lock()
        self.one_at_a_time = threading.Lock()  # checking a password takes a lot of memory

    def log_in(self, password: str) -> Optional[Login]:
        """None if it is wrong."""
        with self.one_at_a_time:
            if not self.throttle.open():
                raise Locked
            if not verify(password, self.stored):
                self.throttle.failed()
                return None
            self.throttle.succeeded()
            return self._start()  # before anybody can change the password

    def _start(self) -> Login:
        token, session = secrets.token_urlsafe(32), Session(self.clock())
        with self.lock:
            self._drop_old()
            while len(self.sessions) >= MAX_SESSIONS:
                del self.sessions[min(self.sessions, key=lambda k: self.sessions[k].used)]
            self.sessions[_key(token)] = session
        return Login(token, session)

    def change(self, current: str, new: str) -> Optional[Login]:
        """None if `current` is wrong; ValueError if `new` will not do. Ends every session, and
        starts one for whoever changed it."""
        if not MIN_LENGTH <= len(new) <= MAX_LENGTH:
            raise ValueError(f"Use {MIN_LENGTH} to {MAX_LENGTH} characters")
        with self.one_at_a_time:
            if not self.throttle.open():
                raise Locked
            if not verify(current, self.stored):
                self.throttle.failed()
                return None
            self.throttle.succeeded()
            if verify(new, self.stored):
                raise ValueError("That is the password you have")
            stored = hash_password(new)
            save_password(self.changed, stored)
            self.stored = stored
            with self.lock:
                self.sessions.clear()
            return self._start()

    def _drop_old(self) -> None:
        now = self.clock()
        for key in [k for k, s in self.sessions.items() if now - s.used > IDLE or now - s.started > LONGEST]:
            del self.sessions[key]

    def session(self, token: str) -> Optional[Session]:
        with self.lock:
            self._drop_old()
            session = self.sessions.get(_key(token)) if token else None
            if session:
                session.used = self.clock()
            return session

    def log_out(self, token: str) -> None:
        with self.lock:
            self.sessions.pop(_key(token), None)


def main() -> int:
    """Asks for a new password and writes what to store. Used by deploy/setup-web.sh."""
    first = getpass.getpass(f"New password for the web interface, at least {MIN_LENGTH} characters (hidden): ")
    if first != getpass.getpass("Again: "):
        print("They differ; nothing changed.", file=sys.stderr)
        return 1
    try:
        print(hash_password(first))
    except ValueError as exc:
        print(f"Nothing changed: {exc}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
