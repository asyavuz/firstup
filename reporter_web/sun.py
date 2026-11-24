"""Sunrise and sunset, worked out from the position alone (to a minute or two)."""

from datetime import date, datetime, timedelta, timezone
from math import acos, asin, cos, degrees, radians, sin
from typing import NamedTuple, Optional

ALTITUDE = -0.833  # degrees: the sun's upper edge, seen through the air


class Sun(NamedTuple):
    rise: datetime
    set: datetime


def sun(day: date, latitude: float, longitude: float) -> Optional[Sun]:
    """In UTC; None where the sun does not rise or set that day."""
    days = (day - date(2000, 1, 1)).days
    noon = days + 0.0009 - longitude / 360
    anomaly = radians((357.5291 + 0.98560028 * noon) % 360)
    centre = 1.9148 * sin(anomaly) + 0.02 * sin(2 * anomaly) + 0.0003 * sin(3 * anomaly)
    along = radians((degrees(anomaly) + centre + 282.9372) % 360)
    transit = noon + 0.0053 * sin(anomaly) - 0.0069 * sin(2 * along)
    tilt = asin(sin(along) * sin(radians(23.4397)))
    angle = (sin(radians(ALTITUDE)) - sin(radians(latitude)) * sin(tilt)) / (cos(radians(latitude)) * cos(tilt))
    if not -1 <= angle <= 1:
        return None
    half = degrees(acos(angle)) / 360
    start = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    return Sun(start + timedelta(days=transit - half), start + timedelta(days=transit + half))


def sky(now: datetime, latitude: float, longitude: float) -> str:
    """Which of the four skies to draw."""
    there = now.astimezone(timezone.utc) + timedelta(hours=longitude / 15)  # by the sun, not by law
    day = sun(there.date(), latitude, longitude)
    if day is None:
        return "day" if 4 <= now.month <= 9 else "night"
    if day.rise - timedelta(minutes=45) <= now < day.rise + timedelta(minutes=75):
        return "dawn"
    if day.set - timedelta(minutes=75) <= now < day.set + timedelta(minutes=45):
        return "dusk"
    return "day" if day.rise <= now < day.set else "night"


def beside_sunrise(moment: datetime, latitude: float, longitude: float) -> str:
    """Like "27 minutes after sunrise", if that says anything; otherwise ""."""
    day = sun(moment.date(), latitude, longitude)
    if day is None:
        return ""
    minutes = round((moment - day.rise).total_seconds() / 60)
    if abs(minutes) > 180:
        return ""
    if minutes == 0:
        return "at sunrise"
    size = abs(minutes)
    words = f"{size} minute{'s' if size != 1 else ''}" if size < 60 else \
        f"{size // 60} hour{'s' if size >= 120 else ''}" + (f" {size % 60} minutes" if size % 60 else "")
    return f"{words} {'after' if minutes > 0 else 'before'} sunrise"
