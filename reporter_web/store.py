"""The web program's only contact with the rest: it writes the settings file and empty
request files, and reads what the reporter leaves in the `out` folder."""

import hashlib
import json
import os
import secrets
import stat
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from reporter import settings

PAPER = ("receipt", "trains", "health", "calibrate")  # these use paper
SCREEN = ("preview", "preview-trains", "status")
IMAGES = {"preview.png": "preview", "blocks.png": "preview", "trains.png": "preview-trains"}  # and what makes them
MAX_BYTES = 3_000_000
PAUSE = 20  # seconds between two of the same print
A_MINUTE = {"preview": 4, "preview-trains": 3, "status": 8, "rail": 3, "rail-forget": 3}  # more would stop reporter-requests.path, and bother the sources
STUCK = timedelta(minutes=15)  # no job takes this long
KEYS = ("rail", "rail-forget")  # the train token: handed over, never read back
UNANSWERED = 120  # seconds before a request counts as not picked up
FRESH = 60  # seconds a status counts as current


class Result(NamedTuple):
    state: str  # "", "waiting", "working", "done" or "failed"
    text: str
    at: Optional[datetime]

    @property
    def busy(self) -> bool:
        return self.state in ("waiting", "working")


def _moment(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _put(tmp: Path, path: Path, text: str) -> None:
    tmp.unlink(missing_ok=True)
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640), "w") as out:
            out.write(text + "\n")
            out.flush()
            os.fsync(out.fileno())
        settings.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Store:
    def __init__(self, base: Path = settings.BASE) -> None:
        self.settings = base / "settings" / "settings.json"
        self.password = base / "settings" / "password"  # only if changed on the page
        self.requests, self.out = base / "requests", base / "out"
        self.phone = base / "phone" / "token.sha256"
        self.lock, self.phone_lock = threading.Lock(), threading.Lock()
        self.asked: Dict[str, List[float]] = {}

    def read(self, name: str) -> Optional[bytes]:
        try:
            handle = os.open(self.out / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            return None
        with os.fdopen(handle, "rb") as file:
            if not stat.S_ISREG(os.fstat(handle).st_mode):
                return None
            data = file.read(MAX_BYTES + 1)
        return data if len(data) <= MAX_BYTES else None

    def _json(self, name: str) -> Dict[str, Any]:
        try:
            data = json.loads(self.read(name) or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def status(self) -> Dict[str, Any]:
        """Always the right shape, whatever the file holds."""
        data = self._json("status.json")
        rows, problems = (data[key] if isinstance(data.get(key), list) else [] for key in ("health", "problems"))
        return {"at": _moment(data.get("at")), "last_print": str(data.get("last_print") or ""),
                "health": [(str(r[0]), str(r[1])) for r in rows if isinstance(r, list) and len(r) == 2],
                "problems": [str(p) for p in problems], "defaults": data.get("defaults"), "rail_key": data.get("rail_key") is True}

    def image_time(self, name: str) -> int:
        """0 if there is no such picture."""
        try:
            return int((self.out / name).lstat().st_mtime)
        except OSError:
            return 0

    def blocks(self) -> Dict[str, Any]:
        """Where each block is in blocks.png; empty if that is not known."""
        data = self._json("blocks.json")
        height, places = data.get("height"), data.get("places")
        whole = lambda n: isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 100_000  # noqa: E731
        if not whole(height) or not isinstance(places, dict):
            return {}
        good = {name: place for name, place in places.items() if name in settings.SECTIONS and isinstance(place, list) and len(place) == 2 and all(map(whole, place))}
        return {"height": height, "places": good} if good else {}

    def changed(self) -> float:
        """When something was last saved here; 0 if never."""
        try:
            return self.settings.lstat().st_mtime
        except OSError:
            return 0

    # --- tokens ---

    def phone_ready(self) -> bool:
        return os.access(self.phone.parent, os.W_OK)

    def phone_changed(self) -> int:
        """When the phone's token was made here; 0 if it is still the first one."""
        try:
            return int(self.phone.lstat().st_mtime)
        except OSError:
            return 0

    def new_phone_token(self) -> str:
        """Only its fingerprint is kept; the drop box reads that."""
        token = secrets.token_urlsafe(32)
        _put(self.phone.with_name(f".token.{os.getpid()}.{threading.get_ident()}"), self.phone, hashlib.sha256(token.encode()).hexdigest())
        return token

    # --- settings ---

    def defaults(self) -> Dict[str, Any]:
        """What config.toml says, as the reporter last told us; empty if it has not yet."""
        told = self.status()["defaults"]
        if not isinstance(told, dict):
            return {}
        # A reporter that is newer than this program may know more: leave that out.
        told = {name: value for name, value in told.items() if name in settings.GROUPS}
        if isinstance(told.get("sections"), list):
            told["sections"] = [name for name in told["sections"] if name in settings.SECTIONS]
        if isinstance(told.get("button"), dict):
            told["button"] = {k: {n: v for n, v in d.items() if n in settings.PRESSABLE} if isinstance(d, dict) else d for k, d in told["button"].items()}
        good, problems = settings.check(told)
        return good if not problems and set(good) == set(settings.GROUPS) else {}

    def stored(self) -> List[str]:
        return settings.stored(self.settings)

    def changes(self) -> Dict[str, Any]:
        return settings.load(self.settings)[0]

    def current(self) -> Dict[str, Any]:
        defaults = self.defaults()
        return settings.merge(defaults, self.changes()) if defaults else {}

    def change(self, group: str, value: Any) -> None:
        """Raises ValueError, with words for the user, if the value is not allowed."""
        value = settings.GROUPS[group](value)
        with self.lock:
            # Not kept when it is the same as in the files, so later edits there still count.
            settings.change(group, None if value == self.defaults().get(group) else value, self.settings)

    def reset(self, group: str) -> None:
        with self.lock:
            settings.change(group, None, self.settings)

    # --- requests ---

    def ask(self, kind: str, text: str = "") -> bool:
        """False if that is already under way, or was printed a moment ago."""
        with self.lock:
            busy, now = self.result(kind), time.monotonic()
            if busy.state == "waiting" or busy.busy and kind in PAPER:
                return False
            asked = [then for then in self.asked.get(kind, []) if now - then < (PAUSE if kind in PAPER else 60)]
            if len(asked) >= A_MINUTE.get(kind, 1):
                return False
            try:
                # Not moved here from another folder: to the sandbox each is a disk of its own.
                handle = os.open(self.requests / kind, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640 if text else 0o660)
                try:
                    os.write(handle, text.encode())
                finally:
                    os.close(handle)
            except FileExistsError:
                return False
            self.asked[kind] = asked + [now]
            return True

    def _working(self) -> bool:
        """On something else, which comes first."""
        results = [self._json(f"result-{kind}.json") for kind in PAPER + SCREEN]
        starts = [_moment(data.get("at")) for data in results if data.get("state") == "working"]
        return any(at is not None and datetime.now(at.tzinfo) - at < STUCK for at in starts)

    def withdraw(self, kind: str) -> None:
        """Nobody took it in time; what it holds must not lie about."""
        try:
            (self.requests / kind).unlink(missing_ok=True)
        except OSError:
            pass

    def result(self, kind: str) -> Result:
        data = self._json(f"result-{kind}.json")
        at = _moment(data.get("at"))
        try:
            waited = time.time() - (self.requests / kind).lstat().st_mtime
            return Result("waiting", "", at) if waited < UNANSWERED or self._working() else Result("failed", "The printer program is not answering", at)
        except OSError:
            pass  # not waiting
        state, text = data.get("state"), data.get("text")
        if state not in ("working", "done", "failed") or at is None or not isinstance(text, str):
            return Result("", "", None)
        if state == "working" and datetime.now(at.tzinfo) - at > STUCK:
            return Result("failed", "It did not finish", at)
        return Result(state, text, at)

    def busy(self) -> List[str]:
        return [kind for kind in PAPER + SCREEN if self.result(kind).busy]

    def fresh(self, status: Dict[str, Any]) -> bool:
        return status["at"] is not None and abs((datetime.now(status["at"].tzinfo) - status["at"]).total_seconds()) <= FRESH

    def ask_if_stale(self) -> None:
        if not self.fresh(self.status()):
            try:
                self.ask("status")
            except OSError:
                pass  # the page is still worth showing
