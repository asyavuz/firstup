"""A page about the printer itself. Every check is optional: one that fails says so."""

import shutil
import socket
import ssl
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Tuple

from PIL import Image

from . import lists, render, schedule
from .config import Config, state_dir
from .render import PAD, RIGHT, Canvas, font, line_height

STAMP = Path("/var/lib/reporter/last-scheduled-print")


def _run(*command: str) -> str:
    return subprocess.run(command, capture_output=True, text=True, timeout=8, check=True).stdout.strip()


def _address(cfg: Config, now: datetime) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))  # no packet is sent; this only picks the route
        return probe.getsockname()[0]


def _uptime(cfg: Config, now: datetime) -> str:
    minutes = int(float(Path("/proc/uptime").read_text().split()[0]) // 60)
    days, hours = minutes // 1440, minutes // 60 % 24
    return f"{days} d {hours} h" if days else f"{hours} h {minutes % 60} min"


def _power(cfg: Config, now: datetime) -> str:
    bits = int(_run("vcgencmd", "get_throttled").split("=")[1], 16)
    dips = _run("journalctl", "-k", "-b", "--no-pager", "-o", "cat").lower().count("undervoltage detected")
    return "LOW NOW" if bits & 1 else f"{dips} dips since start" if dips else "good"


def _temperature(cfg: Config, now: datetime) -> str:
    return f"{int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000:.0f}°C"


def _wifi(cfg: Config, now: datetime) -> str:
    for line in _run("nmcli", "-t", "-f", "IN-USE,SIGNAL", "device", "wifi", "list", "--rescan", "no").splitlines():
        if line.startswith("*:"):
            return f"{line[2:]}% signal"
    return "not connected"


def _disk(cfg: Config, now: datetime) -> str:
    use = shutil.disk_usage("/")
    return f"{use.free / 1e9:.0f} GB free"


def stamp() -> Path:
    return STAMP if STAMP.exists() else state_dir(create=False) / STAMP.name


def _last_print(cfg: Config, now: datetime) -> str:
    day = schedule.read_stamp(stamp())
    return "never" if day is None else "today" if day == now.date() else f"{day:%a} {day.day} {day:%b}"


def _calendar(cfg: Config, now: datetime) -> str:
    path, _ = lists.paths(cfg)
    if not path.parent.is_dir():
        return "not set up"
    when = lists.arrived(path)
    return "no list" if when is None else f"list at {datetime.fromtimestamp(when, cfg.tz):%a %H:%M}"


def _reminders(cfg: Config, now: datetime) -> str:
    _, path = lists.paths(cfg)
    when = lists.arrived(path)
    return "none today" if when is None else f"list at {datetime.fromtimestamp(when, cfg.tz):%a %H:%M}"


def _certificate(cfg: Config, now: datetime) -> str:
    if not cfg.events.host:
        return "not set up"
    context = ssl.create_default_context()
    with socket.create_connection(("127.0.0.1", 8443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=cfg.events.host) as secure:
            ends = ssl.cert_time_to_seconds(secure.getpeercert()["notAfter"])
    days = int((ends - now.timestamp()) // 86400)
    return f"{days} days left" + (" - RENEW" if days < 14 else "")


def _settings(cfg: Config, now: datetime) -> str:
    return "good" if not cfg.problems else f"{len(cfg.problems)} ignored: {cfg.problems[0]}"


def _services(cfg: Config, now: datetime) -> str:
    failed = [line.split()[0] for line in _run("systemctl", "--failed", "--no-legend", "--plain").splitlines() if line]
    return "all running" if not failed else f"{len(failed)} failed: {failed[0]}"


CHECKS: Tuple[Tuple[str, Callable], ...] = (
    ("Address", _address), ("Wi-Fi", _wifi), ("Power", _power), ("Temperature", _temperature),
    ("Running for", _uptime), ("Storage", _disk), ("Services", _services),
    ("Last daily print", _last_print), ("Calendar", _calendar), ("Reminders", _reminders), ("Certificate", _certificate),
    ("Web settings", _settings),
)


def collect(cfg: Config, now: datetime) -> List[Tuple[str, str]]:
    results = []
    for label, check in CHECKS:
        try:
            results.append((label, check(cfg, now)))
        except Exception as exc:  # a health page must always print
            results.append((label, f"cannot tell ({type(exc).__name__})"))
    return results


def page(cfg: Config, now: datetime) -> Image.Image:
    canvas = Canvas()
    canvas.heading("Printer health")
    name, value = font("semibold", 20), font("bold", 20)
    for label, text in collect(cfg, now):
        canvas.text(PAD, canvas.y, label, name)
        room = RIGHT - PAD - 12 - name.getlength(label)
        canvas.text(RIGHT, canvas.y, render.fit(render.clean(text), value, room), value, "ra")
        canvas.y += line_height(name) + 3
    canvas.y += 4
    canvas.text(render.WIDTH / 2, canvas.y, f"{now:%A} {now.day} {now:%B}, {now:%H:%M}", name, "ma")
    canvas.y += line_height(name) + 4
    return render.to_bitmap(canvas.finish())
