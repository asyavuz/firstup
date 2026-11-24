"""Departures from one station for the next hour.

Data: Realtime Trains (api-portal.rtt.io), free for personal use. It needs a token, which
`reporter rail-setup` stores in a file only this account can read. The specification is at
github.com/realtimetrains/api-specification.
"""

import dataclasses
import getpass
import logging
import re
from datetime import datetime, timedelta
from typing import List, NamedTuple, Optional, Union

from PIL import Image

from . import http, private, render, stations
from .config import TrainSettings
from .render import PAD, RIGHT, WIDTH, Canvas, clean, fit, font, line_height

log = logging.getLogger(__name__)

PATH = private.FOLDER / "rail.json"
BASE = "https://data.rtt.io"
UPCOMING = 120  # minutes after the start in which to look for the first trains
LATE = 30  # minutes back to look for trains that should have gone but have not
MAX_ROWS = 40
CALLS = ("ADVERTISED_OPEN", "ADVERTISED_PICK_UP")
GONE = ("CANCELLED", "DIVERTED")
TIME_X, PLACE_X, PLATFORM_X = PAD, 66, 280


class Token(NamedTuple):
    token: str
    kind: str  # "refresh" must be swapped for a short-lived one, "access" is used as it is


class Train(NamedTuple):
    due: datetime
    place: str
    platform: str  # "" when not known
    expected: str  # "On time", "14:36", "Cancelled", or "" when nothing is known yet
    leaves: Optional[datetime] = None  # when it really goes, as far as is known


class Board(NamedTuple):
    station: str
    trains: List[Train]


def load_token() -> Optional[Token]:
    try:
        token = Token(**(private.read(PATH) or {}))
    except TypeError:
        return None
    return token if valid(token.token) and token.kind in ("refresh", "access") else None


def valid(token: object) -> bool:
    return isinstance(token, str) and bool(re.fullmatch(r"[A-Za-z0-9._~+/=-]{16,4096}", token))


def _time(value: Optional[str], now: datetime) -> Optional[datetime]:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (moment if moment.tzinfo else moment.replace(tzinfo=now.tzinfo)).astimezone(now.tzinfo)


def _train(service: dict, now: datetime, until: datetime) -> Optional[Train]:
    """None for anything nobody can board here in that time."""
    times, about = service.get("temporalData") or {}, service.get("scheduleMetadata") or {}
    departure = times.get("departure") or {}
    due = _time(departure.get("scheduleAdvertised"), now)
    if due is None or about.get("inPassengerService") is False or times.get("displayAs") in (None, "PASS", "TERMINATES"):
        return None
    if times.get("scheduledCallType") not in CALLS and times.get("realtimeCallType") not in CALLS:
        return None
    if departure.get("realtimeActual"):
        return None  # already gone
    cancelled = bool(departure.get("isCancelled")) or times.get("displayAs") in GONE
    forecast = _time(departure.get("realtimeForecast"), now)
    leaves = due if cancelled or forecast is None else forecast
    if not now - timedelta(minutes=1) <= leaves <= until:
        return None
    late = forecast is not None and (forecast.replace(second=0, microsecond=0) - due).total_seconds() >= 60
    expected = "Cancelled" if cancelled else "" if forecast is None else f"{forecast:%H:%M}" if late else "On time"
    platform = (service.get("locationMetadata") or {}).get("platform") or {}
    bus = "BUS" in str(about.get("modeType") or "")
    places = [clean(str((d.get("location") or {}).get("description") or "")) for d in service.get("destination") or []]
    return Train(due, " & ".join(p for p in places if p) or "Unknown",
                 "bus" if bus else clean(str(platform.get("actual") or platform.get("planned") or "")), expected, leaves)


def parse(payload: dict, now: datetime, minutes: int = 60) -> Board:
    until = now + timedelta(minutes=minutes)
    trains = [_train(service, now, until) for service in payload.get("services") or []]
    station = ((payload.get("query") or {}).get("location") or {}).get("description")
    return Board(clean(str(station or "")), sorted((t for t in trains if t), key=lambda t: t.due))


def _ask(session, token: str, path: str, **params) -> dict:
    # No redirects: they would carry the token to another address.
    reply = http.get(session, BASE + path, params=params, redirects=False,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if reply.redirect:
        raise RuntimeError("unexpected redirect")
    return reply.json() if reply.content else {}  # an empty reply means no trains


def _access(session, token: Token) -> str:
    if token.kind == "access":
        return token.token
    access = _ask(session, token.token, "/api/get_access_token").get("token")
    if not valid(access):
        raise RuntimeError("no access token")
    return access


def fetch(settings: TrainSettings, token: Token, session, now: datetime) -> Board:
    params = {"code": f"gb-nr:{settings.station}", "timeWindow": settings.minutes + LATE,
              "timeFrom": f"{now - timedelta(minutes=LATE):%Y-%m-%dT%H:%M:%S}"}
    if settings.towards:
        params["filterTo"] = f"gb-nr:{settings.towards}"
    return parse(_ask(session, _access(session, token), "/rtt/location", **params), now, settings.minutes)


def upcoming(settings: TrainSettings, token: Token, session, now: datetime, start: datetime) -> Board:
    """The first trains that leave from `start` on; cancelled ones are shown but not counted."""
    ahead = int((start - now).total_seconds() // 60) + UPCOMING
    board = fetch(dataclasses.replace(settings, minutes=ahead), token, session, now)
    chosen: List[Train] = []
    running = 0
    for train in sorted(board.trains, key=lambda t: t.leaves or t.due):
        if (train.leaves or train.due) < start.replace(second=0, microsecond=0):
            continue
        chosen.append(train)
        running += train.expected != "Cancelled"
        if running == settings.count or len(chosen) == 2 * settings.count:
            break
    return Board(board.station, chosen)


def _row(canvas: Canvas, train: Train) -> None:
    body, strong = font("semibold", 20), font("bold", 20)
    plain = train.expected == "On time"
    expected = fit(train.expected or "–", body if plain else strong, 100)
    canvas.text(TIME_X, canvas.y, f"{train.due:%H:%M}", strong)
    canvas.text(PLACE_X, canvas.y, fit(train.place, body, PLATFORM_X - 34 - PLACE_X), body)
    canvas.text(PLATFORM_X, canvas.y, fit(train.platform, body, 36), body, "ra")
    canvas.text(RIGHT, canvas.y, expected, body if plain else strong, "ra")
    canvas.y += line_height(body) + 3


def page(settings: TrainSettings, board: Board, now: datetime) -> Image.Image:
    canvas = Canvas()
    canvas.heading(fit(board.station or settings.station, font("bold", 26), WIDTH - 2 * PAD))
    small = font("semibold", 18)
    if settings.towards:
        station = stations.find(settings.towards)
        calling, strong = f"Calling at {station.name if station else settings.towards}", font("bold", 20)
        canvas.text(WIDTH / 2, canvas.y, fit(calling, strong, WIDTH - 2 * PAD), strong, "ma")
        canvas.y += line_height(strong) + 2
    hour = "hour" if settings.minutes == 60 else f"{settings.minutes} minutes"
    canvas.text(WIDTH / 2, canvas.y, f"Next {hour}, from {now:%H:%M}", small, "ma")
    canvas.y += line_height(small) + 2
    canvas.rule()
    if board.trains:
        for x, label, anchor in ((TIME_X, "Due", "la"), (PLACE_X, "To", "la"),
                                 (PLATFORM_X + 4, "Plat", "ra"), (RIGHT, "Expected", "ra")):
            canvas.text(x, canvas.y, label, small, anchor)
        canvas.y += line_height(small) + 2
    for train in board.trains[:MAX_ROWS]:
        _row(canvas, train)
    if len(board.trains) > MAX_ROWS:
        canvas.text(WIDTH / 2, canvas.y, f"and {len(board.trains) - MAX_ROWS} more", small, "ma")
        canvas.y += line_height(small)
    if not board.trains:
        body = font("semibold", 20)
        canvas.text(WIDTH / 2, canvas.y, "No trains", body, "ma")
        canvas.y += line_height(body)
    canvas.y += 4
    canvas.text(WIDTH / 2, canvas.y, "Data: Realtime Trains", small, "ma")
    canvas.y += line_height(small) + 4
    return render.to_bitmap(canvas.finish())


def ask(settings: TrainSettings, now: datetime) -> Union[Board, str]:
    """The trains, or a line saying why there are none."""
    token = load_token()
    if token is None:
        return "Train times are not set up"
    try:
        return fetch(settings, token, http.make_session(), now)
    except Exception as exc:
        log.warning("no train times: %s", http.trace(exc))
        return "Train times unavailable"


def draw(settings: TrainSettings, found: Union[Board, str], now: datetime) -> Image.Image:
    return render.to_bitmap(render.notice(found)) if isinstance(found, str) else page(settings, found, now)


def build(settings: TrainSettings, now: datetime) -> Image.Image:
    return draw(settings, ask(settings, now), now)


class NoToken(Exception):
    """Says why it was not kept."""


def keep(text: str, settings: TrainSettings, now: datetime) -> str:
    """Tries a token and keeps it if it works."""
    if not valid(text):
        raise NoToken("that does not look like a token")
    problem = ""
    for kind in ("refresh", "access"):  # the portal gives out either
        token = Token(text, kind)
        try:
            board = fetch(settings, token, http.make_session(), now)
        except Exception as exc:
            problem = http.reason(exc)
            continue
        private.write(PATH, token._asdict())
        return f"Saved and working: {len(board.trains)} departures from {board.station or settings.station}"
    raise NoToken(problem)


def setup(settings: TrainSettings, now: datetime) -> int:
    try:
        print(keep(getpass.getpass("Realtime Trains token (hidden): ").strip(), settings, now) + ".")
    except NoToken as exc:
        print(f"Not saved: {exc}.")
        return 1
    return 0
