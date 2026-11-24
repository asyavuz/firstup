from datetime import datetime
from typing import List, NamedTuple, Optional, Sequence, Tuple

from PIL import Image

from .. import http
from ..pictograms import pictogram
from ..render import PAD, RIGHT, WIDTH, Canvas, font, icon, line_height, wrap

URL = "https://api.open-meteo.com/v1/forecast"
SLOTS = ((8, "Morning"), (12, "Noon"), (16, "Afternoon"), (20, "Evening"))
LABEL_X, LABEL_WIDTH = 96, 185  # "Feels like" starts right of this
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
CELL, CELL_TEXT = WIDTH // 3, 38  # grid of wind, humidity and so on
# Upper bound (exclusive, km/h) of Beaufort forces 0 to 11; anything above is 12.
BEAUFORT = (1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118)

# WMO weather codes used by Open-Meteo: label, day icon, night icon.
_CLEAR = ("wi-day-sunny.svg.png", "wi-night-clear.svg.png")
_FAIR = ("wi-day-sunny-overcast.svg.png", "wi-night-alt-partly-cloudy.svg.png")
WMO = {
    0: ("Clear",) + _CLEAR, 1: ("Mostly Clear",) + _CLEAR,
    2: ("Partly Cloudy",) + _FAIR, 3: ("Overcast", "wi-cloudy.svg.png"),
    45: ("Fog", "wi-fog.svg.png"), 48: ("Icy Fog", "wi-fog.svg.png"),
    51: ("Light Drizzle", "wi-sprinkle.svg.png"), 53: ("Drizzle", "wi-sprinkle.svg.png"),
    55: ("Heavy Drizzle", "wi-sprinkle.svg.png"),
    56: ("Icy Drizzle", "wi-sleet.svg.png"), 57: ("Icy Drizzle", "wi-sleet.svg.png"),
    61: ("Light Rain", "wi-rain.svg.png"), 63: ("Rain", "wi-rain.svg.png"),
    65: ("Heavy Rain", "wi-rain.svg.png"),
    66: ("Icy Rain", "wi-sleet.svg.png"), 67: ("Icy Rain", "wi-sleet.svg.png"),
    71: ("Light Snow", "wi-snow.svg.png"), 73: ("Snow", "wi-snow.svg.png"),
    75: ("Heavy Snow", "wi-snow.svg.png"), 77: ("Snow Grains", "wi-snow.svg.png"),
    80: ("Light Showers", "wi-showers.svg.png"), 81: ("Showers", "wi-showers.svg.png"),
    82: ("Heavy Showers", "wi-showers.svg.png"),
    85: ("Snow Showers", "wi-snow.svg.png"), 86: ("Snow Showers", "wi-snow.svg.png"),
    95: ("Thunderstorm", "wi-thunderstorm.svg.png"),
    96: ("Thunderstorm", "wi-thunderstorm.svg.png"), 99: ("Thunderstorm", "wi-thunderstorm.svg.png"),
}


# An hour counts as wet when rain is both likely and more than a trace.
WET_PROBABILITY, WET_MM = 40, 0.1
SNOW_CODES = frozenset((71, 73, 75, 77, 85, 86))
DAY_ENDS = 23  # hours after this do not matter for planning the day


# UV index: protection is advised from 3 (the default of weather.uv_from). Whole numbers,
# as the index is published.
UV_LEVELS = ((11, "extreme"), (8, "very high"), (6, "high"), (3, "moderate"), (0, "low"))
UV_TEXT_X, UV_ICON, UV_STEP = PAD + 50, 40, 48


class Sun(NamedTuple):
    index: int
    level: str
    hours: str


class Slot(NamedTuple):
    label: str
    temp: int
    icon: str


class Weather(NamedTuple):
    sunrise: str
    sunset: str
    temp: int
    feels_like: int
    label: str
    icon: str
    wind: int
    gust: int
    direction: str
    humidity: int
    pressure: int
    uv: float
    slots: List[Slot]
    outlook: str
    wet: bool
    sun: Optional[Sun] = None


def describe(code: int, is_day: bool) -> Tuple[str, str]:
    label, *icons = WMO.get(code, ("Unknown", "wi-na.svg.png"))
    return label, icons[0] if is_day or len(icons) == 1 else icons[1]


def compass(degrees: float) -> str:
    return COMPASS[round(degrees / 22.5) % 16]


def beaufort(kmh: float) -> int:
    return next((force for force, limit in enumerate(BEAUFORT) if kmh < limit), 12)


def wet_spells(hours: Sequence[int]) -> List[Tuple[int, int]]:
    """[9, 10, 15] becomes [(9, 11), (15, 16)]: start hour and end hour."""
    spells: List[Tuple[int, int]] = []
    for hour in hours:
        if spells and spells[-1][1] == hour:
            spells[-1] = (spells[-1][0], hour + 1)
        else:
            spells.append((hour, hour + 1))
    return spells


def outlook(payload, from_hour: int) -> Tuple[str, bool]:
    """One line on the rest of the day, and whether it is wet."""
    hourly, daily = payload["hourly"], payload["daily"]
    low, high = round(daily["temperature_2m_min"][0]), round(daily["temperature_2m_max"][0])
    temps = f"{low} to {high}°C" if low != high else f"{high}°C"
    wet, snow = [], 0
    ahead = range(from_hour, DAY_ENDS)
    for i, stamp in enumerate(hourly["time"]):
        hour = datetime.fromisoformat(stamp).hour
        likely = (hourly["precipitation_probability"][i] or 0) >= WET_PROBABILITY
        if hour in ahead and likely and (hourly["precipitation"][i] or 0) >= WET_MM:
            wet.append(hour)
            snow += hourly["weather_code"][i] in SNOW_CODES
    if not wet:
        return f"{temps}, dry {'all day' if from_hour < 12 else 'for the rest of today'}", False
    kind = "Snow" if snow * 2 > len(wet) else "Rain"
    spells = wet_spells(wet)
    if len(wet) >= 0.75 * len(ahead):
        when = "most of the day"
    elif len(spells) > 2:
        when = f"on and off {spells[0][0]:02d}:00–{spells[-1][1]:02d}:00"
    else:
        when = " and ".join(f"{a:02d}:00–{b:02d}:00" for a, b in spells)
    return f"{temps}. {kind} {when}", True


def sun_warning(payload, from_hour: int, uv_from: int = 3) -> Optional[Sun]:
    """The strongest UV still to come today, if it reaches `uv_from`."""
    hourly = payload["hourly"]
    strong = {}
    for stamp, value in zip(hourly["time"], hourly.get("uv_index") or []):
        hour, index = datetime.fromisoformat(stamp).hour, int((value or 0) + 0.5)
        if hour >= from_hour and index >= uv_from:
            strong[hour] = index
    if not strong:
        return None
    top = max(strong.values())
    level = next(name for limit, name in UV_LEVELS if top >= limit)
    return Sun(top, level, f"{min(strong):02d}:00–{max(strong) + 1:02d}:00")


def parse(payload, from_hour: int = 8, uv_from: int = 3) -> Weather:
    cur, hourly, daily = payload["current"], payload["hourly"], payload["daily"]
    by_hour = {datetime.fromisoformat(t).hour: i for i, t in enumerate(hourly["time"])}
    slots = []
    for hour, label in SLOTS:
        i = by_hour[hour]
        _, icon_name = describe(hourly["weather_code"][i], bool(hourly["is_day"][i]))
        slots.append(Slot(label, round(hourly["temperature_2m"][i]), icon_name))
    label, icon_name = describe(cur["weather_code"], bool(cur["is_day"]))
    summary, wet = outlook(payload, from_hour)
    return Weather(
        sunrise=daily["sunrise"][0][-5:], sunset=daily["sunset"][0][-5:],
        temp=round(cur["temperature_2m"]), feels_like=round(cur["apparent_temperature"]),
        label=label, icon=icon_name,
        wind=round(cur["wind_speed_10m"]), gust=round(cur["wind_gusts_10m"]),
        direction=compass(cur["wind_direction_10m"]),
        humidity=round(cur["relative_humidity_2m"]), pressure=round(cur["pressure_msl"]),
        uv=round(daily["uv_index_max"][0], 1), slots=slots,
        outlook=summary, wet=wet, sun=sun_warning(payload, from_hour, uv_from),
    )


def fetch(cfg, session, now) -> Weather:
    params = {
        **cfg.weather.position,
        "timezone": cfg.timezone,
        "forecast_days": 1,
        "wind_speed_unit": "kmh",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                   "pressure_msl,wind_speed_10m,wind_gusts_10m,wind_direction_10m,is_day",
        "hourly": "temperature_2m,weather_code,is_day,precipitation_probability,precipitation,uv_index",
        "daily": "sunrise,sunset,uv_index_max,temperature_2m_max,temperature_2m_min",
    }
    return parse(http.get(session, URL, params=params).json(), now.hour, cfg.weather.uv_from)


def _render_sun(canvas: Canvas, data: Weather) -> None:
    fnt = font("bold", 30)
    icons = (icon("wi-sunrise.svg.png", 35), icon("wi-sunset.svg.png", 35))
    times = (data.sunrise, data.sunset)
    widths = [i.width + 6 + fnt.getlength(t) for i, t in zip(icons, times)]
    x = (WIDTH - sum(widths) - 40) / 2
    for img, text, width in zip(icons, times, widths):
        canvas.icon(img, x, 18 - img.height / 2)
        canvas.text(x + img.width + 6, 18, text, fnt, "lm")
        x += width + 40
    canvas.y = 34


def _render_outlook(canvas: Canvas, data: Weather) -> None:
    fnt = font("bold", 22)
    mark = icon("wi-umbrella.svg.png", 34) if data.wet else None
    indent = mark.width + 10 if mark else 0
    lines = wrap(data.outlook, fnt, WIDTH - 2 * PAD - indent, 3)
    width = max(fnt.getlength(line) for line in lines)
    left = (WIDTH - width - indent) / 2
    height = len(lines) * line_height(fnt)
    if mark:
        canvas.icon(mark, left, canvas.y + (height - mark.height) / 2)
    for line in lines:
        canvas.text(left + indent, canvas.y, line, fnt)
        canvas.y += line_height(fnt)


def _render_uv(canvas: Canvas, sun: Sun) -> None:
    canvas.y += 6
    canvas.icon(pictogram("uv", 40), PAD, canvas.y)
    canvas.text(UV_TEXT_X, canvas.y - 2, f"UV {sun.index}, {sun.level}", font("bold", 22))
    canvas.text(UV_TEXT_X, canvas.y + 24, sun.hours, font("semibold", 20))
    names = ("sunscreen", "hat", "shade")
    for i, name in enumerate(names):
        canvas.icon_centred(pictogram(name, UV_ICON), RIGHT - UV_STEP * (len(names) - i - 0.5), canvas.y + 22)
    canvas.y += 52


def render(data: Weather, now: datetime) -> Image.Image:
    canvas = Canvas()
    _render_sun(canvas, data)
    canvas.rule()

    body = font("semibold", 20)
    top = canvas.y + 6
    canvas.icon_centred(icon(data.icon, 76), PAD + 42, top + 36)
    canvas.text(LABEL_X, top - 6, f"{data.temp}°C", font("bold", 46))
    canvas.text(LABEL_X, top + 48, data.label, font("semibold", 22))
    canvas.text(RIGHT, top, "Feels like", body, "ra")
    canvas.text(RIGHT, top + 22, f"{data.feels_like}°C", font("bold", 30), "ra")
    canvas.y = top + 88

    cells = (
        (f"wi-wind-beaufort-{beaufort(data.wind)}.svg.png", f"{data.wind} km/h"),
        ("wi-strong-wind.svg.png", f"{data.gust} km/h"),
        ("wi-wind-deg.svg.png", data.direction),
        ("wi-humidity.svg.png", f"{data.humidity}%"),
        ("wi-barometer.svg.png", str(data.pressure)),
        ("uv", f"{data.uv:g}"),
    )
    for i, (icon_name, text) in enumerate(cells):
        x, mid = (i % 3) * CELL, canvas.y + 14 + (i // 3) * 36
        canvas.icon_centred(pictogram("uv", 28) if icon_name == "uv" else icon(icon_name, 28), x + 20, mid)
        canvas.text(x + CELL_TEXT, mid, text, body, "lm")
    canvas.y += 2 * 36 + 8

    column = WIDTH / len(data.slots)
    for i, slot in enumerate(data.slots):
        cx = column * (i + 0.5)
        canvas.text(cx, canvas.y, f"{slot.temp}°C", font("bold", 23), "ma")
        canvas.icon_centred(icon(slot.icon, 40), cx, canvas.y + 52)
        canvas.text(cx, canvas.y + 76, slot.label, font("bold", 19), "ma")
    canvas.y += 76 + line_height(font("bold", 19)) + 6
    _render_outlook(canvas, data)
    if data.sun:
        _render_uv(canvas, data.sun)
    canvas.y += 2
    return canvas.finish()
